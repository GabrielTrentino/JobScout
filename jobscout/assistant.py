"""Tudo que é capturado vira rascunho; só a aprovação do usuário grava no banco."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from jobscout import ai_suggest, approach, cv, insights, linkedin_public, llm, pipeline, places, replies, suggest
from jobscout.activities import clean_space, fold, list_tools
from jobscout.events import Hub
from jobscout.profile import Profile, as_prompt
from jobscout.store import ALL_JOB_FIELDS, EXTRA_FIELDS, JOB_FIELDS, STATUS_KEYS, STATUS_LABELS, Store, now

SITE_NAMES = {"linkedin": "LinkedIn", "inhire": "InHire", "email": "E-mail", "manual": "Manual", "painel": "Painel",
              "whatsapp": "WhatsApp", "gupy": "Gupy", "busca": "Busca automática", "web": "Outro site"}
WORK_MODE_NAMES = {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial"}

KINDS = {
    "vaga": "Nova vaga",
    "vaga_alteracao": "Vaga alterada",
    "status": "Mudança de status",
    "resposta": "Resposta de formulário",
    "mensagem": "Mensagem de recrutador",
}

SOURCES = {"linkedin", "inhire", "email", "manual", "painel", "whatsapp", "busca", "web"}

# Status em que a vaga ainda espera retorno; parada por muito tempo vira candidata a "fria".
OPEN_STATUSES = ("candidatado", "em_analise", "entrevista", "proposta")
# Indicadores: qualquer resposta da empresa (até recusa) é retorno.
APPLIED_STAGES = ("candidatado", "em_analise", "entrevista", "proposta", "recusada", "fria")
RETURN_STAGES = {"em_analise", "entrevista", "proposta", "recusada"}
MAX_ANSWERS = 80
MAX_SUGGESTIONS = 60
MAX_AI_FIELDS = 12
LANGUAGE_NAMES = {"pt": "português", "en": "inglês", "es": "espanhol"}

MAX_DESCRIPTION = 20000

TRACKING = re.compile(r"^(utm_|ref|tracking|trk|eBP|refId|trackingId|lipi|src$|origin$)", re.IGNORECASE)

STOPWORDS = set(
    "a o os as de da do das dos e em no na nos nas um uma para por com que qual quais sobre "
    "eu me meu minha voce seu sua the of to in on for and or is are your you what which how "
    "empresa vaga respondi responder falei disse".split()
)


class DraftError(ValueError):
    """O rascunho não pode ser aprovado como está."""


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DraftError("Link inválido.")
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    query = ""
    if "linkedin.com" in host:
        match = re.search(r"/jobs/view/(?:[^/]*?-)?(\d+)", path)
        job_id = match.group(1) if match else dict(parse_qsl(parsed.query)).get("currentJobId")
        if job_id:
            return f"https://www.linkedin.com/jobs/view/{job_id}/"
    else:
        kept = [(key, value) for key, value in parse_qsl(parsed.query) if not TRACKING.match(key)]
        query = urlencode(kept)
    return urlunparse((parsed.scheme, host, path, "", query, ""))


def describe(draft: dict[str, Any]) -> str:
    payload = draft["payload"]
    kind = draft["kind"]
    if kind == "vaga":
        text = _job_label(payload)
        if payload.get("status") == "candidatado":
            text += " (candidatado)"
        return text
    if kind == "vaga_alteracao":
        fields = ", ".join(payload.get("mudancas", {}))
        return f"{payload.get('vaga', 'Vaga')}: {fields}"
    if kind == "status":
        return f"{payload.get('vaga', 'Vaga')}: {STATUS_LABELS.get(payload.get('de'), '—')} → {STATUS_LABELS.get(payload.get('para'), payload.get('para'))}"
    if kind == "resposta":
        return payload.get("pergunta", "Pergunta")
    if kind == "mensagem":
        return payload.get("assunto") or payload.get("remetente_email") or "Mensagem"
    return kind


def _job_label(fields: dict[str, Any]) -> str:
    title = fields.get("title") or "Vaga sem título"
    company = fields.get("company")
    return f"{title} — {company}" if company else title


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", fold(text)) if word not in STOPWORDS and len(word) > 1}


def similarity(left: str, right: str) -> float:
    a, b = _words(left), _words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class Assistant:
    def __init__(
        self,
        store: Store,
        hub: Hub,
        profile: Profile,
        *,
        background: bool = True,
        public_job: Any = linkedin_public.fetch,
        public_company: Any = linkedin_public.fetch_company,
    ) -> None:
        self.store = store
        self.hub = hub
        self.profile = profile
        self.background = background
        self.public_job = public_job
        self.public_company = public_company
        self._public_cache: dict[str, dict[str, str]] = {}
        # Modelos de mensagem editados pela pessoa (o App liga às preferências).
        self._message_overrides_loader = None
        self._public_lock = threading.Lock()

    # Entrada: eventos da extensão

    def intake(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        kind = event.get("tipo")
        site = str(event.get("site") or "manual").lower()
        source = site if site in SOURCES else "manual"
        site_name = SITE_NAMES.get(source, source)
        if kind == "selector_failed":
            self.store.add_failure(site, str(event.get("pagina") or ""), str(event.get("detalhe") or "")[:2000])
            self.hub.publish("falha", site=site)
            self.hub.activity(f"{site_name}: não consegui ler a vaga ({event.get('detalhe') or 'seletor'}).", "erro")
            return []
        try:
            job = self._job_fields(event.get("vaga") or {}, source)
        except DraftError as exc:
            self.hub.activity(f"{site_name}: evento recusado. {exc}", "erro")
            raise
        if source == "linkedin":
            job = self._complete_from_public(job)
        job = insights.enrich(job)
        if source == "linkedin":
            key = "vaga:" + job["url"]
            known = self.store.job_by_url(job["url"]) or self.store.pending_draft(key) or self.store.was_discarded(key)
            if not job["title"] and not job["company"] and not known:
                self.store.add_failure(site, str(event.get("pagina") or ""), "título e empresa não encontrados nem na página pública")
                self.hub.publish("falha", site=site)
                return []
        label = _job_label(job)
        if kind == "job_viewed":
            self.hub.activity(f"{site_name}: lendo a vaga {label}…", "trabalhando")
            changed = [self._job_viewed(job, source)]
        elif kind == "application_submitted":
            self.hub.activity(f"{site_name}: clique em Enviar detectado em {label}.", "trabalhando", acao="envio")
            changed = [self._application_submitted(
                job, source, event.get("quando"), _form_answers(event.get("respostas")), _documents(event.get("documentos")),
            )]
        elif kind == "form_detected":
            count = len(event.get("perguntas") or [])
            self.hub.activity(f"{site_name}: formulário com {count} pergunta(s) aberta(s) em {label}.", "trabalhando")
            changed = self._form_detected(job, source, event)
        else:
            raise DraftError(f"Evento desconhecido: {kind}")
        drafts = [draft for draft in changed if draft]
        if drafts:
            self.hub.publish("rascunhos", ids=[draft["id"] for draft in drafts])
            for draft in drafts:
                verb = "Novo rascunho" if draft.get("novo") else "Rascunho atualizado"
                self.hub.activity(f"{verb} — {KINDS[draft['kind']]}: {describe(draft)}. Aguardando sua aprovação.", "aviso", rascunho=draft["id"])
        else:
            self.hub.activity(f"Nada a aprovar: {self._why_skipped(kind, job)}", "info")
        return drafts

    def _complete_from_public(self, job: dict[str, str]) -> dict[str, str]:
        """Vaga nova do LinkedIn: completa com a página pública (nível, setor, empresa; e título se faltar).

        Uma busca por vaga. O que veio da página logada tem prioridade.
        """
        key = "vaga:" + job["url"]
        if self.store.job_by_url(job["url"]) or self.store.pending_draft(key) or self.store.was_discarded(key):
            return job
        missing = not job["title"] or not job["company"]
        with self._public_lock:
            cached = self._public_cache.get(job["url"])
        if cached is None:
            if missing:
                self.hub.activity("LinkedIn: layout não reconhecido; buscando os dados públicos da vaga…", "trabalhando")
            else:
                self.hub.activity(f"LinkedIn: buscando nível, setor e empresa de {_job_label(job)}…", "trabalhando")
            try:
                cached = self.public_job(job["url"])
            except linkedin_public.PublicPageError as exc:
                level = "erro" if missing else "info"
                self.hub.activity(f"LinkedIn: não consegui os dados públicos da vaga ({exc}).", level)
                cached = {}
            with self._public_lock:
                self._public_cache[job["url"]] = cached
        filled = dict(job)
        limits = {"title": 300, "company": 200, "location": 200, "description": MAX_DESCRIPTION}
        for name in ("title", "company", "location", "description", *EXTRA_FIELDS):
            if not filled.get(name) and cached.get(name):
                filled[name] = cached[name][: limits.get(name, 300)]
        return filled

    def _why_skipped(self, kind: str, job: dict[str, str]) -> str:
        existing = self.store.job_by_url(job["url"])
        label = _job_label(existing or job)
        if kind == "application_submitted" and existing:
            return f"{label} já está como {STATUS_LABELS.get(existing['status'], existing['status'])}."
        if kind == "form_detected":
            return f"as perguntas de {label} já estão nos rascunhos."
        if existing:
            return f"{label} já está salva e nada mudou."
        if self.store.pending_draft("vaga:" + job["url"]):
            return f"{label} já está nos rascunhos."
        if self.store.was_discarded("vaga:" + job["url"]):
            return f"você descartou {label} antes; não vou propor de novo."
        return f"{label} sem novidades."

    def _job_fields(self, raw: dict[str, Any], source: str) -> dict[str, str]:
        url = str(raw.get("url") or "")
        if not url:
            raise DraftError("A vaga chegou sem link.")
        fields = {
            "source": source,
            "url": normalize_url(url),
            "title": clean_space(str(raw.get("title") or ""))[:300],
            "company": clean_space(str(raw.get("company") or ""))[:200],
            "location": clean_space(str(raw.get("location") or ""))[:200],
            "description": str(raw.get("description") or "").strip()[:MAX_DESCRIPTION],
        }
        for name in EXTRA_FIELDS:
            fields[name] = clean_space(str(raw.get(name) or ""))[:300]
        return fields

    def _job_viewed(self, job: dict[str, str], source: str) -> dict[str, Any] | None:
        existing = self.store.job_by_url(job["url"])
        if existing:
            return self._propose_changes(existing, job, source)
        key = "vaga:" + job["url"]
        pending = self.store.pending_draft(key)
        if pending:
            return self._refresh_job_draft(pending, job)
        if self.store.was_discarded(key):
            return None
        if not job["title"] and not job["company"]:
            raise DraftError("A vaga chegou sem título e sem empresa.")
        payload = {**job, "status": "visualizada", "candidatado_em": None}
        return self._new_draft("vaga", key, source, payload, job_url=job["url"])

    def _application_submitted(
        self, job: dict[str, str], source: str, when: Any, answers: list[dict[str, str]] | None = None,
        documents: list[str] | None = None,
    ) -> dict[str, Any] | None:
        applied_at = str(when) if when else now()
        extra: dict[str, Any] = {"respostas": answers, "guardar_respostas": True} if answers else {}
        if documents:
            extra["documentos"] = documents
        existing = self.store.job_by_url(job["url"])
        if existing:
            if STATUS_KEYS.index(existing["status"]) >= STATUS_KEYS.index("candidatado"):
                return None
            key = f"status:{existing['id']}"
            payload = {
                "vaga": _job_label(existing),
                "de": existing["status"],
                "para": "candidatado",
                "quando": applied_at,
                **extra,
            }
            pending = self.store.pending_draft(key)
            if pending:
                self.store.update_draft(pending["id"], {**pending["payload"], **payload})
                return self.store.draft(pending["id"])
            return self._new_draft("status", key, source, payload, job_id=existing["id"], job_url=job["url"])
        key = "vaga:" + job["url"]
        pending = self.store.pending_draft(key)
        if pending:
            payload = {**pending["payload"], "status": "candidatado", "candidatado_em": applied_at, **extra}
            self.store.update_draft(pending["id"], payload)
            self._refresh_job_draft(self.store.draft(pending["id"]), job)
            return self.store.draft(pending["id"])
        payload = {**job, "status": "candidatado", "candidatado_em": applied_at, **extra}
        return self._new_draft("vaga", key, source, payload, job_url=job["url"])

    def _refresh_job_draft(self, draft: dict[str, Any], job: dict[str, str]) -> dict[str, Any] | None:
        """Completa campos vazios do rascunho sem passar por cima do que o usuário editou."""
        payload = dict(draft["payload"])
        changed = False
        for name in ALL_JOB_FIELDS:
            value = job.get(name)
            if not value or payload.get(name) == value:
                continue
            if draft["edited"] and payload.get(name):
                continue
            payload[name] = value
            changed = True
        if not changed:
            return None
        self.store.update_draft(draft["id"], payload)
        return self.store.draft(draft["id"])

    def _propose_changes(self, existing: dict[str, Any], job: dict[str, str], source: str) -> dict[str, Any] | None:
        changes = {}
        for name in ("title", "company", "location", "description"):
            new = job.get(name) or ""
            old = existing.get(name) or ""
            if new and clean_space(new) != clean_space(old):
                changes[name] = {"de": old, "para": new}
        if not changes:
            return None
        key = f"alteracao:{existing['id']}"
        pending = self.store.pending_draft(key)
        if pending:
            merged = dict(pending["payload"].get("mudancas", {}))
            for name, change in changes.items():
                if pending["edited"] and name in merged:
                    continue
                merged[name] = change
            if merged == pending["payload"].get("mudancas"):
                return None
            self.store.update_draft(pending["id"], {**pending["payload"], "mudancas": merged})
            return self.store.draft(pending["id"])
        payload = {"vaga": _job_label(existing), "mudancas": changes}
        return self._new_draft("vaga_alteracao", key, source, payload, job_id=existing["id"], job_url=job["url"])

    def _form_detected(self, job: dict[str, str], source: str, event: dict[str, Any]) -> list[dict[str, Any] | None]:
        page = str(event.get("pagina") or job["url"])
        existing = self.store.job_by_url(job["url"])
        if not existing and not self.store.pending_draft("vaga:" + job["url"]):
            if job["title"] or job["company"]:
                self._job_viewed(job, source)
        created = []
        for question in event.get("perguntas") or []:
            label = clean_space(str(question.get("rotulo") or ""))[:1000]
            field = str(question.get("campo") or "")
            if not label or not field:
                continue
            key = f"resposta:{job['url']}:{fold(label)}"
            pending = self.store.pending_draft(key)
            if pending:
                if pending["payload"].get("campo") != field or pending["payload"].get("pagina") != page:
                    self.store.update_draft(pending["id"], {**pending["payload"], "campo": field, "pagina": page})
                continue
            suggestion = self._from_history(label)
            payload = {
                "vaga": _job_label(existing or job),
                "pergunta": label,
                "resposta": suggestion["resposta"] if suggestion else "",
                "sugerida_por": "historico" if suggestion else "",
                "base": suggestion["base"] if suggestion else "",
                "campo": field,
                "pagina": page,
                "inserir": True,
            }
            draft = self._new_draft(
                "resposta", key, source, payload,
                job_id=existing["id"] if existing else None, job_url=job["url"],
            )
            created.append(draft)
            if not suggestion and llm.available("responder"):
                self._run(self._suggest_answer, draft["id"], job, label)
        return created

    def _from_history(self, question: str) -> dict[str, str] | None:
        best, score = None, 0.0
        for answer in self._reusable_answers():
            value = similarity(question, answer["question"])
            if value > score:
                best, score = answer, value
        if best is None or score < 0.6:
            return None
        return {"resposta": best["answer"], "base": f"Já usada em {best['title']} — {best['company']}"}

    def _suggest_answer(self, draft_id: int, job: dict[str, str], question: str) -> None:
        past = ai_suggest.examples([question], self._reusable_answers(), similarity)
        history = "".join(f"- {item['pergunta']} → {item['resposta']}\n" for item in past)
        prompt = (
            f"Perfil:\n{as_prompt(self.profile.load())}\n\n"
            + (f"Como a pessoa respondeu perguntas parecidas antes (siga o mesmo jeito e os mesmos fatos):\n{history}\n" if history else "")
            + f"Vaga: {_job_label(job)}\n{job.get('description', '')[:4000]}\n\n"
            f"Pergunta do formulário: {question}\n\n"
            f"Escreva a resposta em {LANGUAGE_NAMES[places.language(question)]}, o idioma da pergunta."
        )
        self.hub.activity(f"IA escrevendo sugestão para “{question[:80]}”…", "trabalhando")
        try:
            text = llm.ask_llm("responder", prompt)
        except llm.LLMUnavailable as exc:
            self.hub.activity(f"IA indisponível; a pergunta fica para você responder. {exc}", "aviso")
            return
        draft = self.store.draft(draft_id)
        if not draft or draft["state"] != "pendente" or draft["edited"] or not text:
            return
        self.store.update_draft(draft_id, {**draft["payload"], "resposta": text, "sugerida_por": "llm", "base": ""})
        self.hub.publish("rascunhos", ids=[draft_id])
        self.hub.activity("Sugestão da IA pronta. Confira os fatos antes de aprovar.", "aviso", rascunho=draft_id)

    # Entrada: mensagens (e-mail)

    def intake_message(self, payload: dict[str, Any], source: str = "email") -> dict[str, Any] | None:
        external = payload.get("external_id") or ""
        key = "mensagem:" + (external or f"{payload.get('remetente_email')}:{payload.get('assunto')}:{payload.get('recebido_em')}")
        subject = payload.get("assunto") or payload.get("remetente_email") or "e-mail"
        if (external and self.store.message_exists(external)) or self.store.pending_draft(key) or self.store.was_discarded(key):
            self.hub.activity(f"E-mail “{subject}” já foi tratado antes.", "info")
            return None
        draft = self._new_draft("mensagem", key, source, payload, job_id=payload.get("job_id"))
        self.hub.publish("rascunhos", ids=[draft["id"]])
        where = f" → {payload['vaga']}" if payload.get("vaga") else " (sem vaga vinculada)"
        self.hub.activity(f"E-mail de recrutador: “{subject}”{where}. Aguardando sua aprovação.", "aviso", rascunho=draft["id"])
        return draft

    def _new_draft(
        self,
        kind: str,
        key: str,
        source: str,
        payload: dict[str, Any],
        *,
        job_id: int | None = None,
        job_url: str = "",
    ) -> dict[str, Any]:
        with self.store.tx():
            draft_id = self.store.add_draft(kind, key, source, payload, job_id=job_id, job_url=job_url)
            draft = self.store.draft(draft_id)
            self.store.log(
                "rascunho_criado",
                f"Rascunho — {KINDS[kind]}: {describe(draft)}",
                source,
                job_id=job_id,
                draft_id=draft_id,
            )
        return {**draft, "novo": True}

    # Decisões do usuário

    def edit(self, draft_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        draft = self._pending(draft_id)
        merged = self._merge_edit(draft, payload)
        self.store.update_draft(draft_id, merged, edited=True)
        self.hub.publish("rascunhos", ids=[draft_id])
        return self.store.draft(draft_id)

    def approve(self, draft_id: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        draft = self._pending(draft_id)
        if payload:
            # A edição fica salva mesmo se a aprovação for recusada logo abaixo.
            draft["payload"] = self._merge_edit(draft, payload)
            draft["edited"] = True
            self.store.update_draft(draft_id, draft["payload"], edited=True)
        apply = getattr(self, "_apply_" + draft["kind"])
        with self.store.tx():
            job_id = apply(draft)
            self.store.set_draft_state(draft_id, "aprovado", job_id)
            self.store.log(
                "rascunho_aprovado",
                f"Aprovado — {KINDS[draft['kind']]}: {describe(draft)}",
                "painel",
                job_id=job_id,
                draft_id=draft_id,
                detail={"editado": draft["edited"]},
            )
        self.hub.publish("aprovado", id=draft_id, vaga=job_id)
        self.hub.activity(f"Aprovado e salvo — {KINDS[draft['kind']]}: {describe(draft)}", "ok", vaga=job_id)
        return self.store.draft(draft_id)

    def discard(self, draft_id: int) -> dict[str, Any]:
        draft = self._pending(draft_id)
        with self.store.tx():
            self.store.set_draft_state(draft_id, "descartado")
            self.store.log(
                "rascunho_descartado",
                f"Descartado — {KINDS[draft['kind']]}: {describe(draft)}",
                "painel",
                job_id=draft["job_id"],
                draft_id=draft_id,
            )
        self.hub.publish("descartado", id=draft_id)
        self.hub.activity(f"Descartado — {KINDS[draft['kind']]}: {describe(draft)}", "info")
        return self.store.draft(draft_id)

    def _pending(self, draft_id: int) -> dict[str, Any]:
        draft = self.store.draft(draft_id)
        if draft is None:
            raise LookupError(f"Rascunho {draft_id} não encontrado.")
        if draft["state"] != "pendente":
            raise DraftError(f"O rascunho {draft_id} já foi {draft['state']}.")
        return draft

    def _merge_edit(self, draft: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        payload = dict(draft["payload"])
        kind = draft["kind"]
        if kind == "vaga":
            for name in ("title", "company", "location", "description"):
                if name in incoming:
                    payload[name] = str(incoming[name] or "").strip()
            if "status" in incoming:
                payload["status"] = _status(incoming["status"])
            for name in EXTRA_FIELDS:
                if name in incoming:
                    payload[name] = clean_space(str(incoming[name] or ""))
        elif kind == "vaga_alteracao":
            changes = dict(payload.get("mudancas", {}))
            for name, value in (incoming.get("mudancas") or {}).items():
                if name not in changes:
                    continue
                if value is None:
                    changes.pop(name)
                else:
                    changes[name] = {**changes[name], "para": str(value.get("para", value) if isinstance(value, dict) else value)}
            payload["mudancas"] = changes
        elif kind == "status":
            if "para" in incoming:
                payload["para"] = _status(incoming["para"])
        if "guardar_respostas" in incoming and payload.get("respostas"):
            payload["guardar_respostas"] = bool(incoming["guardar_respostas"])
        elif kind == "resposta":
            if "resposta" in incoming:
                payload["resposta"] = str(incoming["resposta"] or "")
            if "inserir" in incoming:
                payload["inserir"] = bool(incoming["inserir"])
        elif kind == "mensagem":
            if "job_id" in incoming:
                payload["job_id"] = int(incoming["job_id"]) if incoming["job_id"] not in (None, "") else None
            if "status_proposto" in incoming:
                value = incoming["status_proposto"]
                payload["status_proposto"] = _status(value) if value else ""
            for name in ("classificacao", "resumo", "data_evento"):
                if name in incoming:
                    payload[name] = str(incoming[name] or "")
        return payload

    def _apply_vaga(self, draft: dict[str, Any]) -> int:
        payload = draft["payload"]
        fields = {name: payload.get(name, "") for name in ALL_JOB_FIELDS}
        if not fields["title"] and not fields["company"]:
            raise DraftError("Informe pelo menos o título ou a empresa.")
        status = _status(payload.get("status") or "visualizada")
        applied_at = payload.get("candidatado_em") if status != "visualizada" else None
        existing = self.store.job_by_url(fields["url"])
        if existing:
            self.store.update_job(existing["id"], fields)
            job_id = existing["id"]
            self.store.set_status(job_id, status, applied_at)
        else:
            job_id = self.store.insert_job(fields, status, applied_at or (now() if status != "visualizada" else None))
        self.store.attach_drafts_to_job(fields["url"], job_id)
        self.store.log("vaga_criada", f"Vaga salva: {_job_label(fields)}", draft["source"], job_id=job_id, draft_id=draft["id"])
        self._save_form_answers(job_id, payload, draft["source"], draft["id"])
        self._save_sent(job_id, payload)
        self.ensure_company(job_id)
        recruiter = payload.get("recrutador") if isinstance(payload.get("recrutador"), dict) else None
        if recruiter and recruiter.get("nome"):
            # Vaga oferecida no chat: quem abordou fica vinculado a ela.
            contact = self.find_contact(recruiter.get("nome", ""), recruiter.get("email", ""), recruiter.get("linkedin", ""), recruiter.get("telefone", ""))
            if contact is None:
                contact_id = self.store.create_contact(self._contact_fields({**recruiter, "empresa": fields["company"]}))
            else:
                contact_id = contact["id"]
            self.store.link_contact(job_id, contact_id)
            self.store.log("recrutador", f"Abordagem de {recruiter['nome']} vinculada", draft["source"], job_id=job_id, draft_id=draft["id"])
        if status != "visualizada":
            self.store.log(
                "status", f"Status: {STATUS_LABELS[status]}", draft["source"],
                job_id=job_id, draft_id=draft["id"], detail={"de": None, "para": status},
            )
        return job_id

    def _apply_vaga_alteracao(self, draft: dict[str, Any]) -> int:
        job_id = draft["job_id"]
        changes = draft["payload"].get("mudancas") or {}
        if not changes:
            raise DraftError("Nenhuma mudança sobrou neste rascunho.")
        self.store.update_job(job_id, {name: change["para"] for name, change in changes.items()})
        self.store.log(
            "vaga_alterada", "Vaga atualizada: " + ", ".join(changes), draft["source"],
            job_id=job_id, draft_id=draft["id"], detail={"mudancas": changes},
        )
        return job_id

    def _apply_status(self, draft: dict[str, Any]) -> int:
        payload = draft["payload"]
        job_id = draft["job_id"]
        job = self.store.job(job_id)
        status = _status(payload["para"])
        self.store.set_status(job_id, status, payload.get("quando") if status == "candidatado" else None)
        self.store.log(
            "status", f"Status: {STATUS_LABELS.get(job['status'], '—')} → {STATUS_LABELS[status]}", draft["source"],
            job_id=job_id, draft_id=draft["id"], detail={"de": job["status"], "para": status},
        )
        self._save_form_answers(job_id, payload, draft["source"], draft["id"])
        self._save_sent(job_id, payload)
        return job_id

    def _save_sent(self, job_id: int, payload: dict[str, Any]) -> None:
        """Currículo enviado e salário informado ficam na candidatura, para filtrar e comparar depois."""
        documents = ", ".join(_documents(payload.get("documentos")))
        salary = next(
            (item["valor"] for item in payload.get("respostas") or [] if suggest.SALARY.search(fold(item["rotulo"]))), ""
        )
        if documents or salary:
            self.store.set_sent(job_id, documents, salary[:200])

    def _save_form_answers(self, job_id: int, payload: dict[str, Any], source: str, draft_id: int) -> None:
        """Registra o que foi preenchido no formulário no momento do envio.

        Sempre fica no histórico da vaga; "guardar_respostas" desmarcado só impede o reuso no preenchimento.
        """
        answers = payload.get("respostas") or []
        if not answers:
            return
        origin = "registro" if payload.get("guardar_respostas") is False else "formulario"
        known = {(fold(a["question"]), fold(a["answer"])) for a in self.store.answers(job_id)}
        saved = 0
        for item in answers:
            pair = (fold(item["rotulo"]), fold(item["valor"]))
            if pair in known:
                continue
            known.add(pair)
            self.store.add_answer(job_id, item["rotulo"], item["valor"], False, origin)
            saved += 1
        if saved:
            self.store.log(
                "respostas_formulario", f"{saved} resposta(s) do formulário guardada(s)", source,
                job_id=job_id, draft_id=draft_id,
            )

    def _apply_resposta(self, draft: dict[str, Any]) -> int:
        payload = draft["payload"]
        job = self.store.job(draft["job_id"]) if draft["job_id"] else self.store.job_by_url(draft["job_url"])
        if job is None:
            raise DraftError("Aprove antes o rascunho da vaga desta pergunta.")
        answer = payload.get("resposta", "").strip()
        if not answer:
            raise DraftError("Escreva a resposta antes de aprovar.")
        self.store.add_answer(job["id"], payload["pergunta"], answer, payload.get("sugerida_por") == "llm")
        if payload.get("inserir") and payload.get("campo") and payload.get("pagina"):
            self.store.add_insertion(payload["pagina"], payload["campo"], payload["pergunta"], answer)
        self.store.log(
            "resposta", f"Resposta salva: {payload['pergunta'][:120]}", draft["source"],
            job_id=job["id"], draft_id=draft["id"],
        )
        return job["id"]

    def _apply_mensagem(self, draft: dict[str, Any]) -> int:
        payload = draft["payload"]
        job_id = payload.get("job_id")
        job = self.store.job(int(job_id)) if job_id else None
        if job is None:
            raise DraftError("Escolha a vaga desta mensagem antes de aprovar.")
        contact_id = self.store.upsert_contact(
            payload.get("remetente_nome", ""), payload.get("remetente_email", ""), job["company"]
        )
        if contact_id:
            # Quem escreveu sobre a vaga fica vinculado a ela (aparece em Recrutadores e no chat).
            self.store.link_contact(job["id"], contact_id)
        self.store.add_message({
            "application_id": job["application_id"],
            "contact_id": contact_id,
            "channel": payload.get("canal", "email"),
            "external_id": payload.get("external_id"),
            "subject": payload.get("assunto", ""),
            "received_at": payload.get("recebido_em"),
            "body": payload.get("corpo", ""),
            "summary": payload.get("resumo", ""),
            "classification": payload.get("classificacao", "outro"),
            "event_at": payload.get("data_evento") or None,
        })
        self.store.log(
            "mensagem", f"E-mail: {payload.get('assunto') or payload.get('remetente_email')}", draft["source"],
            job_id=job["id"], draft_id=draft["id"], detail={"classificacao": payload.get("classificacao")},
        )
        target = payload.get("status_proposto")
        if target and target != job["status"]:
            self.store.set_status(job["id"], _status(target))
            self.store.log(
                "status", f"Status: {STATUS_LABELS.get(job['status'], '—')} → {STATUS_LABELS[target]}", draft["source"],
                job_id=job["id"], draft_id=draft["id"],
                detail={"de": job["status"], "para": target, "data_evento": payload.get("data_evento")},
            )
        if draft["job_id"] != job["id"]:
            self.store.update_draft(draft["id"], payload, job_id=job["id"])
        return job["id"]

    # Ações diretas do usuário no painel (já são a decisão dele)

    def add_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        fields = self._job_fields(raw, "manual")
        if linkedin_public.job_id(fields["url"]):
            fields = self._complete_from_public(fields)
        fields = insights.enrich(fields)
        if not fields["title"] and not fields["company"]:
            raise DraftError("Informe pelo menos o título ou a empresa.")
        if self.store.job_by_url(fields["url"]):
            raise DraftError("Esta vaga já está salva.")
        status = _status(raw.get("status") or "visualizada")
        with self.store.tx():
            job_id = self.store.insert_job(fields, status, now() if status != "visualizada" else None)
            self.store.attach_drafts_to_job(fields["url"], job_id)
            self.store.log("vaga_criada", f"Vaga adicionada por link: {_job_label(fields)}", "painel", job_id=job_id)
            self.ensure_company(job_id)
        self.hub.publish("vaga", id=job_id)
        return self.store.job(job_id)

    def set_status(self, job_id: int, status: str) -> dict[str, Any]:
        job = self._job(job_id)
        status = _status(status)
        if status == job["status"]:
            return job
        with self.store.tx():
            self.store.set_status(job_id, status, now() if status == "candidatado" else None)
            self.store.log(
                "status", f"Status: {STATUS_LABELS.get(job['status'], '—')} → {STATUS_LABELS[status]}", "painel",
                job_id=job_id, detail={"de": job["status"], "para": status},
            )
            self._stage_from_status(job_id, status)
        self.hub.publish("vaga", id=job_id)
        return self.store.job(job_id)

    def add_note(self, job_id: int, text: str) -> dict[str, Any]:
        self._job(job_id)
        text = text.strip()
        if not text:
            raise DraftError("A nota está vazia.")
        with self.store.tx():
            self.store.add_note(job_id, text)
            self.store.log("nota", f"Nota: {text[:120]}", "painel", job_id=job_id)
        self.hub.publish("vaga", id=job_id)
        return self.store.job(job_id)

    # Empresas

    def ensure_company(self, job_id: int) -> int | None:
        """Cadastra a empresa da vaga (se ainda não existe) e busca os dados públicos dela."""
        job = self.store.job(job_id)
        name = clean_space(job["company"] if job else "")
        if not name:
            return None
        company_id, created = self.store.upsert_company(
            company_key(name), name, {"linkedin_url": job["company_url"], "industry": job["industry"]}
        )
        if created:
            self.store.log("empresa_cadastrada", f"Empresa cadastrada: {name}", job["source"], job_id=job_id)
            self.hub.activity(f"Empresa cadastrada: {name}.", "ok")
        company = self.store.company(company_id)
        if company["linkedin_url"] and not company["fetched_at"]:
            self._run(self._refresh_company_quietly, company_id)
        return company_id

    def _refresh_company_quietly(self, company_id: int) -> None:
        try:
            self.refresh_company(company_id)
        except (linkedin_public.PublicPageError, LookupError):
            pass

    def refresh_company(self, company_id: int) -> dict[str, Any]:
        company = self.store.company(company_id)
        if company is None:
            raise LookupError(f"Empresa {company_id} não encontrada.")
        if not company["linkedin_url"]:
            raise DraftError("Esta empresa não tem página do LinkedIn ligada.")
        self.hub.activity(f"Buscando dados públicos da empresa {company['name']}…", "trabalhando")
        try:
            fields = self.public_company(company["linkedin_url"])
        except linkedin_public.PublicPageError as exc:
            self.hub.activity(f"Empresa {company['name']}: {exc}.", "erro")
            raise
        self.store.upsert_company(company["key"], company["name"], fields)
        self.store.mark_company_fetched(company_id)
        summary = " · ".join(value for value in (fields.get("industry"), fields.get("size")) if value)
        self.hub.activity(f"Empresa {company['name']} atualizada{': ' + summary if summary else ''}.", "ok")
        self.hub.publish("empresa", id=company_id)
        return self.store.company(company_id)

    def companies(self) -> list[dict[str, Any]]:
        jobs = self.store.jobs()
        for job in jobs:
            if job["company"] and not self.store.company_by_key(company_key(job["company"])):
                self.ensure_company(job["id"])
        grouped: dict[str, list[dict[str, Any]]] = {}
        for job in jobs:
            grouped.setdefault(company_key(job["company"]), []).append(job)
        rows = []
        for company in self.store.companies():
            own = grouped.get(company["key"], [])
            applied = [job for job in own if job["status"] != "visualizada"]
            rows.append({
                **company,
                "vagas": len(own),
                "candidaturas": len(applied),
                "ultima": max((job["status_at"] or job["updated_at"] for job in own), default=None),
                "status": sorted({job["status"] for job in own}),
            })
        return rows

    def company_detail(self, company_id: int) -> dict[str, Any]:
        company = self.store.company(company_id)
        if company is None:
            raise LookupError(f"Empresa {company_id} não encontrada.")
        jobs = [job for job in self.store.jobs() if company_key(job["company"]) == company["key"]]
        moves = []
        for job in jobs:
            moves.extend(self.store.movements(100, job["id"]))
        moves.sort(key=lambda move: move["id"], reverse=True)
        ids = {job["id"] for job in jobs}
        return {
            "empresa": company,
            "vagas": [{**job, "parada_dias": self._idle_days(job)} for job in jobs],
            "movimentos": moves[:200],
            "rascunhos": [draft for draft in self.store.drafts("pendente") if draft["job_id"] in ids],
        }

    def set_company_notes(self, company_id: int, notes: str) -> dict[str, Any]:
        if self.store.company(company_id) is None:
            raise LookupError(f"Empresa {company_id} não encontrada.")
        self.store.set_company_notes(company_id, notes.strip()[:5000])
        return self.store.company(company_id)

    # Sugestões para os campos de um formulário aberto (a extensão mostra; a pessoa clica para usar)

    def suggestions(self, fields: list[Any]) -> list[dict[str, str]]:
        profile = self.profile.load()
        result = []
        for item in fields[:MAX_SUGGESTIONS]:
            if not isinstance(item, dict):
                continue
            label = clean_space(str(item.get("rotulo") or ""))[:500]
            field = str(item.get("campo") or "")
            options = [clean_space(str(option))[:200] for option in item.get("opcoes") or []][:50]
            kind = str(item.get("tipo") or "text")
            if not label or not field:
                continue
            if kind == "text" and not options and suggest.numeric_question(label):
                kind = "number"
            limit = item.get("max") if isinstance(item.get("max"), (int, float)) else 0
            found = suggest.suggest(label, profile, options=options, kind=kind) or self._history_suggestion(label, options)
            if found and suggest.fits(found["valor"], kind, int(limit or 0)):
                result.append({"campo": field, **found})
        return result

    def ai_suggestions(self, fields: list[Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
        """Campos que as regras não souberam responder vão para a IA, de uma vez."""
        model = llm.model_name("responder")
        if not model:
            return {"ia": False, "sugestoes": []}
        clean = []
        for item in fields[:MAX_AI_FIELDS]:
            if not isinstance(item, dict):
                continue
            label = clean_space(str(item.get("rotulo") or ""))[:500]
            if not label or not item.get("campo") or suggest.profile_only(label):
                continue
            kind = str(item.get("tipo") or "text")
            options = [clean_space(str(option))[:200] for option in item.get("opcoes") or []][:30]
            if kind == "text" and not options and suggest.numeric_question(label):
                kind = "number"
            limit = item.get("max")
            clean.append({
                "campo": str(item["campo"]),
                "rotulo": label,
                "tipo": kind,
                "opcoes": options,
                "max": int(limit) if isinstance(limit, (int, float)) and limit > 0 else 0,
            })
        if not clean:
            return {"ia": True, "sugestoes": []}
        past = ai_suggest.examples([field["rotulo"] for field in clean], self._reusable_answers(), similarity)
        job_fields = None
        if isinstance(job, dict):
            try:
                known = self.store.job_by_url(normalize_url(str(job.get("url") or "")))
            except DraftError:
                known = None
            job_fields = known or {key: str(job.get(key) or "") for key in ("title", "company", "description")}
        self.hub.activity(f"IA pensando em {len(clean)} pergunta(s) do formulário…", "trabalhando")
        profile_text = as_prompt(self.profile.load())
        facts = profile_text + "\n" + json.dumps(past, ensure_ascii=False)

        def ask(batch: list[dict[str, Any]]) -> list[dict[str, str]]:
            raw = llm.ask_llm("responder", ai_suggest.prompt(batch, profile_text, past, job_fields),
                              system=ai_suggest.SYSTEM, as_json=True, timeout=180 if any(field["tipo"] == "textarea" for field in batch) else 120)
            return ai_suggest.parse(raw, batch, model, facts)

        try:
            found = ask(clean)
            # Modelo pequeno às vezes pula campos do lote: os que faltaram têm uma segunda chance, sozinhos.
            answered = {item["campo"] for item in found}
            missing = [field for field in clean if field["campo"] not in answered]
            if missing and len(clean) > 1:
                for field in missing:
                    found += ask([field])
        except llm.LLMUnavailable as exc:
            self.hub.activity(f"IA indisponível para o formulário. {exc}", "aviso")
            return {"ia": True, "sugestoes": [], "erro": str(exc)}
        self.hub.activity(f"IA sugeriu {len(found)} de {len(clean)} resposta(s). Confira antes de usar.", "ok" if found else "info")
        return {"ia": True, "sugestoes": found}

    def _history_suggestion(self, label: str, options: list[str]) -> dict[str, str] | None:
        if suggest.SENSITIVE.search(fold(label)):
            return None
        remembered = self._from_history(label)
        if not remembered:
            return None
        value = remembered["resposta"]
        if options:
            index = suggest.fit_text(value, options)
            if index < 0:
                yes_no = suggest.yes_no(value)
                index = suggest.fit_yes_no(yes_no, options) if yes_no is not None else -1
            if index < 0:
                return None
            value = options[index]
        return {"valor": value, "origem": "historico", "base": remembered["base"]}

    # Backlog de melhoria do currículo: "Ponto de melhoria" na sugestão manda a pergunta para cá

    def add_improvement(self, data: dict[str, Any]) -> dict[str, Any]:
        question = clean_space(str(data.get("pergunta") or ""))[:500]
        if not question:
            raise ValueError("Pergunta vazia.")
        job = data.get("vaga") if isinstance(data.get("vaga"), dict) else {}
        improvement_id = self.store.add_improvement({
            "question": question,
            "options": [clean_space(str(option))[:200] for option in data.get("opcoes") or []][:30],
            "kind": str(data.get("tipo") or "text")[:20],
            "suggestion": clean_space(str(data.get("sugestao") or ""))[:500],
            "basis": clean_space(str(data.get("base") or ""))[:300],
            "origin": str(data.get("origem") or "")[:20],
            "job": _job_label(job) if job else "",
            "job_url": str(job.get("url") or "")[:500],
        })
        self.hub.activity(f"Ponto de melhoria anotado: “{question[:80]}”. Veja em Currículo.", "info")
        self.hub.publish("melhorias")
        return self.store.improvement(improvement_id)

    def reprocess_improvement(self, improvement_id: int) -> dict[str, Any]:
        """Responde de novo com o currículo de agora: regras e, se ligada, a IA."""
        item = self.store.improvement(improvement_id)
        if item is None:
            raise LookupError(f"Ponto {improvement_id} não encontrado.")
        profile = self.profile.load()
        rule = suggest.suggest(item["question"], profile, options=item["options"], kind=item["kind"])
        field = {"campo": "melhoria", "rotulo": item["question"], "tipo": item["kind"], "opcoes": item["options"]}
        ai = self.ai_suggestions([field]) if not rule else {"ia": bool(llm.model_name("responder")), "sugestoes": []}
        found = rule or (ai["sugestoes"][0] if ai.get("sugestoes") else None)
        latest = {
            "em": now(),
            "valor": found["valor"] if found else "",
            "base": found["base"] if found else "Nem as regras nem a IA acharam resposta com o currículo atual.",
            "origem": found["origem"] if found else "",
            "mudou": bool(found) and found["valor"] != item["suggestion"],
        }
        self.store.update_improvement(improvement_id, latest=latest)
        self.hub.publish("melhorias")
        return self.store.improvement(improvement_id)

    def set_improvement(self, improvement_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if self.store.improvement(improvement_id) is None:
            raise LookupError(f"Ponto {improvement_id} não encontrado.")
        fields: dict[str, Any] = {}
        if "estado" in data:
            state = str(data["estado"])
            if state not in {"aberto", "resolvido", "descartado"}:
                raise ValueError("Estado inválido.")
            fields["state"] = state
        if "nota" in data:
            fields["note"] = clean_space(str(data["nota"] or ""))[:1000]
        self.store.update_improvement(improvement_id, **fields)
        self.hub.publish("melhorias")
        return self.store.improvement(improvement_id)

    # Respostas já dadas: base do preenchimento automático

    def _reusable_answers(self) -> list[dict[str, Any]]:
        """Respostas que podem preencher outros formulários (as de "só registro" ficam de fora)."""
        return [answer for answer in self.store.answers() if answer.get("origin") != "registro"]

    def answer_history(self) -> list[dict[str, str]]:
        latest: dict[str, dict[str, str]] = {}
        for answer in self._reusable_answers():
            key = fold(answer["question"])
            if key and key not in latest and answer["answer"].strip():
                latest[key] = {
                    "rotulo": answer["question"],
                    "valor": answer["answer"],
                    "quando": answer["created_at"],
                    "vaga": _job_label(answer),
                    "origem": answer.get("origin") or "rascunho",
                }
        return list(latest.values())

    # Vagas frias: sem movimento há muito tempo

    def _idle_days(self, job: dict[str, Any]) -> int | None:
        last = self.store.last_activity(job["id"]) or job["status_at"] or job["updated_at"]
        try:
            then = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            return None
        return max(0, (datetime.now(then.tzinfo) - then).days)

    def check_cold(self, days: int) -> list[dict[str, Any]]:
        """Propõe marcar como fria a vaga em aberto sem novidade há `days` dias. Só propõe; você decide."""
        created = []
        for job in self.store.jobs():
            if job["status"] not in OPEN_STATUSES:
                continue
            idle = self._idle_days(job)
            if idle is None or idle < days:
                continue
            last = self.store.last_activity(job["id"]) or ""
            key = f"fria:{job['id']}:{last}"
            if self.store.pending_draft(key) or self.store.was_discarded(key) or self.store.pending_draft(f"status:{job['id']}"):
                continue
            payload = {
                "vaga": _job_label(job),
                "de": job["status"],
                "para": "fria",
                "quando": now(),
                "motivo": f"Sem novidade há {idle} dias.",
            }
            draft = self._new_draft("status", key, "painel", payload, job_id=job["id"], job_url=job["url"])
            created.append(draft)
            self.hub.activity(
                f"{_job_label(job)} está parada há {idle} dias. Marcar como fria?", "aviso", rascunho=draft["id"]
            )
        if created:
            self.hub.publish("rascunhos", ids=[draft["id"] for draft in created])
        return created

    def _job(self, job_id: int) -> dict[str, Any]:
        job = self.store.job(job_id)
        if job is None:
            raise LookupError(f"Vaga {job_id} não encontrada.")
        return job

    # Consulta

    # Recrutadores

    def _contact_fields(self, data: dict[str, Any]) -> dict[str, str]:
        mapping = {"nome": "name", "email": "email", "telefone": "phone", "empresa": "company", "cargo": "role", "linkedin": "linkedin", "notas": "notes"}
        fields = {column: clean_space(str(data[key]))[:500] for key, column in mapping.items() if key in data}
        if "email" in fields and fields["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", fields["email"]):
            raise ValueError("E-mail inválido.")
        return fields

    def create_contact(self, data: dict[str, Any], job_id: int | None = None) -> dict[str, Any]:
        fields = self._contact_fields(data)
        if not fields.get("name") and not fields.get("email") and not fields.get("linkedin"):
            raise ValueError("Informe pelo menos o nome, o e-mail ou o LinkedIn da pessoa.")
        contact_id = self.store.create_contact(fields)
        if job_id:
            self.link_contact(job_id, contact_id)
        self.hub.publish("recrutadores")
        return self.contact_detail(contact_id)

    def update_contact(self, contact_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if self.store.contact(contact_id) is None:
            raise LookupError(f"Recrutador {contact_id} não encontrado.")
        self.store.update_contact(contact_id, self._contact_fields(data))
        self.hub.publish("recrutadores")
        return self.contact_detail(contact_id)

    def link_contact(self, job_id: int, contact_id: int) -> None:
        job = self._job(job_id)
        contact = self.store.contact(contact_id)
        if contact is None:
            raise LookupError(f"Recrutador {contact_id} não encontrado.")
        self.store.link_contact(job_id, contact_id)
        if not contact["company"] and job["company"]:
            self.store.update_contact(contact_id, {"company": job["company"]})
        self.store.log("recrutador", f"{contact['name'] or contact['email']} vinculado(a) à vaga", "painel", job_id=job_id)
        self.hub.publish("recrutadores")

    def unlink_contact(self, job_id: int, contact_id: int) -> None:
        self.store.unlink_contact(job_id, contact_id)
        self.hub.publish("recrutadores")

    def contact_detail(self, contact_id: int) -> dict[str, Any]:
        contact = self.store.contact(contact_id)
        if contact is None:
            raise LookupError(f"Recrutador {contact_id} não encontrado.")
        return {**contact, "vagas": [_job_brief(job) for job in self.store.contact_jobs(contact_id)]}

    def find_contact(self, name: str = "", email: str = "", linkedin: str = "", phone: str = "") -> dict[str, Any] | None:
        """Quem está na conversa: pelo e-mail, LinkedIn ou telefone; senão pelo nome (inteiro, sem acento)."""
        contacts = self.store.contacts()
        digits = re.sub(r"\D", "", phone)
        for contact in contacts:
            if email and (contact["email"] or "").lower() == email.lower():
                return contact
            if linkedin and contact["linkedin"] and _linkedin_slug(contact["linkedin"]) == _linkedin_slug(linkedin):
                return contact
            if len(digits) >= 8 and re.sub(r"\D", "", contact["phone"] or "").endswith(digits[-8:]):
                return contact
        wanted = fold(clean_space(name))
        if wanted:
            for contact in contacts:
                if fold(contact["name"] or "") == wanted:
                    return contact
        return None

    def chat_context(self, data: dict[str, Any]) -> dict[str, Any]:
        """Para a barra do chat: quem é a pessoa, as vagas dela e a vaga mais provável da conversa."""
        name = clean_space(str(data.get("nome") or ""))[:120]
        contact = self.find_contact(name, str(data.get("email") or ""), str(data.get("linkedin") or ""), str(data.get("telefone") or ""))
        jobs = self.store.contact_jobs(contact["id"]) if contact else []
        # A empresa citada na conversa vale mais que o vínculo: a mesma pessoa pode estar falando de outra vaga.
        guess = replies.match_job([str(data.get("texto") or "")], self.store.jobs()) or (jobs[0] if jobs else None)
        return {
            "recrutador": {**contact, "vagas": [_job_brief(job) for job in jobs]} if contact else None,
            "vaga_sugerida": _job_brief(guess) if guess else None,
            "vagas": [_job_brief(job) for job in self.store.jobs() if job["title"] or job["company"]][:80],
            "intencoes": [intent for intent in self.message_library() if intent["ativo"]],
        }

    def chat_record(self, data: dict[str, Any]) -> dict[str, Any]:
        """Guarda na vaga a resposta inserida no chat; quem escreveu do outro lado conta como retorno."""
        job = self.store.job(int(data["vaga_id"])) if data.get("vaga_id") else None
        text = str(data.get("texto") or "").strip()[:4000]
        if job is None or not text:
            return {"registrado": False}
        channel = str(data.get("canal") or "chat")[:20]
        self.store.add_message({
            "application_id": job["application_id"], "contact_id": data.get("contato_id") or None, "channel": channel,
            "subject": clean_space(str(data.get("intencao") or "Resposta no chat"))[:120], "body": text, "summary": text[:200],
            "classification": "enviada",
        })
        source = channel if channel in SOURCES else "painel"
        self.store.log("mensagem", f"Resposta inserida no {SITE_NAMES.get(channel, channel)}", source, job_id=job["id"], detail={"intencao": data.get("intencao")})
        if data.get("recebeu"):
            self.store.log("chat_retorno", "Recrutador respondeu no chat", source, job_id=job["id"])
        self.hub.publish("vaga", id=job["id"])
        return {"registrado": True}

    def chat_approach(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recrutador oferecendo vaga no chat: se ainda não está salva, vira rascunho de vaga para aprovar."""
        turns = replies.conversation(data.get("conversa"))
        channel = "whatsapp" if data.get("canal") == "whatsapp" else "linkedin"
        texts = [turn["texto"] for turn in turns if not turn["minha"]]
        known = replies.match_job(texts, self.store.jobs())
        if known:
            return {"estado": "salva", "vaga": _job_brief(known)}
        found = approach.detect(turns)
        if not found:
            return {"estado": "nada"}
        name = clean_space(str(data.get("nome") or ""))[:120]
        if found["link"]:
            try:
                url = normalize_url(found["link"])
            except DraftError:
                url = ""
        else:
            url = ""
        if not url:
            # Sem link da vaga: um endereço próprio do JobScout identifica a abordagem (não abre nada).
            slug = re.sub(r"[^a-z0-9]+", "-", fold(f"{name or data.get('telefone') or 'contato'} {found['empresa'] or found['titulo']}")).strip("-")
            url = f"https://jobscout.local/abordagem/{channel}/{slug[:80]}"
        existing = self.store.job_by_url(url)
        if existing:
            return {"estado": "salva", "vaga": _job_brief(existing)}
        key = "vaga:" + url
        if self.store.pending_draft(key):
            return {"estado": "rascunho", "vaga": {"titulo": found["titulo"], "empresa": found["empresa"]}}
        if self.store.was_discarded(key):
            return {"estado": "descartada"}
        excerpt = replies.transcript(turns, name)[-4000:]
        payload = {
            "source": channel, "url": url, "title": found["titulo"], "company": found["empresa"],
            "location": found["local"], "description": f"Abordagem pelo {SITE_NAMES[channel]}:\n\n{excerpt}",
            "work_mode": WORK_MODE_NAMES.get(found["modelo"], ""), "status": "visualizada", "candidatado_em": None,
            "recrutador": {
                "nome": name, "email": clean_space(str(data.get("email") or "")),
                "linkedin": clean_space(str(data.get("linkedin") or "")), "telefone": clean_space(str(data.get("telefone") or "")),
            },
            "abordagem": True,
        }
        for field in EXTRA_FIELDS:
            payload.setdefault(field, "")
        draft = self._new_draft("vaga", key, channel, payload, job_url=url)
        self.hub.publish("rascunhos", ids=[draft["id"]])
        who = name or "Um recrutador"
        self.hub.activity(f"{who} ofereceu {_job_label(payload)} no {SITE_NAMES[channel]}. Aprove para virar oportunidade.", "aviso", rascunho=draft["id"])
        return {"estado": "novo", "rascunho": draft["id"], "vaga": {"titulo": found["titulo"], "empresa": found["empresa"]}, "origem": found["origem"]}

    # Etapas do processo (quadro da empresa)

    def _company_of(self, job: dict[str, Any]) -> dict[str, Any] | None:
        return self.store.company_by_key(company_key(job["company"])) if job.get("company") else None

    def stages(self, job_id: int) -> list[dict[str, Any]]:
        """Etapas da vaga; na primeira vez, saem do quadro da empresa (ou do padrão) e do status atual."""
        job = self._job(job_id)
        stages = self.store.job_stages(job_id)
        if not stages:
            initial = pipeline.initial_stages(pipeline.company_pipeline(self._company_of(job)), job["status"])
            self.store.replace_job_stages(job_id, initial)
            stages = self.store.job_stages(job_id)
        return stages

    def stages_view(self, job_id: int) -> dict[str, Any]:
        job = self._job(job_id)
        company = self._company_of(job)
        return {
            "etapas": self.stages(job_id),
            "tipos": pipeline.KINDS,
            "sugestoes": [{"nome": name, "tipo": kind} for name, kind in pipeline.SUGGESTIONS],
            "empresa": {"id": company["id"], "nome": company["name"], "quadro": pipeline.company_pipeline(company),
                        "personalizado": bool(company.get("pipeline"))} if company else None,
        }

    def save_stages(self, job_id: int, raw: Any, source: str = "painel") -> dict[str, Any]:
        job = self._job(job_id)
        stages = pipeline.clean_stages(raw)
        if not stages:
            raise DraftError("Deixe pelo menos uma etapa.")
        with self.store.tx():
            self.store.replace_job_stages(job_id, stages)
            self.store.log("etapas", "Etapas do processo atualizadas", source, job_id=job_id)
            self._status_from_stage(job, pipeline.current(stages), source)
        self.hub.publish("vaga", id=job_id)
        return self.stages_view(job_id)

    def move_to_stage(self, job_id: int, target: Any, source: str = "painel") -> dict[str, Any]:
        """Leva a vaga para a etapa (pelo índice ou pelo nome); o status geral acompanha o tipo da etapa."""
        job = self._job(job_id)
        stages = self.stages(job_id)
        if isinstance(target, int) or str(target).isdigit():
            index = int(target)
        else:
            index = next((i for i, stage in enumerate(stages) if fold(stage["name"]) == fold(str(target))), -1)
            if index < 0:
                # Quadro da empresa tem uma etapa que esta vaga ainda não tinha: entra na posição do quadro.
                board = pipeline.company_pipeline(self._company_of(job))
                wanted = next((stage for stage in board if fold(stage["name"]) == fold(str(target))), None)
                if wanted is None:
                    raise DraftError(f"Etapa “{target}” não existe nesta vaga.")
                order = [fold(stage["name"]) for stage in board]
                position = sum(1 for stage in stages if fold(stage["name"]) in order[:order.index(fold(wanted["name"]))])
                stages.insert(position, {**wanted, "state": "pendente", "scheduled_at": None, "notes": "", "done_at": None})
                index = position
        moved = pipeline.advance(stages, index, now())
        with self.store.tx():
            self.store.replace_job_stages(job_id, moved)
            self.store.log("etapa", f"Etapa: {moved[index]['name']}", source, job_id=job_id, detail={"etapa": moved[index]["name"]})
            self._status_from_stage(job, moved[index], source)
        self.hub.publish("vaga", id=job_id)
        return self.stages_view(job_id)

    def _status_from_stage(self, job: dict[str, Any], stage: dict[str, Any] | None, source: str) -> None:
        if not stage or stage["kind"] == job["status"] or job["status"] in {"recusada", "fria"}:
            return
        self.store.set_status(job["id"], stage["kind"], now() if stage["kind"] == "candidatado" else None)
        self.store.log(
            "status", f"Status: {STATUS_LABELS.get(job['status'], '—')} → {STATUS_LABELS[stage['kind']]}", source,
            job_id=job["id"], detail={"de": job["status"], "para": stage["kind"], "etapa": stage["name"]},
        )

    def _stage_from_status(self, job_id: int, status: str) -> None:
        """Mudou o status pelo quadro geral: a etapa atual vai para a próxima do mesmo tipo."""
        stages = self.store.job_stages(job_id)
        if not stages or status not in pipeline.KINDS:
            return
        here = next((i for i, stage in enumerate(stages) if stage["state"] == "atual"), -1)
        if here >= 0 and stages[here]["kind"] == status:
            return
        ahead = [i for i, stage in enumerate(stages) if stage["kind"] == status and i > here]
        anywhere = [i for i, stage in enumerate(stages) if stage["kind"] == status]
        target = (ahead or anywhere or [None])[0]
        if target is not None:
            self.store.replace_job_stages(job_id, pipeline.advance(stages, target, now()))

    def save_company_pipeline(self, company_id: int, raw: Any, apply_to_jobs: bool = False) -> dict[str, Any]:
        company = self.store.company(company_id)
        if company is None:
            raise LookupError(f"Empresa {company_id} não encontrada.")
        board = pipeline.clean_pipeline(raw)
        if not board:
            raise DraftError("O quadro precisa de pelo menos uma etapa.")
        default = [dict(stage) for stage in pipeline.DEFAULT_PIPELINE]
        self.store.set_company_pipeline(company_id, [] if board == default else board)
        self.store.log("quadro_empresa", f"Quadro da {company['name']}: " + " → ".join(stage["name"] for stage in board), "painel")
        changed = 0
        if apply_to_jobs:
            for job in self.store.jobs():
                if job["company"] and company_key(job["company"]) == company["key"]:
                    self._rebuild_stages(job, board)
                    changed += 1
        self.hub.publish("empresas")
        return {**self.company_board(company_id), "vagas_atualizadas": changed}

    def _rebuild_stages(self, job: dict[str, Any], board: list[dict[str, str]]) -> None:
        """Novo quadro numa vaga em andamento: mantém estado, data e notas das etapas de mesmo nome."""
        old = {fold(stage["name"]): stage for stage in self.store.job_stages(job["id"])}
        if not old:
            self.store.replace_job_stages(job["id"], pipeline.initial_stages(board, job["status"]))
            return
        rebuilt = []
        for stage in board:
            before = old.get(fold(stage["name"]))
            rebuilt.append({**stage, **({k: before[k] for k in ("state", "scheduled_at", "notes", "done_at")} if before else
                                        {"state": "pendente", "scheduled_at": None, "notes": "", "done_at": None})})
        if not any(stage["state"] == "atual" for stage in rebuilt):
            rebuilt = pipeline.initial_stages(board, job["status"]) if not any(s["state"] == "feita" for s in rebuilt) else rebuilt
        self.store.replace_job_stages(job["id"], rebuilt)

    def company_board(self, company_id: int) -> dict[str, Any]:
        """Kanban da empresa: colunas = etapas do quadro dela; cada vaga na etapa atual."""
        company = self.store.company(company_id)
        if company is None:
            raise LookupError(f"Empresa {company_id} não encontrada.")
        board = pipeline.company_pipeline(company)
        names = [fold(stage["name"]) for stage in board]
        cards = []
        for job in self.store.jobs():
            if not job["company"] or company_key(job["company"]) != company["key"]:
                continue
            stages = self.stages(job["id"])
            here = pipeline.current(stages)
            column = fold(here["name"]) if here else ""
            cards.append({
                **_job_brief(job), "status": job["status"], "local": job["location"], "modo": job.get("work_mode") or "",
                "etapa": here["name"] if here else "",
                "coluna": column if column in names else ("encerrada" if job["status"] in {"recusada", "fria"} else ""),
                "proxima": next((s["scheduled_at"] for s in stages if s["state"] in {"atual", "pendente"} and s.get("scheduled_at")), None),
            })
        return {
            "empresa": {"id": company["id"], "nome": company["name"]},
            "quadro": board,
            "personalizado": bool(company.get("pipeline")),
            "tipos": pipeline.KINDS,
            "sugestoes": [{"nome": name, "tipo": kind} for name, kind in pipeline.SUGGESTIONS],
            "vagas": cards,
        }

    # Encaixe da vaga com o perfil

    def my_skills(self) -> list[str]:
        profile = self.profile.load()
        parts = [profile.get("curriculo") or ""] + [story.get("texto", "") for story in profile.get("historias") or []]
        declared = [item.get("skill", "") for item in profile.get("skills_extras") or [] if isinstance(item, dict)]
        return list(dict.fromkeys([*insights.skills("\n".join(parts)), *(name for name in declared if name)]))

    def rule_fit(self, job: dict[str, Any]) -> int | None:
        """% das skills pedidas na vaga que o perfil tem; None se a vaga não cita nenhuma."""
        wanted = cv.job_skills(job)
        if not wanted:
            return None
        mine = {fold(name) for name in self.my_skills()}
        return round(100 * sum(1 for name in wanted if fold(name) in mine) / len(wanted))

    def job_fit(self, job_id: int) -> dict[str, Any]:
        """Avaliação da IA: nota de 0 a 100, o que combina, o que falta e um resumo. Fica salva na vaga."""
        job = self._job(job_id)
        if not llm.available("responder"):
            raise llm.LLMUnavailable("IA desligada. Ligue em Config > IA.")
        profile = as_prompt(self.profile.load())
        prompt = (
            f"Perfil da pessoa:\n{profile[:5000]}\n\n"
            f"Vaga: {job['title']} — {job['company']}\n{job['location']}\n{str(job['description'])[:4000]}"
        )
        system = (
            "Você avalia o quanto um perfil se encaixa numa vaga. Compare habilidades, tempo de experiência, senioridade e idioma. "
            "Use só o que está escrito no perfil e na vaga; o que o perfil não cita conta como lacuna, não como conhecimento. "
            "Responda só com JSON: {\"nota\": 0 a 100, \"combina\": [\"até 6 itens\"], \"faltam\": [\"até 6 itens\"], \"resumo\": \"uma frase\"}"
        )
        raw = llm.ask_llm("responder", prompt, system=system, as_json=True, timeout=150)
        try:
            answer = json.loads(raw)
            grade = max(0, min(100, int(float(answer.get("nota")))))
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            raise llm.LLMUnavailable("A IA não devolveu uma avaliação válida. Tente de novo.") from exc
        result = {
            "nota": grade,
            "combina": [clean_space(str(item))[:120] for item in answer.get("combina") or []][:6],
            "faltam": [clean_space(str(item))[:120] for item in answer.get("faltam") or []][:6],
            "resumo": clean_space(str(answer.get("resumo") or ""))[:300],
            "modelo": llm.model_name("responder"),
            "em": now(),
        }
        self.store.set_job_fit(job_id, result)
        self.hub.publish("vaga", id=job_id)
        return result

    # Chat da aba Busca: perguntas sobre o histórico, com as conversas guardadas

    def chat_thread(self, thread_id: int) -> dict[str, Any]:
        thread = self.store.chat_thread(thread_id)
        if thread is None:
            raise LookupError(f"Conversa {thread_id} não encontrada.")
        return {**thread, "mensagens": self.store.chat_messages(thread_id)}

    def _chat_overview(self) -> str:
        jobs = self.store.jobs()
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job["status"]] = counts.get(job["status"], 0) + 1
        lines = ", ".join(f"{STATUS_LABELS.get(key, key)}: {value}" for key, value in counts.items())
        return f"{len(jobs)} vaga(s) salvas. Por status: {lines or 'nenhuma'}."

    def chat(self, thread_id: int | None, text: str) -> dict[str, Any]:
        text = clean_space(text)[:2000]
        if not text:
            raise DraftError("Escreva a pergunta.")
        if thread_id is None:
            thread_id = self.store.add_chat_thread(text[:70])
        elif self.store.chat_thread(thread_id) is None:
            raise LookupError(f"Conversa {thread_id} não encontrada.")
        earlier = self.store.chat_messages(thread_id)[-6:]
        self.store.add_chat_message(thread_id, "pessoa", text)
        hits = self.search(text, 8)
        sources = [{"tipo": hit["tipo"], "titulo": hit["titulo"], "vaga": hit["vaga"], "job_id": hit["job_id"], "quando": hit["quando"], "texto": hit["texto"]} for hit in hits]
        answer, origin = self._chat_answer(text, earlier, hits)
        self.store.add_chat_message(thread_id, "jobscout", answer, sources)
        return {**self.chat_thread(thread_id), "origem": origin}

    def _chat_answer(self, text: str, earlier: list[dict[str, Any]], hits: list[dict[str, Any]]) -> tuple[str, str]:
        kinds = {"vaga": "vaga", "resposta": "resposta sua", "mensagem": "mensagem", "nota": "nota"}
        if not llm.available("chat"):
            if not hits:
                return f"Não achei nada sobre isso no histórico. {self._chat_overview()} Com a IA ligada (Config > IA), eu também resumo a resposta.", "regras"
            lines = [f"- {kinds.get(hit['tipo'], hit['tipo'])}{' (' + hit['vaga'] + ')' if hit['vaga'] else ''}: {hit['titulo']} — {hit['texto']}" for hit in hits[:5]]
            return "Achei isto no histórico:\n" + "\n".join(lines), "regras"
        context = "\n".join(
            f"[{hit['tipo']}] {hit['vaga']} | {hit['titulo']} | {str(hit['quando'] or '')[:10]}\n{hit['texto']}" for hit in hits
        ) or "(nada encontrado no histórico)"
        talk = "\n".join(f"{'Pessoa' if row['role'] == 'pessoa' else 'JobScout'}: {row['text'][:400]}" for row in earlier)
        system = (
            "Você é o assistente do JobScout e responde sobre o histórico de candidaturas da pessoa. Use só o resumo e os trechos "
            "do histórico abaixo; se a resposta não estiver neles, diga que não encontrou. Seja direto, em português, em até 5 frases, "
            "citando vaga e empresa quando houver."
        )
        prompt = f"Resumo: {self._chat_overview()}\n\nTrechos do histórico:\n{context}\n\n" + (f"Conversa até agora:\n{talk}\n\n" if talk else "") + f"Pergunta: {text}"
        try:
            reply = llm.ask_llm("chat", prompt, system=system, timeout=120).strip()
        except llm.LLMUnavailable as exc:
            return f"A IA não respondeu ({exc}). Os trechos do histórico estão abaixo.", "regras"
        return reply or "Não encontrei isso no histórico.", "ia"

    def message_library(self) -> list[dict[str, Any]]:
        return replies.library(self.message_overrides())

    def message_overrides(self) -> dict[str, Any]:
        return self._message_overrides_loader() if self._message_overrides_loader else {}

    def results(self) -> list[dict[str, Any]]:
        """Candidaturas com o que foi enviado e até onde cada uma chegou (retorno, entrevista, proposta)."""
        reached = self.store.stages()
        answered = self.store.chat_returns()
        versions = [{**version, "label": version["name"]} for version in self.store.resume_versions()]
        rows = []
        for job in self.store.jobs():
            stages = set(reached.get(job["id"], set())) | {job["status"]}
            if not (job["applied_at"] or stages & set(APPLIED_STAGES)):
                continue
            rows.append({
                "id": job["id"],
                "titulo": job["title"],
                "empresa": job["company"],
                "fonte": SITE_NAMES.get(job["source"], job["source"]),
                "senioridade": job.get("seniority") or "",
                "modelo": job.get("work_mode") or "",
                "regiao": job.get("region") or "",
                "status": job["status"],
                "candidatado_em": job["applied_at"] or "",
                "documentos": job.get("documents") or "",
                "curriculo": cv.resume_kind(job.get("documents") or "", versions),
                "salario_informado": job.get("salary_informed") or "",
                "retorno": bool(stages & RETURN_STAGES) or job["id"] in answered,
                "entrevista": bool(stages & {"entrevista", "proposta"}),
                "proposta": "proposta" in stages,
                "recusada": "recusada" in stages,
                "url": job["url"],
            })
        return rows

    def detail(self, job_id: int) -> dict[str, Any]:
        job = self._job(job_id)
        company = self.store.company_by_key(company_key(job["company"])) if job["company"] else None
        versions = [{**version, "label": version["name"]} for version in self.store.resume_versions()]
        return {
            "vaga": job,
            "empresa": company,
            "parada_dias": self._idle_days(job),
            "respostas": self.store.answers(job_id),
            "mensagens": self.store.messages(job_id),
            "notas": self.store.notes(job_id),
            "movimentos": self.store.movements(100, job_id),
            "rascunhos": self.store.drafts("pendente", job_id),
            "recrutadores": self.store.job_contacts(job_id),
            "encaixe": self.rule_fit(job),
            "encaixe_ia": json.loads(job["fit_ai"]) if job.get("fit_ai") else None,
            "curriculo": cv.resume_kind(job.get("documents") or "", versions),
            "curriculos": [
                {"valor": version["name"], "nome": f"{'Customizado' if version['job_id'] else 'Padrão'}: {version['name']}"}
                for version in versions if version["job_id"] == job_id or not version["job_id"]
            ] + [{"valor": "Currículo padrão", "nome": "Padrão: Currículo padrão"}],
        }

    def prepare(self, job_id: int) -> dict[str, Any]:
        """Material para estudar antes da entrevista. Não é para usar durante ela."""
        job = self._job(job_id)
        answers = self.store.answers(job_id)
        messages = self.store.messages(job_id)
        tools = list_tools(job["description"])
        questions = [f"Conte um projeto em que você usou {tool}." for tool in tools[:5]]
        questions += [
            f"Por que você quer trabalhar na {job['company'] or 'empresa'}?",
            "Conte uma situação difícil no trabalho e como você resolveu.",
        ]
        source = "regras"
        if llm.available("preparar"):
            prompt = (
                f"Perfil:\n{as_prompt(self.profile.load())}\n\nVaga: {_job_label(job)}\n{job['description'][:5000]}\n\n"
                "Respostas já enviadas no formulário:\n"
                + "\n".join(f"- {a['question']}: {a['answer']}" for a in answers)
                + "\n\nListe até 8 perguntas prováveis da entrevista, uma por linha, sem numeração."
            )
            try:
                text = llm.ask_llm("preparar", prompt)
                generated = [line.strip("-• ").strip() for line in text.splitlines() if line.strip()]
                if generated:
                    questions, source = generated[:8], "llm"
            except llm.LLMUnavailable:
                pass
        return {
            "vaga": job,
            "ferramentas": tools,
            "respostas": answers,
            "mensagens": messages,
            "perguntas": questions,
            "fonte_perguntas": source,
        }

    def search(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        terms = _words(query)
        if not terms:
            return []
        jobs = {job["id"]: job for job in self.store.jobs()}
        results = []
        for row in self.store.corpus():
            job = jobs.get(row["job_id"])
            context = f"{job['title']} {job['company']}" if job else ""
            haystack = _words(f"{row['titulo']} {row['texto']} {context}")
            hits = terms & haystack
            if not hits:
                continue
            results.append({
                **row,
                "texto": _snippet(row["texto"], hits),
                "vaga": _job_label(job) if job else "",
                "pontos": len(hits) / len(terms),
            })
        results.sort(key=lambda item: item["quando"] or "", reverse=True)
        results.sort(key=lambda item: item["pontos"], reverse=True)
        return results[:limit]

    def _run(self, target: Any, *args: Any) -> None:
        if self.background:
            threading.Thread(target=target, args=args, daemon=True).start()
        else:
            target(*args)


def company_key(name: str) -> str:
    return fold(clean_space(name or ""))


def _job_brief(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"], "titulo": job["title"], "empresa": job["company"], "status": job.get("status") or "",
        "candidatado_em": job.get("applied_at") or "",
    }


def _linkedin_slug(url: str) -> str:
    match = re.search(r"linkedin\.com/in/([^/?#]+)", url or "", re.I)
    return (match.group(1) if match else (url or "")).strip("/").lower()


def _documents(raw: Any) -> list[str]:
    """Nomes de arquivo enviados (currículo, carta), sem caminho e sem repetir."""
    names = []
    for item in raw if isinstance(raw, list) else []:
        name = clean_space(str(item or "")).replace("\\", "/").rsplit("/", 1)[-1][:160]
        if name and name not in names:
            names.append(name)
    return names[:5]


def _form_answers(raw: Any) -> list[dict[str, str]]:
    """Respostas lidas do formulário no envio: só pares rótulo/valor preenchidos."""
    answers = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        label = clean_space(str(item.get("rotulo") or ""))[:500]
        value = str(item.get("valor") or "").strip()[:5000]
        if label and value:
            answers.append({"rotulo": label, "valor": value})
    return answers[:MAX_ANSWERS]


def _status(value: Any) -> str:
    status = str(value or "")
    if status not in STATUS_KEYS:
        raise DraftError(f"Status inválido: {status}")
    return status


def _snippet(text: str, hits: set[str], width: int = 220) -> str:
    plain = clean_space(text)
    folded = fold(plain)
    starts = [folded.find(word) for word in hits if folded.find(word) >= 0]
    start = max(0, min(starts) - 60) if starts else 0
    piece = plain[start:start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(plain) else "")
