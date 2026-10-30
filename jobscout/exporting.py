"""Abas da exportação para Excel. A pessoa escolhe quais abas e quais status de vaga entram."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from jobscout import xlsx
from jobscout.store import STATUS_LABELS

ORIGINS = {"formulario": "Formulário", "rascunho": "Rascunho aprovado"}


def _when(value: str | None) -> str:
    """ISO -> 'AAAA-MM-DD HH:MM', que o Excel ordena e filtra direito."""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def jobs_sheet(assistant: Any, statuses: set[str] | None) -> xlsx.Sheet:
    headers = [
        "ID", "Status", "Título", "Empresa", "Local", "Senioridade", "Modelo de trabalho", "Inglês", "Salário",
        "Região", "Skills", "Fonte", "Link", "Capturada em", "Candidatado em", "Último status em",
    ]
    rows = [
        [
            job["id"], STATUS_LABELS.get(job["status"], job["status"]), job["title"], job["company"], job["location"],
            job.get("seniority") or "", job.get("work_mode") or "", job.get("english") or "", job.get("salary") or "",
            job.get("region") or "", job.get("skills") or "", job["source"], job["url"],
            _when(job["captured_at"]), _when(job["applied_at"]), _when(job["status_at"]),
        ]
        for job in assistant.store.jobs()
        if not statuses or job["status"] in statuses
    ]
    return ("Vagas", headers, rows)


def companies_sheet(assistant: Any, _statuses: set[str] | None) -> xlsx.Sheet:
    headers = ["Empresa", "Setor", "Tamanho", "Sede", "Especializações", "LinkedIn", "Vagas", "Candidaturas", "Última movimentação", "Notas"]
    rows = [
        [
            company["name"], company["industry"], company["size"], company["headquarters"], company["specialties"],
            company["linkedin_url"], company["vagas"], company["candidaturas"], _when(company["ultima"]), company["notes"],
        ]
        for company in assistant.companies()
    ]
    return ("Empresas", headers, rows)


def answers_sheet(assistant: Any, _statuses: set[str] | None) -> xlsx.Sheet:
    headers = ["Pergunta", "Resposta", "Vaga", "Empresa", "Origem", "Quando"]
    rows = [
        [
            answer["question"], answer["answer"], answer["title"], answer["company"],
            ORIGINS.get(answer.get("origin") or "", answer.get("origin") or ""), _when(answer["created_at"]),
        ]
        for answer in assistant.store.answers()
    ]
    return ("Respostas", headers, rows)


def timeline_sheet(assistant: Any, _statuses: set[str] | None) -> xlsx.Sheet:
    headers = ["Quando", "Tipo", "Resumo", "Vaga", "Empresa", "Origem"]
    rows = [
        [_when(move["at"]), move["kind"], move["summary"], move["job_title"] or "", move["job_company"] or "", move["source"]]
        for move in assistant.store.movements(100000)
    ]
    return ("Linha do tempo", headers, rows)


SHEETS: dict[str, tuple[str, Callable[[Any, set[str] | None], xlsx.Sheet]]] = {
    "vagas": ("Vagas e candidaturas", jobs_sheet),
    "empresas": ("Empresas", companies_sheet),
    "respostas": ("Perguntas e respostas dos formulários", answers_sheet),
    "linha": ("Linha do tempo", timeline_sheet),
}


def export(assistant: Any, folder: Path, sheets: list[str], statuses: list[str] | None = None) -> Path:
    """Grava o .xlsx na pasta de exportações e devolve o caminho."""
    chosen = [key for key in SHEETS if key in set(sheets)]
    if not chosen:
        raise ValueError("Escolha pelo menos uma aba para exportar.")
    wanted = {status for status in statuses or [] if status in STATUS_LABELS} or None
    content = xlsx.build([SHEETS[key][1](assistant, wanted) for key in chosen])
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %Hh%M")
    target = folder / f"JobScout {stamp}.xlsx"
    counter = 2
    while target.exists():
        target = folder / f"JobScout {stamp} ({counter}).xlsx"
        counter += 1
    target.write_bytes(content)
    return target
