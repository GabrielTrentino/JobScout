"""Aparência importada pela pessoa: tema (JSON com as cores) e personagem no lugar do boneco.

Só entra o que passa pela validação: nomes de cor conhecidos e valores de cor no tema; imagens PNG, GIF,
WebP ou SVG no personagem, mostradas em <img> (assim, script dentro de um SVG não roda).
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

# Cores do painel que um tema pode trocar (as variáveis --nome do app.css).
TOKENS = (
    "bg", "surface", "surface-2", "sunken", "ink", "muted", "line", "line-strong",
    "accent", "accent-soft", "accent-ink", "ok", "ok-soft", "warn", "warn-soft", "danger", "danger-soft",
)
COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%/]+\)|hsla?\([\d\s.,%/deg]+\))$")
POSES = ("idle", "think", "throw")
MAX_IMAGE = 600 * 1024
IMAGE = re.compile(r"^data:image/(png|gif|webp|svg\+xml);base64,([A-Za-z0-9+/=]+)$")

THEME_TEMPLATE: dict[str, Any] = {
    "nome": "Meu tema",
    "claro": {"bg": "#f2f4f7", "surface": "#ffffff", "ink": "#16202a", "muted": "#5a6876", "line": "#dde3ea", "accent": "#2f6fd1", "accent-ink": "#ffffff"},
    "escuro": {"bg": "#0d1117", "surface": "#151b23", "ink": "#e6edf3", "muted": "#93a1af", "line": "#262f3a", "accent": "#5aa2ff", "accent-ink": "#0b1220"},
}


def _colors(raw: Any, where: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"“{where}” deve ser um objeto de cores.")
    colors = {}
    for name, value in raw.items():
        if name not in TOKENS:
            raise ValueError(f"Cor desconhecida em “{where}”: {name}. Use: {', '.join(TOKENS)}.")
        text = str(value).strip()
        if not COLOR.match(text):
            raise ValueError(f"Valor inválido para {name}: {text[:40]}. Use #rrggbb, rgb() ou hsl().")
        colors[name] = text
    return colors


def clean_theme(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("O tema deve ser um objeto JSON com “claro” e/ou “escuro”.")
    theme = {
        "nome": " ".join(str(raw.get("nome") or "Tema importado").split())[:60],
        "claro": _colors(raw.get("claro"), "claro"),
        "escuro": _colors(raw.get("escuro"), "escuro"),
    }
    if not theme["claro"] and not theme["escuro"]:
        raise ValueError("O tema precisa de pelo menos uma cor em “claro” ou “escuro”.")
    return theme


def clean_avatar(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw.get("idle"):
        raise ValueError("Envie pelo menos a imagem “parado”.")
    avatar: dict[str, str] = {}
    for pose in POSES:
        value = raw.get(pose)
        if not value:
            continue
        match = IMAGE.match(str(value))
        if not match:
            raise ValueError("Use imagem PNG, GIF, WebP ou SVG.")
        if len(base64.b64decode(match.group(2))) > MAX_IMAGE:
            raise ValueError(f"Cada imagem pode ter até {MAX_IMAGE // 1024} KB.")
        avatar[pose] = str(value)
    return avatar


class Avatar:
    """Fica num arquivo próprio: as imagens não devem pesar em cada leitura das preferências."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, str] | None:
        if not self.path.is_file():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) and data.get("idle") else None

    def save(self, raw: Any) -> dict[str, str]:
        avatar = clean_avatar(raw)
        self.path.write_text(json.dumps(avatar), encoding="utf-8")
        return avatar

    def reset(self) -> None:
        if self.path.is_file():
            self.path.unlink()
