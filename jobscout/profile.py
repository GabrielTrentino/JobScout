"""Perfil do usuário em profile.json e o dicionário de campos padrão."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIELDS = (
    "nome",
    "email",
    "telefone",
    "cidade",
    "linkedin",
    "github",
    "portfolio",
    "pretensao_salarial",
    "disponibilidade",
    "curriculo",
)

# Rótulos que a extensão compara (sem acento, minúsculo) para preencher campos padrão sem LLM.
LABELS = {
    "primeiro_nome": ("primeiro nome", "first name", "given name"),
    "sobrenome": ("sobrenome", "ultimo nome", "last name", "family name", "surname"),
    "nome": ("nome completo", "full name", "seu nome", "nome", "name"),
    "email": ("e-mail", "email", "endereco de email"),
    "telefone": ("telefone", "celular", "phone", "mobile", "whatsapp", "numero de contato"),
    "cidade": ("cidade", "city", "localizacao", "location", "onde voce mora"),
    "linkedin": ("linkedin",),
    "github": ("github",),
    "portfolio": ("portfolio", "site pessoal", "website", "personal site"),
    "pretensao_salarial": ("pretensao salarial", "expectativa salarial", "salary expectation", "expected salary"),
    "disponibilidade": ("disponibilidade", "quando pode comecar", "availability", "notice period"),
}


def empty_profile() -> dict[str, Any]:
    profile: dict[str, Any] = {name: "" for name in FIELDS}
    profile["historias"] = []
    return profile


class Profile:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        profile = empty_profile()
        if self.path.is_file():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                stored = {}
            if isinstance(stored, dict):
                profile.update(clean(stored))
        return profile

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        profile = empty_profile()
        profile.update(clean(data))
        self.path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        return profile


def clean(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in FIELDS:
        if name in data:
            result[name] = str(data.get(name) or "").strip()
    if "historias" in data:
        stories = []
        for item in data.get("historias") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("titulo") or "").strip()
            text = str(item.get("texto") or "").strip()
            if title or text:
                stories.append({"titulo": title, "texto": text})
        result["historias"] = stories
    return result


def standard_fields(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Só os campos com valor, para a extensão preencher."""
    values = {name: profile.get(name, "") for name in FIELDS}
    parts = values["nome"].split()
    values["primeiro_nome"] = parts[0] if parts else ""
    values["sobrenome"] = " ".join(parts[1:]) if len(parts) > 1 else ""
    return [
        {"chave": key, "valor": values[key], "rotulos": list(labels)}
        for key, labels in LABELS.items()
        if values.get(key)
    ]


def as_prompt(profile: dict[str, Any]) -> str:
    """Fatos do perfil em texto, para a LLM não inventar nada além disso."""
    lines = []
    for name in FIELDS:
        if name == "curriculo":
            continue
        if profile.get(name):
            lines.append(f"{name}: {profile[name]}")
    if profile.get("curriculo"):
        lines.append("Currículo:\n" + profile["curriculo"])
    for story in profile.get("historias") or []:
        lines.append(f"História — {story['titulo']}: {story['texto']}")
    return "\n".join(lines)
