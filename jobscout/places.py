"""Localização no idioma da pergunta: cidade, estado e país, com o nome do país traduzido."""

from __future__ import annotations

import re
from typing import Any

from jobscout.activities import fold

LANGUAGES = ("pt", "en", "es")

# Países mais comuns em vagas para quem está no Brasil: (português, inglês, espanhol).
COUNTRIES = (
    ("Brasil", "Brazil", "Brasil"),
    ("Portugal", "Portugal", "Portugal"),
    ("Argentina", "Argentina", "Argentina"),
    ("Chile", "Chile", "Chile"),
    ("Colômbia", "Colombia", "Colombia"),
    ("México", "Mexico", "México"),
    ("Peru", "Peru", "Perú"),
    ("Uruguai", "Uruguay", "Uruguay"),
    ("Paraguai", "Paraguay", "Paraguay"),
    ("Bolívia", "Bolivia", "Bolivia"),
    ("Equador", "Ecuador", "Ecuador"),
    ("Venezuela", "Venezuela", "Venezuela"),
    ("Costa Rica", "Costa Rica", "Costa Rica"),
    ("Estados Unidos", "United States", "Estados Unidos"),
    ("Canadá", "Canada", "Canadá"),
    ("Reino Unido", "United Kingdom", "Reino Unido"),
    ("Irlanda", "Ireland", "Irlanda"),
    ("Espanha", "Spain", "España"),
    ("França", "France", "Francia"),
    ("Alemanha", "Germany", "Alemania"),
    ("Itália", "Italy", "Italia"),
    ("Países Baixos", "Netherlands", "Países Bajos"),
    ("Bélgica", "Belgium", "Bélgica"),
    ("Suíça", "Switzerland", "Suiza"),
    ("Suécia", "Sweden", "Suecia"),
    ("Polônia", "Poland", "Polonia"),
    ("Japão", "Japan", "Japón"),
    ("Índia", "India", "India"),
    ("Austrália", "Australia", "Australia"),
)
# Outras grafias -> nome em português da tabela acima.
ALIASES = {
    "eua": "Estados Unidos", "usa": "Estados Unidos", "us": "Estados Unidos", "u.s.": "Estados Unidos",
    "united states of america": "Estados Unidos", "estados unidos da america": "Estados Unidos",
    "uk": "Reino Unido", "inglaterra": "Reino Unido", "england": "Reino Unido", "great britain": "Reino Unido",
    "holanda": "Países Baixos", "holland": "Países Baixos", "the netherlands": "Países Baixos",
}

# Palavras que entregam o idioma de uma pergunta curta de formulário.
WORDS = {
    "en": set("what your where are you is do does current located live based city country state province location please enter of in which the".split()),
    "pt": set("qual sua seu voce onde cidade mora pais estado localizacao atual reside resides esta localizado em que de do da".split()),
    "es": set("cual tu su usted donde ciudad vives vive resides ubicacion provincia actualmente en que de del".split()),
}
# Palavras que só existem num idioma desempatam (de, em, que aparecem em mais de um).
STRONG = {
    "en": set("what your where are you is do does located live based city country state please which the".split()),
    "pt": set("qual voce cidade mora pais localizacao atual reside esta localizado".split()),
    "es": set("cual tu usted donde ciudad vives ubicacion provincia actualmente".split()),
}


# Regiões que as vagas perguntam ("Are you based in Latin America?"): nome em qualquer idioma -> países (português).
_LATAM = {"Brasil", "Argentina", "Chile", "Colômbia", "México", "Peru", "Uruguai", "Paraguai", "Bolívia", "Equador", "Venezuela", "Costa Rica"}
_SOUTH = _LATAM - {"México", "Costa Rica"}
_EUROPE = {"Portugal", "Reino Unido", "Irlanda", "Espanha", "França", "Alemanha", "Itália", "Países Baixos", "Bélgica", "Suíça", "Suécia", "Polônia"}
REGIONS = (
    (re.compile(r"\b(latin america|latam|america latina|latinoamerica|latino america)\b"), _LATAM),
    (re.compile(r"\b(south america|america do sul|america del sur|sudamerica)\b"), _SOUTH),
    (re.compile(r"\b(europe|europa|eu|emea)\b"), _EUROPE),
    (re.compile(r"\b(north america|america do norte|america del norte)\b"), {"Estados Unidos", "Canadá", "México"}),
)


def in_region(question: str, country_name: str) -> bool | None:
    """A pessoa (pelo país do Perfil) está na região ou no país citado? None se a pergunta não cita nenhum."""
    row = country_row(country_name)
    home = COUNTRIES[row][0] if row is not None else ""
    folded = fold(question)
    for pattern, members in REGIONS:
        if pattern.search(folded):
            return home in members if home else None
    for names in COUNTRIES:
        if any(re.search(rf"\b{re.escape(fold(name))}\b", folded) for name in names):
            return names[0] == home if home else None
    return None


def language(text: str, default: str = "pt") -> str:
    words = re.findall(r"[a-z]+", fold(text))
    scores = {lang: sum(2 if word in STRONG[lang] else 1 for word in words if word in WORDS[lang]) for lang in LANGUAGES}
    best = max(scores, key=lambda lang: (scores[lang], lang == default))
    return best if scores[best] else default


def country_row(name: str) -> int | None:
    key = fold(name).strip()
    if not key:
        return None
    key = fold(ALIASES.get(key, key))
    for index, names in enumerate(COUNTRIES):
        if key in {fold(item) for item in names}:
            return index
    return None


def country(name: str, lang: str) -> str:
    """Nome do país no idioma pedido; país fora da lista fica como a pessoa escreveu."""
    row = country_row(name)
    if row is None:
        return name.strip()
    return COUNTRIES[row][LANGUAGES.index(lang) if lang in LANGUAGES else 0]


def country_names(name: str) -> list[str]:
    """Todas as grafias conhecidas do país, para casar com a opção de uma lista."""
    row = country_row(name)
    if row is None:
        return [name.strip()] if name.strip() else []
    return list(dict.fromkeys([*COUNTRIES[row], *(alias for alias, target in ALIASES.items() if target == COUNTRIES[row][0])]))


def location(profile: dict[str, Any], lang: str) -> str:
    """'São Paulo, SP, Brasil' (ou 'Brazil' em inglês). Só o que estiver preenchido."""
    parts = [str(profile.get("cidade") or "").strip(), str(profile.get("estado") or "").strip()]
    if profile.get("pais"):
        parts.append(country(str(profile["pais"]), lang))
    return ", ".join(part for part in parts if part)


def variants(profile: dict[str, Any], build) -> dict[str, str]:
    """O mesmo valor nos três idiomas, só quando muda de um para outro."""
    values = {lang: build(profile, lang) for lang in LANGUAGES}
    return values if len(set(values.values())) > 1 else {}
