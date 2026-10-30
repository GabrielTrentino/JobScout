"""Lê e-mails, filtra por regras, classifica e propõe o vínculo com a vaga."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from jobscout import llm
from jobscout.activities import clean_space, fold
from jobscout.gmail import ALERT_SENDERS

KEYWORDS = (
    "processo seletivo", "entrevista", "candidatura", "vaga", "recrutamento", "recrutador",
    "recruiter", "interview", "application", "hiring", "talent", "oportunidade", "feedback",
    "teste tecnico", "case tecnico", "desafio tecnico", "proposta", "offer",
)

# A ordem importa: a primeira classe que bate vence.
CLASSES = (
    ("rejeicao", (
        "infelizmente", "nao seguiremos", "nao vamos seguir", "seguir com outros candidatos",
        "outro candidato", "optamos por", "nao foi selecionad", "decidimos nao", "encerrad",
        "unfortunately", "not moving forward", "other candidates", "not be moving", "decided not to",
    )),
    ("entrevista", (
        "entrevista", "bate-papo", "bate papo", "conversa com", "agendar", "agendamento", "convite",
        "interview", "schedule a call", "meet with", "calendly", "google meet", "zoom", "teams",
    )),
    ("documento", (
        "documento", "documentos", "comprovante", "envie seu", "enviar seu", "preencha", "formulario",
        "teste tecnico", "desafio tecnico", "case tecnico", "document", "please send", "assessment",
    )),
)

NEXT_STATUS = {"entrevista": "entrevista", "rejeicao": "recusada", "documento": "em_analise"}

FREE_MAIL = {"gmail", "outlook", "hotmail", "yahoo", "icloud", "live", "bol", "uol", "terra", "proton", "protonmail"}
PLATFORM_MAIL = {"linkedin", "inhire", "gupy", "greenhouse", "lever", "workable", "kenoby", "solides", "pandape"}

MONTHS = {
    "jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
}

NUMERIC_DATE = re.compile(
    r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b(?:[^\d\n]{0,25}?(\d{1,2})\s*(?:h|:)\s*(\d{2})?)?",
    re.IGNORECASE,
)
WRITTEN_DATE = re.compile(
    r"\b(\d{1,2})\s+de\s+([a-zç]{3,})(?:\s+de\s+(\d{4}))?(?:[^\d\n]{0,25}?(\d{1,2})\s*(?:h|:)\s*(\d{2})?)?",
    re.IGNORECASE,
)
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?")


def parse_eml(data: bytes) -> dict[str, Any]:
    message = message_from_bytes(data, policy=policy.default)
    name, address = parseaddr(str(message.get("From", "")))
    received = None
    if message.get("Date"):
        try:
            received = parsedate_to_datetime(str(message["Date"])).astimezone().isoformat(timespec="seconds")
        except (TypeError, ValueError):
            received = None
    body = ""
    part = message.get_body(preferencelist=("plain", "html"))
    if part is not None:
        content = part.get_content()
        body = _strip_html(content) if part.get_content_subtype() == "html" else content
    html_part = message.get_body(preferencelist=("html",))
    return {
        "remetente_nome": name.strip(),
        "remetente_email": address.strip().lower(),
        "assunto": clean_space(str(message.get("Subject", ""))),
        "recebido_em": received,
        "corpo": body.strip()[:20000],
        "message_id": str(message.get("Message-ID", "")).strip(),
        # Os links das vagas (alertas do LinkedIn) só existem no HTML.
        "html": html_part.get_content()[:300000] if html_part is not None else "",
        # Lista de envio (descadastro): newsletter e marketing, não uma pessoa escrevendo.
        "em_massa": bool(message.get("List-Unsubscribe") or message.get("List-Id")),
    }


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return "\n".join(clean_space(line) for line in text.splitlines() if line.strip())


def sender_org(email: str) -> str:
    domain = email.rpartition("@")[2].lower()
    parts = [part for part in domain.split(".") if part not in {"com", "br", "net", "org", "io", "co", "app", "mail", "email"}]
    return parts[-1] if parts else ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(text))


def link_job(message: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Escolhe a vaga mais provável: domínio do remetente, empresa e título no texto."""
    org = sender_org(message.get("remetente_email", ""))
    text = fold(f"{message.get('assunto', '')} {message.get('corpo', '')[:4000]}")
    best, best_score = None, 0
    for job in jobs:
        score = 0
        company = _slug(job.get("company") or "")
        if company and org and org not in FREE_MAIL | PLATFORM_MAIL and (org in company or company in org):
            score += 3
        if job.get("company") and fold(job["company"]) in text:
            score += 2
        if job.get("title") and fold(job["title"]) in text:
            score += 2
        if score > best_score or (score == best_score and score and (job.get("status_at") or "") > (best.get("status_at") or "")):
            best, best_score = job, score
    return best if best_score >= 2 else None


