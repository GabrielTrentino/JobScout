"""Perfil do usuário em profile.json e o dicionário de campos padrão."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jobscout import places

FIELDS = (
    "nome",
    "email",
    "telefone",
    "cidade",
    "estado",
    "pais",
    "linkedin",
    "github",
    "portfolio",
    "pretensao_salarial",
    "pretensao_usd",
    "disponibilidade",
    # Respostas rápidas: a extensão sugere a partir delas (suggest.py).
    "nivel_ingles",
    "nivel_espanhol",
    "autorizacao_trabalho",
    "precisa_visto",
    "aceita_mudanca",
    "modelos_trabalho",
    "anos_experiencia",
    "curriculo",
)

# Rótulos que a extensão compara (sem acento, minúsculo) para preencher campos padrão sem LLM.
LABELS = {
    "primeiro_nome": ("primeiro nome", "first name", "given name"),
    "sobrenome": ("sobrenome", "ultimo nome", "last name", "family name", "surname"),
    "nome": ("nome completo", "full name", "seu nome", "nome", "name"),
    "email": ("e-mail", "email", "endereco de email"),
    "telefone": ("telefone", "celular", "phone", "mobile", "whatsapp", "numero de contato"),
    "cidade": ("cidade", "city", "municipio", "current city", "cidade atual", "cidade onde mora", "ciudad"),
    "estado": ("estado", "state", "uf", "province", "provincia", "state/province", "state or province"),
    "pais": ("pais", "country", "pais de residencia", "country of residence", "pais onde mora"),
    # Localização inteira: cidade, estado e país juntos. Perguntas inteiras só batem pelas frases.
    "localizacao": (
        "localizacao", "location", "ubicacion", "onde voce mora",
        "current location", "where are you located", "where are you based", "where do you live",
        "localizacao atual", "onde voce esta localizado", "onde voce reside", "donde vives", "donde resides",
    ),
    "linkedin": ("linkedin",),
    "github": ("github",),
    "portfolio": ("portfolio", "site pessoal", "website", "personal site"),
    "pretensao_salarial": ("pretensao salarial", "expectativa salarial", "salary expectation", "expected salary"),
    "disponibilidade": ("disponibilidade", "quando pode comecar", "availability", "notice period"),
}


MAX_SKILL_YEARS = 60


def empty_profile() -> dict[str, Any]:
    profile: dict[str, Any] = {name: "" for name in FIELDS}
    profile["historias"] = []
    # Tempo real de uso de uma skill quando o currículo não mostra tudo (ex.: SQL antes do primeiro cargo).
    profile["skills_extras"] = []
    # Currículo completo (estrutura do editor); dele sai o texto em "curriculo".
    profile["cv"] = None
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
        """Grava só o que veio; o resto fica como estava (Perfil e Currículo editam partes diferentes)."""
        profile = self.load()
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
    if "cv" in data:
        from jobscout import cv

        result["cv"] = cv.clean(data["cv"]) if data.get("cv") else None
    if "skills_extras" in data:
        extras: dict[str, dict[str, Any]] = {}
        for item in data.get("skills_extras") or []:
            if not isinstance(item, dict):
                continue
            skill = " ".join(str(item.get("skill") or "").split())[:60]
            try:
                years = float(str(item.get("anos") or "").replace(",", "."))
            except ValueError:
                years = 0.0
            if skill and 0 < years <= MAX_SKILL_YEARS:
                extras[skill.lower()] = {"skill": skill, "anos": round(years, 1), "nota": " ".join(str(item.get("nota") or "").split())[:200]}
        result["skills_extras"] = list(extras.values())
    return result


def standard_fields(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Só os campos com valor, para a extensão preencher.

    País e localização vêm também por idioma ("valores"); a extensão escolhe pelo idioma do rótulo.
    """
    values = {name: profile.get(name, "") for name in FIELDS}
    parts = values["nome"].split()
    values["primeiro_nome"] = parts[0] if parts else ""
    values["sobrenome"] = " ".join(parts[1:]) if len(parts) > 1 else ""
    values["pais"] = places.country(values["pais"], "pt") if values["pais"] else ""
    values["localizacao"] = places.location(profile, "pt")
    by_language = {
        "pais": places.variants(profile, lambda data, lang: places.country(str(data.get("pais") or ""), lang)),
        "localizacao": places.variants(profile, places.location),
    }
    # Pretensão: "brl" e "usd" para rótulo que diz a moeda; sem moeda no rótulo, vale o idioma.
    brl, usd = str(profile.get("pretensao_salarial") or ""), str(profile.get("pretensao_usd") or "")
    if brl or usd:
        values["pretensao_salarial"] = brl or usd
        by_language["pretensao_salarial"] = {
            "pt": brl or usd, "es": brl or usd, "en": usd or brl,
            **({"brl": brl} if brl else {}), **({"usd": usd} if usd else {}),
        }
    fields = []
    for key, labels in LABELS.items():
        if not values.get(key):
            continue
        field: dict[str, Any] = {"chave": key, "valor": values[key], "rotulos": list(labels)}
        if by_language.get(key):
            field["valores"] = by_language[key]
        fields.append(field)
    return fields


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
    for extra in profile.get("skills_extras") or []:
        note = f" ({extra['nota']})" if extra.get("nota") else ""
        lines.append(f"Tempo de uso informado pela pessoa — {extra['skill']}: {extra['anos']:g} anos{note}")
    return "\n".join(lines)
