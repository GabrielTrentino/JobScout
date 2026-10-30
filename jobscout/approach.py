"""Abordagem de recrutador no chat (LinkedIn, WhatsApp): acha a empresa e a vaga para virar oportunidade.

Regras primeiro ("vaga de Engenheira de Dados na Acme", "role at Acme"); a IA local (tarefa privada
"classificar") completa o que as regras não acharem. O resultado vira um rascunho de vaga para aprovar.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jobscout import llm
from jobscout.activities import clean_space, fold

# Sinais de que a pessoa do outro lado fala de uma vaga (não de outro assunto).
CUES = re.compile(
    r"\b(vaga|oportunidade|posi[cç][aã]o|processo seletivo|recrutamento|contrata[cç][aã]o|"
    r"position|role|opportunity|opening|hiring|recruit)", re.I,
)
STOP = r"(?=\s*(?:[,.;:!?\n]|\s(?:e|que|com|para|aqui|onde|em|no|na|and|with|for|that|which|where|in)\s|$))"
TITLE = r"([A-ZÀ-Ý][\w\-/+#.À-ÿ]*(?:\s+(?:de|do|da|of|\w+)?\s*[A-ZÀ-Ý0-9][\w\-/+#.À-ÿ]*){0,5}(?:\s+(?:Jr|Pl|Sr|Pleno|Sênior|Senior|Júnior|Junior|I{1,3}))?)"
COMPANY = r"([A-ZÀ-Ý0-9][\w&.\-À-ÿ]*(?:\s+[A-ZÀ-Ý0-9][\w&.\-À-ÿ]*){0,3})"
PATTERNS = (
    re.compile(rf"(?:vaga|oportunidade|posi[cç][aã]o)\s+(?:de|para)\s+{TITLE}\s+(?:na|no|da|do|em|para a|para o)\s+{COMPANY}{STOP}"),
    re.compile(rf"(?:position|role|opening|opportunity)\s+(?:as|for)\s+(?:an?\s+)?{TITLE}\s+at\s+{COMPANY}{STOP}"),
    re.compile(rf"{TITLE}\s+(?:role|position)\s+at\s+{COMPANY}{STOP}"),
)
COMPANY_ONLY = (
    re.compile(rf"(?:aqui na|aqui no|trabalho na|trabalho no|recrutadora? da|recrutadora? do|time da|time do|parte da)\s+{COMPANY}{STOP}"),
    re.compile(rf"(?:here at|recruiter at|working at|team at)\s+{COMPANY}{STOP}"),
)
TITLE_ONLY = (
    re.compile(rf"(?:vaga|oportunidade|posi[cç][aã]o)\s+(?:de|para)\s+{TITLE}{STOP}"),
    re.compile(rf"(?:position|role|opening)\s+(?:as|for)\s+(?:an?\s+)?{TITLE}{STOP}"),
)
JOB_LINK = re.compile(r"https?://[^\s]*(?:linkedin\.com/(?:comm/)?jobs/view/\d+|gupy\.io/job/[\w=-]+|inhire\.app/vagas/[\w-]+)[^\s]*", re.I)
NOT_COMPANY = {"voce", "você", "vc", "linkedin", "whatsapp", "empresa", "nossa", "nosso", "uma", "um", "the", "our", "a", "o"}
SYSTEM = (
    "Você lê conversas de recrutadores com uma pessoa candidata. Extraia a vaga que o recrutador oferece. "
    "Use só o que está escrito; não invente. Responda só com JSON: "
    '{"vaga": true ou false, "empresa": "", "titulo": "", "local": "", "modelo": "remoto, híbrido, presencial ou vazio"}'
)


def _clean(value: str) -> str:
    value = clean_space(value).strip(" .,;:-")
    return "" if fold(value) in NOT_COMPANY else value[:120]


def by_rules(text: str) -> dict[str, str]:
    found = {"empresa": "", "titulo": ""}
    for pattern in PATTERNS:
        match = pattern.search(text)
        if match:
            found["titulo"], found["empresa"] = _clean(match.group(1)), _clean(match.group(2))
            break
    if not found["empresa"]:
        for pattern in COMPANY_ONLY:
            match = pattern.search(text)
            if match and _clean(match.group(1)):
                found["empresa"] = _clean(match.group(1))
                break
    if not found["titulo"]:
        for pattern in TITLE_ONLY:
            match = pattern.search(text)
            if match and _clean(match.group(1)):
                found["titulo"] = _clean(match.group(1))
                break
    return found


def detect(turns: list[dict[str, Any]], use_ai: bool = True) -> dict[str, Any] | None:
    """A vaga oferecida na conversa: {empresa, titulo, local, modelo, link, origem}, ou None se não há abordagem."""
    theirs = "\n".join(turn["texto"] for turn in turns if not turn.get("minha"))
    if not theirs or not CUES.search(theirs):
        return None
    folded = fold(theirs)
    mode = "remoto" if re.search(r"remot|remote|home ?office", folded) else "hibrido" if re.search(r"hibrid|hybrid", folded) else (
        "presencial" if re.search(r"presencial|on-?site", folded) else "")
    found: dict[str, Any] = {**by_rules(theirs), "local": "", "modelo": mode, "origem": "regras"}
    link = JOB_LINK.search(theirs)
    found["link"] = link.group(0).rstrip(").,") if link else ""
    if (not found["empresa"] or not found["titulo"]) and use_ai and llm.available("classificar"):
        try:
            answer = json.loads(llm.ask_llm("classificar", theirs[-3000:], system=SYSTEM, as_json=True, timeout=90))
        except (llm.LLMUnavailable, json.JSONDecodeError, AttributeError):
            answer = {}
        if isinstance(answer, dict) and answer.get("vaga") is not False:
            for key, field in (("empresa", "empresa"), ("titulo", "titulo"), ("local", "local"), ("modelo", "modelo")):
                value = _clean(str(answer.get(field) or ""))
                # A IA só completa; o que veio das regras (citado literalmente) fica.
                if value and not found[key] and fold(value) in fold(theirs):
                    found[key] = value
                    found["origem"] = "ia"
    if not found["empresa"] and not found["titulo"] and not found["link"]:
        return None
    return found
