"""IA para perguntas curtas que as regras não sabem responder.

O modelo recebe o perfil, a vaga e as respostas parecidas que a pessoa já deu, para responder
do mesmo jeito (mesmos valores, mesmo nível de detalhe). A resposta só vale se couber no campo:
numa lista, tem de ser uma das opções. Quem preenche é a pessoa, no clique em Usar.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from jobscout import insights, places, replies, suggest
from jobscout.activities import clean_space, fold

MAX_EXAMPLES = 12
PER_QUESTION = 3
MAX_ANSWER = 300
MAX_LONG_ANSWER = 1500
LANGUAGES = {"pt": "português", "en": "inglês", "es": "espanhol"}

SYSTEM = (
    "Você ajuda uma pessoa a preencher formulários de candidatura a vagas. "
    "Use só os fatos do perfil, do currículo e das respostas que ela já deu. Nunca invente experiência, empresa, data ou número. "
    "Siga o jeito como ela respondeu antes: mesmos valores, mesmo nível de detalhe. Responda no idioma da pergunta. "
    "Quando o campo tiver opções, a resposta tem de ser exatamente uma delas. Campo de número: só o número. "
    "Se os fatos não bastarem para responder com segurança, deixe a resposta vazia; não responda 'não' só porque algo não aparece no currículo. "
    "Em base, diga de onde tirou (o trecho do currículo, do perfil ou a resposta anterior). "
    "Nunca responda perguntas sobre gênero, raça, cor, deficiência, idade, religião, orientação sexual ou estado civil. "
    'Responda só com JSON: {"respostas": [{"campo": "...", "resposta": "...", "base": "de onde tirou, em poucas palavras"}]}'
)


def examples(questions: list[str], answers: list[dict[str, Any]], similarity: Callable[[str, str], float]) -> list[dict[str, str]]:
    """Respostas anteriores mais parecidas com as perguntas de agora, mais algumas recentes."""
    chosen: dict[str, dict[str, str]] = {}

    def add(answer: dict[str, Any]) -> None:
        key = fold(answer["question"])
        if key and key not in chosen and answer["answer"].strip() and not suggest.SENSITIVE.search(key):
            chosen[key] = {
                "pergunta": clean_space(answer["question"])[:200],
                "resposta": clean_space(answer["answer"])[:MAX_ANSWER],
                "vaga": f"{answer.get('title') or ''} — {answer.get('company') or ''}".strip(" —"),
            }

    for question in questions:
        scored = sorted(((similarity(question, answer["question"]), answer) for answer in answers), key=lambda pair: -pair[0])
        for score, answer in scored[:PER_QUESTION]:
            if score >= 0.2:
                add(answer)
    for answer in answers[:5]:  # as mais recentes mostram o estilo atual
        if len(chosen) >= MAX_EXAMPLES:
            break
        add(answer)
    return list(chosen.values())[:MAX_EXAMPLES]


def prompt(fields: list[dict[str, Any]], profile_text: str, past: list[dict[str, str]], job: dict[str, Any] | None) -> str:
    lines = ["Perfil e currículo:", profile_text or "(vazio)", ""]
    if past:
        lines.append("Como a pessoa respondeu antes (siga este jeito):")
        lines.extend(f"- {item['pergunta']} → {item['resposta']}" + (f" ({item['vaga']})" if item["vaga"] else "") for item in past)
        lines.append("")
    if job:
        lines.append(f"Vaga: {job.get('title') or ''} — {job.get('company') or ''}")
        if job.get("description"):
            lines.append(str(job["description"])[:2500])
        lines.append("")
    lines.append("Campos para responder:")
    for field in fields:
        options = f" Opções: {json.dumps(field['opcoes'], ensure_ascii=False)}" if field.get("opcoes") else ""
        kind = field.get("tipo") or "text"
        hint = " Só número inteiro; se não constar no currículo, 0." if kind == "number" else ""
        if kind == "checkbox":
            hint = " Pode escolher mais de uma opção, separadas por ponto e vírgula."
        if kind == "textarea":
            hint = " Resposta aberta: 2 a 5 frases em primeira pessoa, com fatos do currículo."
        if not field.get("opcoes") and kind != "number":
            # Modelo local tende a responder em português: o idioma vai em cada campo.
            hint += f" Responda em {LANGUAGES[places.language(field['rotulo'])]}."
        if field.get("max"):
            hint += f" No máximo {field['max']} caracteres."
        lines.append(f'- campo "{field["campo"]}" ({kind}): {field["rotulo"]}{options}{hint}')
    return "\n".join(lines)


# "Não consta no currículo", "nenhuma", "none"...: num campo de número isso é 0.
NONE_WORDS = re.compile(r"(nao consta|nao (?:tenho|possuo|ha)|nenhum\w*|sem experiencia|none|no experience|not (?:listed|mentioned)|zero)")


def _number(text: str) -> str:
    """Número inteiro: os formulários de candidatura costumam recusar decimal."""
    match = re.search(r"\d+(?:[.,]\d+)?", text)
    return str(int(float(match.group(0).replace(",", ".")))) if match else ""


def _invents(answer: str, label: str, facts: str) -> bool:
    """Resposta aberta com número ou ferramenta fora do perfil e do histórico: a IA inventou."""
    known = {fold(name) for name in insights.skills(f"{facts} {label}")}
    return bool(replies.invented_numbers(answer, [facts, label])) or any(fold(name) not in known for name in insights.skills(answer))


def parse(raw: str, fields: list[dict[str, Any]], model: str, facts: str = "") -> list[dict[str, str]]:
    """Só as respostas que cabem no campo; o resto some calado."""
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        match = re.search(r"\{.*\}", raw or "", re.S)
        try:
            data = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            data = {}
    items = data.get("respostas") if isinstance(data, dict) else data
    by_id = {field["campo"]: field for field in fields}
    result = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        field = by_id.pop(str(item.get("campo") or ""), None)
        answer = clean_space(str(item.get("resposta") or ""))
        if not field or not answer or suggest.SENSITIVE.search(fold(field["rotulo"])) or "[falta" in answer.lower():
            continue
        options = field.get("opcoes") or []
        if options and field.get("tipo") == "checkbox":
            # Várias opções podem valer: cada uma tem de existir no campo.
            chosen = [index for index in (suggest.fit_text(part.strip(), options) for part in re.split(r"[;,]", answer)) if index >= 0]
            if not chosen:
                continue
            answer = "; ".join(dict.fromkeys(options[index] for index in chosen))
        elif options:
            index = suggest.fit_text(answer, options)
            if index < 0:
                continue
            answer = options[index]
        base = clean_space(str(item.get("base") or ""))[:120]
        if not options and field.get("tipo") == "number":
            number = _number(answer)
            if not number and NONE_WORDS.search(fold(answer)):
                number, base = "0", f"Não consta no currículo ({answer[:60]})"
            if not number:
                continue
            answer = number
        limit = field.get("max") or 0
        if limit and len(answer) > limit:
            continue
        if facts and not options and field.get("tipo") != "number" and _invents(answer, field["rotulo"], facts):
            continue
        answer = answer[:MAX_LONG_ANSWER if field.get("tipo") == "textarea" else MAX_ANSWER]
        # Sem dizer de onde tirou, é chute (ex.: "No" para uma skill que o currículo só não cita): não sugere.
        if not base:
            continue
        result.append({"campo": field["campo"], "valor": answer, "origem": "ia", "base": f"IA ({model}): {base}"})
    return result