def looks_relevant(message: dict[str, Any], jobs: list[dict[str, Any]]) -> bool:
    """Pré-filtro por regras, antes de qualquer LLM."""
    org = sender_org(message.get("remetente_email", ""))
    if org and org not in FREE_MAIL and any(org in _slug(job.get("company") or "") for job in jobs if job.get("company")):
        return True
    text = fold(f"{message.get('assunto', '')} {message.get('corpo', '')[:3000]}")
    return any(word in text for word in KEYWORDS)


ATS_MAIL = PLATFORM_MAIL - {"linkedin"}
# Conteúdo de massa que cita "vaga" ou "oportunidade" sem ser um processo seletivo da pessoa.
MARKETING = (
    "webinar", "newsletter", "curso", "bootcamp", "inscreva-se", "inscricoes abertas", "desconto", "promocao",
    "black friday", "evento online", "masterclass", "mentoria gratuita", "unsubscribe", "descadastr",
    "vagas da semana", "vagas recomendadas", "jobs you may", "recommended jobs", "empregos recomendados",
)
STRONG = (
    "processo seletivo", "sua candidatura", "your application", "entrevista", "interview", "teste tecnico",
    "case tecnico", "desafio tecnico", "proposta de trabalho", "offer letter", "seguir com o seu perfil",
    "gostariamos de conversar", "would like to schedule", "next steps", "proximas etapas", "feedback do processo",
)
RELEVANCE_SYSTEM = (
    "Você avalia e-mails para uma pessoa que procura emprego. Diga se o e-mail é sobre um processo de "
    "recrutamento e seleção que envolve ela diretamente: abordagem de recrutador, candidatura, entrevista, "
    "teste, retorno, recusa, proposta ou pedido de documentos. Newsletter, curso, marketing, alerta de vagas "
    "genérico e notificação de rede social não contam. Responda só com JSON: "
    '{"recrutamento": true ou false, "motivo": "frase curta em português"}'
)


