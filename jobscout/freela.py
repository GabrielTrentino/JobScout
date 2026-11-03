"""Freela: oportunidades, estimativas, contratos PJ, retornos do cliente e recebimentos.

Também lê a página aberta no navegador (só o que a extensão mandar) e diz o que ela é para a pessoa:
vaga, projeto de freela ou outra coisa, cruzando com o que já está salvo e com as skills do perfil.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from jobscout import insights, llm
from jobscout.activities import clean_space, fold

STATUSES = (
    ("prospeccao", "Prospecção"),
    ("estimativa", "Estimativa enviada"),
    ("negociacao", "Negociação"),
    ("contrato", "Contrato fechado"),
    ("andamento", "Em andamento"),
    ("concluido", "Concluído"),
    ("perdido", "Perdido"),
)
STATUS_KEYS = {key for key, _ in STATUSES}
KINDS = {"projeto": "Projeto fechado", "hora": "Por hora", "mensal": "Mensal (PJ)"}
CURRENCIES = ("BRL", "USD", "EUR")
ESTIMATE_STATES = ("rascunho", "enviada", "aprovada", "recusada")
EVENT_KINDS = ("retorno", "enviado", "nota")
TEXT_FIELDS = {
    "title": 160, "client": 160, "contact": 200, "cnpj": 30, "source_url": 500, "contract_ref": 80, "notes": 4000,
}
DATE_FIELDS = ("start_date", "end_date", "renewal_date")
NUMBER_FIELDS = ("rate_hour", "amount", "hours")
RENEWAL_WARNING_DAYS = 30

PLATFORMS = {
    "workana.com": "Workana", "99freelas.com.br": "99Freelas", "upwork.com": "Upwork", "freelancer.com": "Freelancer",
    "fiverr.com": "Fiverr", "getninjas.com.br": "GetNinjas", "toptal.com": "Toptal", "guru.com": "Guru",
}
FREELA_WORDS = re.compile(r"\b(freela\w*|projeto pontual|or[cç]amento|proposta para o projeto|budget|fixed[- ]price|hourly rate|escopo do projeto)\b", re.I)
JOB_WORDS = re.compile(r"\b(vaga|candidatar|candidatura|job description|apply now|apply for this|requisitos|responsibilities|qualifications)\b", re.I)
MONEY = re.compile(r"(?:R\$|US\$|U\$|USD|BRL|€|\$)\s?\d(?:[\d.,]*\d)?(?:\s?(?:k|mil)\b)?", re.I)

ESTIMATE_SYSTEM = (
    "Você quebra um pedido de freela em etapas de trabalho para uma estimativa de horas. Use só o que está no escopo. "
    "Estime horas realistas por etapa, incluindo testes e ajustes quando fizer sentido. Não invente requisitos nem valores em dinheiro. "
    'Responda só com JSON: {"itens": [{"descricao": "etapa curta", "horas": 8}], "premissas": ["o que você assumiu"]}'
)
PAGE_SYSTEM = (
    "Você ajuda uma pessoa a entender a página que ela está vendo no navegador. Use só o texto da página e o perfil. "
    "Não invente fatos. Responda em português, direto, em até 6 frases."
)


def _date(value: Any) -> str | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"Data inválida: {text}. Use AAAA-MM-DD.") from exc


def _number(value: Any) -> float:
    text = str(value if value is not None else "").strip().replace(" ", "")
    if not text:
        return 0.0
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"Número inválido: {value}.") from exc
    if number < 0:
        raise ValueError("Valores não podem ser negativos.")
    return number


def clean(data: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, limit in TEXT_FIELDS.items():
        if key in data:
            fields[key] = str(data[key] or "").strip()[:limit]
    for key in DATE_FIELDS:
        if key in data:
            fields[key] = _date(data[key])
    for key in NUMBER_FIELDS:
        if key in data:
            fields[key] = _number(data[key])
    if "payment_day" in data:
        day = int(_number(data["payment_day"]))
        if day > 31:
            raise ValueError("Dia de pagamento vai de 1 a 31.")
        fields["payment_day"] = day
    if "status" in data:
        if data["status"] not in STATUS_KEYS:
            raise ValueError("Situação inválida.")
        fields["status"] = data["status"]
    if "kind" in data:
        if data["kind"] not in KINDS:
            raise ValueError("Tipo de contrato inválido.")
        fields["kind"] = data["kind"]
    if "currency" in data:
        if data["currency"] not in CURRENCIES:
            raise ValueError("Moeda inválida.")
        fields["currency"] = data["currency"]
    if not partial and not (fields.get("title") or fields.get("client")):
        raise ValueError("Informe o projeto ou o cliente.")
    return fields


def clean_estimate(data: dict[str, Any]) -> dict[str, Any]:
    """Soma horas e total a partir das linhas: o total nunca é digitado à mão."""
    items = []
    for item in data.get("itens") or []:
        if not isinstance(item, dict):
            continue
        text = clean_space(str(item.get("descricao") or ""))[:200]
        if text:
            items.append({"descricao": text, "horas": _number(item.get("horas"))})
    if not items:
        raise ValueError("Inclua pelo menos uma etapa na estimativa.")
    rate = _number(data.get("valor_hora"))
    hours = round(sum(item["horas"] for item in items), 2)
    currency = data.get("moeda") if data.get("moeda") in CURRENCIES else "BRL"
    state = data.get("estado") if data.get("estado") in ESTIMATE_STATES else "rascunho"
    return {
        "name": clean_space(str(data.get("nome") or "Estimativa"))[:120], "items": items, "rate": rate, "hours": hours,
        "total": round(hours * rate, 2), "currency": currency, "valid_until": _date(data.get("validade")), "state": state,
        "notes": str(data.get("notas") or "").strip()[:2000],
    }


def estimate_text(project: dict[str, Any], estimate: dict[str, Any]) -> str:
    """Texto pronto para mandar ao cliente; quem envia é a pessoa."""
    lines = [f"Estimativa: {project.get('title') or project.get('client') or 'projeto'}", ""]
    lines += [f"- {item['descricao']}: {item['horas']:g}h" for item in estimate["items"]]
    lines += ["", f"Total: {estimate['hours']:g} horas"]
    if estimate["rate"]:
        lines.append(f"Valor: {money(estimate['total'], estimate['currency'])} ({money(estimate['rate'], estimate['currency'])}/hora)")
    if estimate.get("valid_until"):
        lines.append(f"Validade: {date.fromisoformat(estimate['valid_until']):%d/%m/%Y}")
    if estimate.get("notes"):
        lines += ["", estimate["notes"]]
    return "\n".join(lines)


def money(value: float, currency: str) -> str:
    symbol = {"BRL": "R$", "USD": "US$", "EUR": "€"}.get(currency, currency)
    text = f"{value:,.2f}"
    return f"{symbol} " + (text.replace(",", "§").replace(".", ",").replace("§", ".") if currency == "BRL" else text)


def summary(projects: list[dict[str, Any]], payments: list[dict[str, Any]], estimates: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    """Painel do freela: a receber, recebido no mês, atrasado, contratos a renovar e estimativas sem resposta."""
    today = today or date.today()
    month = today.strftime("%Y-%m")
    receivable: dict[str, float] = {}
    received: dict[str, float] = {}
    late = []
    for payment in payments:
        if payment["paid_at"]:
            if payment["paid_at"].startswith(month):
                received[payment["currency"]] = received.get(payment["currency"], 0) + payment["amount"]
            continue
        receivable[payment["currency"]] = receivable.get(payment["currency"], 0) + payment["amount"]
        if payment["due_date"] and payment["due_date"] < today.isoformat():
            late.append(payment)
    limit = (today + timedelta(days=RENEWAL_WARNING_DAYS)).isoformat()
    open_status = {"contrato", "andamento"}
    expiring = [
        {"id": row["id"], "title": row["title"], "client": row["client"], "date": row["renewal_date"] or row["end_date"]}
        for row in projects if row["status"] in open_status and (row["renewal_date"] or row["end_date"])
        and today.isoformat() <= (row["renewal_date"] or row["end_date"]) <= limit
    ]
    waiting = [row for row in estimates if row["state"] == "enviada"]
    return {
        "a_receber": receivable, "recebido_mes": received, "atrasados": len(late), "a_renovar": expiring,
        "estimativas_sem_retorno": len(waiting), "ativos": sum(1 for row in projects if row["status"] in open_status),
    }


def ai_estimate(scope: str) -> dict[str, Any]:
    """Etapas e horas sugeridas pela IA (tarefa "freela"). Levanta llm.LLMUnavailable."""
    raw = llm.ask_llm("freela", f"Escopo do pedido:\n{scope[:6000]}", system=ESTIMATE_SYSTEM, as_json=True, timeout=150)
    try:
        answer = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise llm.LLMUnavailable("A IA não devolveu uma estimativa válida. Tente de novo.") from exc
    items = []
    for item in answer.get("itens") or []:
        if isinstance(item, dict) and clean_space(str(item.get("descricao") or "")):
            try:
                hours = max(0.0, float(str(item.get("horas") or 0).replace(",", ".")))
            except ValueError:
                hours = 0.0
            items.append({"descricao": clean_space(str(item["descricao"]))[:200], "horas": hours})
    if not items:
        raise llm.LLMUnavailable("A IA não devolveu etapas. Tente de novo.")
    return {"itens": items[:30], "premissas": [clean_space(str(item))[:200] for item in answer.get("premissas") or []][:8]}


# Leitura da página aberta

def platform_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return next((name for domain, name in PLATFORMS.items() if host == domain or host.endswith("." + domain)), "")


def page_kind(url: str, title: str = "", text: str = "") -> str:
    """vaga, freela ou outra. Vale a plataforma, depois o título e o endereço, depois o que mais aparece no texto.

    Uma palavra solta no texto não decide: "budget" aparece em vaga de gestão, "requisitos" em qualquer manual.
    """
    if platform_of(url):
        return "freela"
    head = f"{title} {urlparse(url).path.replace('-', ' ').replace('/', ' ')}"
    if FREELA_WORDS.search(head):
        return "freela"
    if JOB_WORDS.search(head):
        return "vaga"
    gig, job = len(FREELA_WORDS.findall(text[:6000])), len(JOB_WORDS.findall(text[:6000]))
    if max(gig, job) < 2:
        return "outra"
    return "freela" if gig > job else "vaga"


def page_facts(url: str, title: str, text: str, my_skills: list[str]) -> dict[str, Any]:
    wanted = insights.skills(f"{title} {text[:12000]}")
    mine = {fold(name) for name in my_skills}
    has = [name for name in wanted if fold(name) in mine]
    return {
        "tipo": page_kind(url, title, text), "plataforma": platform_of(url),
        "habilidades": wanted[:20], "tem": has[:20], "faltam": [name for name in wanted if fold(name) not in mine][:20],
        "encaixe": round(100 * len(has) / len(wanted)) if wanted else None,
        "valores": list(dict.fromkeys(clean_space(match) for match in MONEY.findall(text[:12000])))[:6],
    }


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
