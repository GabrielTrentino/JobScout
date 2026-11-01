"""Etapas do processo seletivo: o quadro que cada empresa usa, desenhado pela pessoa.

O padrão vai de "Visualizada" a "Proposta", passando por testes, entrevistas e visita presencial.
Cada etapa tem um tipo, que diz em que coluna do quadro geral (status) a vaga fica quando chega nela:
assim o Kanban geral, os indicadores e os lembretes continuam valendo para qualquer quadro.
"""

from __future__ import annotations

import json
from typing import Any

from jobscout.activities import clean_space, fold

# Tipo da etapa → status da vaga no quadro geral.
KINDS = {
    "visualizada": "Visualizada",
    "candidatado": "Candidatura enviada",
    "em_analise": "Em análise / teste",
    "entrevista": "Entrevista / conversa",
    "proposta": "Proposta",
}
STATES = ("pendente", "atual", "feita", "pulada")
MAX_STAGES = 20

DEFAULT_PIPELINE: tuple[dict[str, str], ...] = (
    {"name": "Visualizada", "kind": "visualizada"},
    {"name": "Currículo enviado", "kind": "candidatado"},
    {"name": "Triagem com RH", "kind": "entrevista"},
    {"name": "Teste técnico", "kind": "em_analise"},
    {"name": "Entrevista técnica", "kind": "entrevista"},
    {"name": "Entrevista com gestor", "kind": "entrevista"},
    {"name": "Visita presencial", "kind": "entrevista"},
    {"name": "Proposta", "kind": "proposta"},
)

# Sugestões para o botão "+ Etapa".
SUGGESTIONS = (
    ("Triagem com RH", "entrevista"), ("Teste técnico", "em_analise"), ("Case / desafio para casa", "em_analise"),
    ("Teste de inglês", "em_analise"), ("Teste de perfil / comportamental", "em_analise"), ("Dinâmica de grupo", "entrevista"),
    ("Entrevista técnica", "entrevista"), ("Live coding", "entrevista"), ("System design", "entrevista"),
    ("Entrevista com gestor", "entrevista"), ("Entrevista com diretoria", "entrevista"), ("Fit cultural", "entrevista"),
    ("Visita presencial", "entrevista"), ("Checagem de referências", "em_analise"), ("Proposta", "proposta"),
)


def clean_pipeline(raw: Any) -> list[dict[str, str]]:
    """Lista de {name, kind} válida; nomes repetidos ou vazios saem."""
    result, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = clean_space(str(item.get("name") or item.get("nome") or ""))[:60]
        kind = str(item.get("kind") or item.get("tipo") or "entrevista")
        if not name or fold(name) in seen:
            continue
        seen.add(fold(name))
        result.append({"name": name, "kind": kind if kind in KINDS else "entrevista"})
    return result[:MAX_STAGES]


def company_pipeline(company: dict[str, Any] | None) -> list[dict[str, str]]:
    raw = (company or {}).get("pipeline") or ""
    try:
        custom = clean_pipeline(json.loads(raw)) if raw else []
    except json.JSONDecodeError:
        custom = []
    return custom or [dict(stage) for stage in DEFAULT_PIPELINE]


def initial_stages(pipeline: list[dict[str, str]], status: str) -> list[dict[str, Any]]:
    """Etapas de uma vaga que ainda não tinha quadro: marca até onde o status atual já chegou."""
    stages = [{**stage, "state": "pendente", "scheduled_at": None, "notes": "", "done_at": None} for stage in pipeline]
    order = list(KINDS)
    if status in order:
        same = [index for index, stage in enumerate(stages) if stage["kind"] == status]
        if same:
            # "Entrevista" não diz qual delas: fica na primeira, e a pessoa avança quando quiser.
            # Nos outros tipos, a última etapa do tipo é a atual.
            current = same[0] if status == "entrevista" else same[-1]
        else:
            reached = order.index(status)
            current = max((index for index, stage in enumerate(stages) if order.index(stage["kind"]) <= reached), default=None)
        if current is not None:
            for index in range(current):
                stages[index]["state"] = "feita"
            stages[current]["state"] = "atual"
    return stages


def clean_stages(raw: Any) -> list[dict[str, Any]]:
    """Etapas editadas no painel: nome, tipo, estado, data marcada e notas."""
    result = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = clean_space(str(item.get("name") or item.get("nome") or ""))[:60]
        if not name:
            continue
        kind = str(item.get("kind") or item.get("tipo") or "entrevista")
        state = str(item.get("state") or item.get("estado") or "pendente")
        result.append({
            "name": name,
            "kind": kind if kind in KINDS else "entrevista",
            "state": state if state in STATES else "pendente",
            "scheduled_at": str(item.get("scheduled_at") or item.get("quando") or "")[:30] or None,
            "notes": str(item.get("notes") or item.get("notas") or "")[:1000],
            "done_at": str(item.get("done_at") or "")[:30] or None,
        })
    if sum(1 for stage in result if stage["state"] == "atual") > 1:
        raise ValueError("Só uma etapa pode ser a atual.")
    return result[:MAX_STAGES]


def advance(stages: list[dict[str, Any]], index: int, at: str) -> list[dict[str, Any]]:
    """Leva a vaga para a etapa `index`: as anteriores ficam feitas (as puladas continuam puladas)."""
    if not 0 <= index < len(stages):
        raise ValueError("Etapa inexistente.")
    result = []
    for position, stage in enumerate(stages):
        stage = dict(stage)
        if position < index:
            if stage["state"] != "pulada":
                stage["done_at"] = stage.get("done_at") or at
                stage["state"] = "feita"
        elif position == index:
            stage["state"] = "atual"
            stage["done_at"] = None
        elif stage["state"] in {"atual", "feita"}:
            stage["state"] = "pendente"
            stage["done_at"] = None
        result.append(stage)
    return result


def current(stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((stage for stage in stages if stage["state"] == "atual"), None)