def relevance(message: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """É recrutamento e seleção para a pessoa? Regras decidem os casos claros; a IA local, os duvidosos.

    Devolve {recrutamento, motivo, origem}. Sem IA, na dúvida conta como recrutamento (vira rascunho,
    e a pessoa descarta): perder um e-mail de processo seletivo é pior que um rascunho a mais.
    """
    sender = message.get("remetente_email", "")
    if sender in ALERT_SENDERS:
        return {"recrutamento": False, "motivo": "alerta de vagas do LinkedIn (vai para a busca automática)", "origem": "regras", "alerta": True}
    text = fold(f"{message.get('assunto', '')}\n{message.get('corpo', '')[:6000]}")
    org = sender_org(sender)
    if org and org not in FREE_MAIL and any(org in _slug(job.get("company") or "") for job in jobs if job.get("company")):
        return {"recrutamento": True, "motivo": "remetente de uma empresa com vaga salva", "origem": "regras"}
    if not looks_relevant(message, jobs):
        return {"recrutamento": False, "motivo": "não fala de vaga, entrevista nem candidatura", "origem": "regras"}
    strong = [word for word in STRONG if word in text]
    marketing = [word for word in MARKETING if word in text]
    if strong and not marketing and not message.get("em_massa"):
        return {"recrutamento": True, "motivo": f"fala de “{strong[0]}”", "origem": "regras"}
    if org in ATS_MAIL and not marketing:
        return {"recrutamento": True, "motivo": f"plataforma de recrutamento ({org})", "origem": "regras"}
    if llm.available("classificar"):
        prompt = (
            f"De: {message.get('remetente_nome', '')} <{sender}>\n"
            f"Enviado para uma lista: {'sim' if message.get('em_massa') else 'não'}\n"
            f"Assunto: {message.get('assunto', '')}\n\n{message.get('corpo', '')[:3500]}"
        )
        try:
            answer = json.loads(llm.ask_llm("classificar", prompt, system=RELEVANCE_SYSTEM, as_json=True, timeout=90))
            return {
                "recrutamento": bool(answer.get("recrutamento")),
                "motivo": clean_space(str(answer.get("motivo") or ""))[:160] or "avaliado pela IA",
                "origem": "llm",
            }
        except (llm.LLMUnavailable, json.JSONDecodeError, AttributeError):
            pass
    if marketing or message.get("em_massa"):
        return {"recrutamento": False, "motivo": f"parece envio em massa ({marketing[0] if marketing else 'lista de e-mails'})", "origem": "regras"}
    return {"recrutamento": True, "motivo": "cita vaga ou candidatura (sem IA para confirmar)", "origem": "regras"}


def classify(message: dict[str, Any]) -> tuple[str, str]:
    """Devolve (classe, origem). Regras primeiro; a LLM local só desempata 'outro'."""
    text = fold(f"{message.get('assunto', '')}\n{message.get('corpo', '')[:6000]}")
    for name, words in CLASSES:
        if any(word in text for word in words):
            return name, "regras"
    if llm.available("classificar"):
        prompt = (
            "Classifique o e-mail de recrutamento abaixo em exatamente uma palavra: "
            "entrevista, rejeicao, documento ou outro.\n\n"
            f"Assunto: {message.get('assunto', '')}\n\n{message.get('corpo', '')[:4000]}"
        )
        try:
            answer = fold(llm.ask_llm("classificar", prompt, system="Responda só com a palavra pedida."))
        except llm.LLMUnavailable:
            return "outro", "regras"
        for name in ("entrevista", "rejeicao", "documento", "outro"):
            if name in answer:
                return name, "llm"
    return "outro", "regras"


def extract_when(text: str, reference: datetime | None = None) -> str | None:
    """Primeira data (e hora) citada no texto, em ISO local."""
    reference = reference or datetime.now().astimezone()
    candidates: list[tuple[int, datetime]] = []
    for match in ISO_DATE.finditer(text):
        year, month, day, hour, minute = match.groups()
        candidates.append((match.start(), _build(int(year), int(month), int(day), hour, minute, reference)))
    for match in NUMERIC_DATE.finditer(text):
        day, month, year, hour, minute = match.groups()
        candidates.append((match.start(), _build(_year(year, reference), int(month), int(day), hour, minute, reference)))
    for match in WRITTEN_DATE.finditer(fold(text)):
        day, month_name, year, hour, minute = match.groups()
        month = MONTHS.get(month_name[:3])
        if month:
            candidates.append((match.start(), _build(_year(year, reference), month, int(day), hour, minute, reference)))
    found = sorted((pos, value) for pos, value in candidates if value is not None)
    if not found:
        return None
    value = found[0][1]
    return value.isoformat(timespec="minutes")


def _year(raw: str | None, reference: datetime) -> int:
    if not raw:
        return reference.year
    year = int(raw)
    return year + 2000 if year < 100 else year


def _build(year: int, month: int, day: int, hour: str | None, minute: str | None, reference: datetime) -> datetime | None:
    try:
        return datetime(
            year, month, day, int(hour) if hour else 0, int(minute) if minute else 0, tzinfo=reference.tzinfo
        )
    except ValueError:
        return None


def summarize(message: dict[str, Any]) -> str:
    if llm.available("resumir"):
        try:
            return llm.ask_llm(
                "resumir",
                f"Resuma em uma frase o que o recrutador pede ou informa:\n\n{message.get('corpo', '')[:4000]}",
                system="Responda em português, uma frase, sem inventar nada.",
            )[:400]
        except llm.LLMUnavailable:
            pass
    lines = [line.strip() for line in message.get("corpo", "").splitlines() if len(line.strip()) > 25]
    first = next((line for line in lines if not fold(line).startswith(("ola", "oi ", "hello", "hi ", "prezad", "bom dia", "boa tarde"))), "")
    return clean_space(first)[:280]


def build_draft(message: dict[str, Any], jobs: list[dict[str, Any]], *, external_id: str = "", channel: str = "email") -> dict[str, Any]:
    classification, origin = classify(message)
    job = link_job(message, jobs)
    when = extract_when(f"{message.get('assunto', '')}\n{message.get('corpo', '')}") if classification == "entrevista" else None
    target = NEXT_STATUS.get(classification, "")
    if job and target == "em_analise" and job.get("status") not in {"visualizada", "candidatado"}:
        target = ""
    return {
        "canal": channel,
        "external_id": external_id or message.get("message_id") or "",
        "remetente_nome": message.get("remetente_nome", ""),
        "remetente_email": message.get("remetente_email", ""),
        "assunto": message.get("assunto", ""),
        "recebido_em": message.get("recebido_em"),
        "corpo": message.get("corpo", ""),
        "resumo": summarize(message),
        "classificacao": classification,
        "classificado_por": origin,
        "job_id": job["id"] if job else None,
        "vaga": f"{job['title']} — {job['company']}" if job else "",
        "status_proposto": target if job else "",
        "data_evento": when or "",
        # Por que o JobScout achou que é recrutamento (regras ou IA), para conferir no rascunho.
        "relevancia": message.get("relevancia", ""),
    }
