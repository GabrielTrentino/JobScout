"""Serve o painel e a API só neste computador."""

from __future__ import annotations

import csv
import io
import json
import queue
import re
import threading
import time
from email import message_from_bytes
from email import policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from jobscout import appearance, cv, exporting, insights, jobsearch, linkedin_public, llm, mail, preferences, reminders, replies, resume_tools
from jobscout.activities import (
    MAX_BYTES,
    ResumeReadError,
    fold,
    list_activities,
    list_tools,
    read_resume_bytes,
)
from jobscout.assistant import Assistant, DraftError, company_key
from jobscout.config import data_dir, setting
from jobscout.events import Hub
from jobscout.gmail import ALERT_QUERY, Gmail, GmailError, Poller
from jobscout.preferences import Preferences
from jobscout.profile import Profile, as_prompt, standard_fields
from jobscout.store import STATUSES, Store, now

WEB = Path(__file__).with_name("web")
STATIC = {
    "index.html": "text/html; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}
MAX_JSON = 2 * 1024 * 1024
HEARTBEAT = 15
EXTENSION_ALIVE_SECONDS = 180
COLD_CHECK_SECONDS = 3600


def cold_days() -> int:
    try:
        return max(1, int(setting("JOBSCOUT_DIAS_FRIA", "14")))
    except ValueError:
        return 14


class App:
    """Tudo que o servidor precisa, montado uma vez."""

    def __init__(self, folder: Path | None = None, *, background: bool = True) -> None:
        folder = folder or data_dir()
        self.store = Store(folder / "jobscout.db")
        self.hub = Hub()
        self.profile = Profile(folder / "profile.json")
        self.preferences = Preferences(folder / "preferencias.json")
        self.apply_ai_choices()
        self.backend = "http://127.0.0.1:8765/"
        self.assistant = Assistant(self.store, self.hub, self.profile, background=background)
        self.assistant._message_overrides_loader = lambda: self.preferences.load()["mensagens_modelos"]
        self.gmail = Gmail(folder / "gmail_token.json", credentials=self.google_credentials)
        self.avatar = appearance.Avatar(folder / "boneco.json")
        self.poller = Poller(self.gmail, self.check_gmail)
        self.reminders = reminders.Reminders(self.store, self.hub, self.gmail, link=lambda: self.backend)
        self.search = jobsearch.JobSearch(
            self.store, self.hub,
            load=lambda: self.preferences.load()["busca"],
            save=lambda changes: self.preferences.save({"busca": changes}),
            alerts=self.linkedin_alerts,
            profile=self.profile.load,
            fit=self.assistant.rule_fit,
        )
        self.stopping = threading.Event()
        self.extension_seen = 0.0

    def start_cold_check(self) -> None:
        """De hora em hora, propõe marcar como fria a vaga parada (vira rascunho)."""

        def loop() -> None:
            while not self.stopping.wait(10):
                try:
                    self.assistant.check_cold(cold_days())
                except Exception as exc:  # noqa: BLE001 - não derruba o servidor
                    self.hub.activity(f"Verificação de vagas frias falhou: {exc}", "erro")
                if self.stopping.wait(COLD_CHECK_SECONDS - 10):
                    return

        threading.Thread(target=loop, daemon=True).start()

    def google_credentials(self) -> tuple[str, str]:
        prefs = self.preferences.load()
        return prefs["google_cliente"], prefs["google_chave"]

    def apply_ai_choices(self) -> None:
        prefs = self.preferences.load()
        llm.configure(prefs["ia"], prefs["ia_tarefas"], prefs["gemini_chave"])

    def prepare_folder(self, backend: str | None = None) -> dict[str, str]:
        """Cria (ou atualiza) a pasta do JobScout com a extensão e o passo a passo."""
        if backend:
            self.backend = backend
        prefs = self.preferences.load()
        return preferences.prepare(Path(prefs["pasta"]), prefs["nome"], self.backend)

    def folder_state(self) -> dict[str, Any]:
        prefs = self.preferences.load()
        folder = Path(prefs["pasta"])
        return {
            **prefs,
            # A chave fica só no arquivo local; o painel só precisa saber se existe.
            "gemini_chave": bool(prefs["gemini_chave"] or llm.gemini_key()),
            "google_chave": bool(prefs["google_chave"]),
            "extensao": str(folder / preferences.EXTENSION_FOLDER),
            "exportacoes": str(folder / preferences.EXPORT_FOLDER),
            "pronta": (folder / preferences.EXTENSION_FOLDER / "manifest.json").is_file(),
        }

    # Currículo completo, versões por vaga e PDF

    def full_resume(self) -> dict[str, Any]:
        profile = self.profile.load()
        data = profile.get("cv")
        return {
            "cv": data,
            "sugerido": None if data else cv.from_text(profile.get("curriculo") or ""),
            "texto": profile.get("curriculo") or "",
            "perfil": {key: profile.get(key) or "" for key in ("nome", "email", "telefone", "cidade", "estado", "pais", "linkedin", "github", "portfolio")},
            "versoes": self.store.resume_versions(),
        }

    def save_full_resume(self, data: Any) -> dict[str, Any]:
        clean = cv.clean(data)
        self.profile.save({"cv": clean, "curriculo": cv.to_text(clean)})
        self.hub.activity("Currículo completo salvo; anos por skill recalculados.", "ok")
        return self.full_resume()

    def base_resume(self) -> dict[str, Any]:
        profile = self.profile.load()
        return profile.get("cv") or cv.from_text(profile.get("curriculo") or "")

    def create_version(self, job_id: int, use_ai: bool) -> dict[str, Any]:
        job = self.store.job(job_id)
        if job is None:
            raise LookupError(f"Vaga {job_id} não encontrada.")
        lang = cv.language_for(job)
        version = cv.tailor(self.base_resume(), job)
        note = ""
        if use_ai:
            self.hub.activity(f"IA ajustando o resumo do currículo para {job['title'] or 'a vaga'}…", "trabalhando")
            try:
                summary = cv.ai_summary(version, job, lang)
                if summary:
                    version["resumo"] = summary
                    version["alvo"]["resumo_por"] = llm.model_name("curriculo")
            except llm.LLMUnavailable as exc:
                note = f"IA indisponível; mantive o resumo original. {exc}"
        name = cv.custom_label(job) or "CV da vaga"
        version_id = self.store.add_resume_version(job_id, name, lang, version)
        self.store.log("curriculo_versao", f"Versão do currículo para {job['title'] or 'a vaga'}", "painel", job_id=job_id)
        result = self.store.resume_version(version_id)
        if note:
            result["aviso"] = note
        return result

    def export_resume(self, version_id: int | None) -> Path:
        profile = self.profile.load()
        folder = Path(self.folder_state()["exportacoes"]) / "Currículos"
        if version_id:
            version = self.store.resume_version(version_id)
            if version is None:
                raise LookupError(f"Versão {version_id} não encontrada.")
            page = cv.render_html(version["data"], profile, version["lang"])
            target = folder / cv.file_name(profile, version["name"])
        else:
            page = cv.render_html(self.base_resume(), profile, "pt")
            target = folder / cv.file_name(profile)
        cv.to_pdf(page, target)
        if version_id:
            self.store.update_resume_version(version_id, pdf=target.name)
        self.hub.activity(f"PDF do currículo salvo: {target.name}", "ok")
        return target

    def resume_online(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Separado para os testes trocarem a rede."""
        return resume_tools.online(profile)

    def health(self) -> dict[str, Any]:
        """O que está operando: a bolinha do painel fica amarela se algo ligado não responde."""
        items = []
        since = time.time() - self.extension_seen
        if not self.extension_seen:
            items.append({"nome": "Extensão do Chrome", "estado": "aviso", "detalhe": "Ainda não falou com o JobScout desde que ele abriu."})
        elif since > EXTENSION_ALIVE_SECONDS:
            items.append({"nome": "Extensão do Chrome", "estado": "aviso", "detalhe": f"Sem contato há {int(since // 60)} min."})
        else:
            items.append({"nome": "Extensão do Chrome", "estado": "ok", "detalhe": "Conectada."})
        model = llm.model_name("responder")
        if not model:
            items.append({"nome": "IA", "estado": "desligado", "detalhe": "Desligada (só regras)."})
        elif model.startswith("ollama:"):
            installed = llm.ollama_models(timeout=1.5)
            if installed is None:
                items.append({"nome": "IA", "estado": "aviso", "detalhe": "Ollama não está rodando."})
            elif model.split(":", 1)[1] not in installed:
                items.append({"nome": "IA", "estado": "aviso", "detalhe": f"Modelo {model} não baixado."})
            else:
                items.append({"nome": "IA", "estado": "ok", "detalhe": model})
        else:
            items.append({"nome": "IA", "estado": "ok", "detalhe": model})
        gmail = self.gmail.status()
        if not gmail["configurado"] or not gmail["conectado"]:
            items.append({"nome": "Gmail", "estado": "desligado", "detalhe": "Não conectado."})
        elif gmail["erro"]:
            items.append({"nome": "Gmail", "estado": "aviso", "detalhe": gmail["erro"]})
        else:
            items.append({"nome": "Gmail", "estado": "ok", "detalhe": "Verificando e-mails."})
        overall = "aviso" if any(item["estado"] == "aviso" for item in items) else "ok"
        return {"geral": overall, "itens": items}

    def pull_model(self, model: str) -> None:
        """Baixa em segundo plano, avisando o andamento na atividade (de 10 em 10%)."""
        last = {"pct": -10}

        def progress(state: dict[str, Any], status: str) -> None:
            if state["pct"] >= last["pct"] + 10:
                last["pct"] = state["pct"]
                self.hub.activity(f"Baixando {model}: {state['pct']}%", "trabalhando")
                self.hub.publish("ia")

        def run() -> None:
            self.hub.activity(f"Baixando o modelo {model} no Ollama…", "trabalhando")
            try:
                llm.pull_ollama(model, progress)
            except llm.LLMUnavailable as exc:
                self.hub.activity(str(exc), "erro")
            else:
                self.hub.activity(f"Modelo {model} pronto para usar.", "ok")
            self.hub.publish("ia")

        threading.Thread(target=run, daemon=True).start()

    def my_skills(self) -> list[str]:
        return self.assistant.my_skills()

    def check_gmail(self) -> int:
        self.hub.activity("Gmail: procurando e-mails de recrutadores…", "trabalhando")
        try:
            found = self.gmail.fetch_new(self.store.gmail_seen)
        except GmailError as exc:
            self.gmail.last_error = str(exc)
            self.hub.activity(f"Gmail: falhou. {exc}", "erro")
            raise
        self.gmail.last_error = None
        created = 0
        jobs = self.store.jobs()
        for message_id, raw in found:
            parsed = mail.parse_eml(raw)
            verdict = mail.relevance(parsed, jobs)
            if verdict.get("alerta"):
                # Fica para a busca automática, que lê os alertas pela própria consulta.
                self.store.mark_gmail_seen(message_id)
                continue
            if not verdict["recrutamento"]:
                by = "IA" if verdict["origem"] == "llm" else "regras"
                self.hub.activity(f"Gmail: ignorei “{parsed['assunto'][:60]}” — {verdict['motivo']} ({by}).", "info")
            else:
                parsed["relevancia"] = verdict["motivo"]
                payload = mail.build_draft(parsed, jobs, external_id="gmail:" + message_id)
                if self.assistant.intake_message(payload):
                    created += 1
            self.store.mark_gmail_seen(message_id)
        self.gmail.last_check = now()
        self.hub.publish("gmail", novos=created)
        level = "aviso" if created else "ok"
        self.hub.activity(f"Gmail: {len(found)} e-mail(s) novo(s), {created} virou(aram) rascunho.", level)
        return created

    def linkedin_alerts(self) -> list[dict[str, Any]]:
        """E-mails de alerta de vagas do LinkedIn ainda não lidos pela busca (vazio sem Gmail)."""
        if not (self.gmail.configured() and self.gmail.connected()):
            return []
        seen = lambda message_id: self.store.gmail_seen("alerta:" + message_id)  # noqa: E731
        messages = []
        for message_id, raw in self.gmail.fetch_new(seen, limit=20, query=ALERT_QUERY):
            messages.append(mail.parse_eml(raw))
            self.store.mark_gmail_seen("alerta:" + message_id)
        return messages

    def close(self) -> None:
        self.stopping.set()
        self.poller.stop()
        self.reminders.stop()
        self.search.stop()
        self.hub.close()
        self.store.close()


Route = tuple[str, re.Pattern[str], str]
ROUTES: list[Route] = []


def route(method: str, pattern: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def register(handler: Callable[..., Any]) -> Callable[..., Any]:
        ROUTES.append((method, re.compile("^" + pattern + "$"), handler.__name__))
        return handler

    return register


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "JobScout"
    app: App

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._send(403, b"", "text/plain")
            return
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return

    @property
    def app(self) -> App:  # type: ignore[override]
        return self.server.app  # type: ignore[attr-defined]

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        self.query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        path = parsed.path
        if method == "GET" and not path.startswith("/api/"):
            self._static(path)
            return
        if not self._origin_allowed():
            self._send_json(403, {"erro": "Origem não permitida."})
            return
        if (self.headers.get("Origin") or "").startswith("chrome-extension://"):
            self.app.extension_seen = time.time()
        for verb, pattern, name in ROUTES:
            match = pattern.match(path)
            if verb == method and match:
                try:
                    getattr(self, name)(*match.groups())
                except ApiError as exc:
                    self._send_json(exc.status, {"erro": str(exc)})
                except LookupError as exc:
                    self._send_json(404, {"erro": str(exc).strip("'\"")})
                except (DraftError, ValueError) as exc:
                    self._send_json(422, {"erro": str(exc)})
                except GmailError as exc:
                    self._send_json(502, {"erro": str(exc)})
                return
        self._send_json(404, {"erro": "Não encontrado."})

    def _origin_allowed(self) -> bool:
        """Bloqueia sites quaisquer de falarem com o banco local pelo navegador."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin.startswith("chrome-extension://"):
            return True
        host = self.headers.get("Host", "")
        return origin in {f"http://{host}", f"https://{host}"}

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin and origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _static(self, path: str) -> None:
        name = path.lstrip("/") or "index.html"
        if name not in STATIC:
            self._send(404, "Não encontrado".encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._send(200, (WEB / name).read_bytes(), STATIC[name], cache=False)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > MAX_BYTES + 1024 * 64:
            raise ApiError(413, "O envio passa de 8 MB.")
        return self.rfile.read(length) if length > 0 else b""

    def _json(self) -> dict[str, Any]:
        if "application/json" not in self.headers.get("Content-Type", "").lower():
            raise ApiError(415, "Envie JSON.")
        raw = self._body()
        if len(raw) > MAX_JSON:
            raise ApiError(413, "JSON grande demais.")
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "JSON inválido.") from exc
        if not isinstance(data, dict):
            raise ApiError(400, "Esperava um objeto JSON.")
        return data

    def _send(self, status: int, payload: bytes, content_type: str, *, cache: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if not cache:
            self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, encoded, "application/json; charset=utf-8")

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # Estado geral e tempo real

    @route("GET", "/api/estado")
    def state(self) -> None:
        app = self.app
        self._send_json(200, {
            "status": [{"chave": key, "nome": name} for key, name in STATUSES],
            "vagas": app.store.jobs(),
            "rascunhos": app.store.drafts("pendente"),
            "modelos": llm.describe(),
            "gmail": app.gmail.status(),
            "dias_fria": cold_days(),
            "minhas_skills": app.my_skills(),
            "preferencias": app.folder_state(),
            "melhorias_abertas": len(app.store.improvements("aberto")),
            "abas_exportacao": [{"chave": key, "nome": name} for key, (name, _) in exporting.SHEETS.items()],
        })

    @route("GET", "/api/saude")
    def health(self) -> None:
        self._send_json(200, self.app.health())

    @route("GET", "/api/resultados")
    def results(self) -> None:
        self._send_json(200, self.app.assistant.results())

    @route("GET", "/api/atividade")
    def activity(self) -> None:
        self._send_json(200, self.app.hub.recent())

    @route("GET", "/api/stream")
    def stream(self) -> None:
        client = self.app.hub.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 1500\n\n")
            self.wfile.flush()
            while not self.app.stopping.is_set():
                try:
                    message = client.get(timeout=HEARTBEAT)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                if message is None:
                    break
                self.wfile.write(f"data: {message}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.app.hub.unsubscribe(client)
            self.close_connection = True

    # Rascunhos

    @route("GET", "/api/rascunhos")
    def list_drafts(self) -> None:
        state = self.query.get("estado", "pendente")
        if state not in {"pendente", "aprovado", "descartado", "todos"}:
            raise ApiError(400, "Estado inválido.")
        self._send_json(200, self.app.store.drafts(None if state == "todos" else state))

    @route("PATCH", r"/api/rascunhos/(\d+)")
    def edit_draft(self, draft_id: str) -> None:
        self._send_json(200, self.app.assistant.edit(int(draft_id), self._json().get("payload") or {}))

    @route("POST", r"/api/rascunhos/(\d+)/aprovar")
    def approve_draft(self, draft_id: str) -> None:
        payload = self._json().get("payload") if self.headers.get("Content-Length", "0") != "0" else None
        self._send_json(200, self.app.assistant.approve(int(draft_id), payload))

    @route("POST", r"/api/rascunhos/(\d+)/descartar")
    def discard_draft(self, draft_id: str) -> None:
        self._send_json(200, self.app.assistant.discard(int(draft_id)))

    # Vagas

    @route("GET", "/api/vagas")
    def list_jobs(self) -> None:
        self._send_json(200, self.app.store.jobs())

    @route("POST", "/api/vagas")
    def add_job(self) -> None:
        self._send_json(201, self.app.assistant.add_job(self._json()))

    @route("GET", r"/api/vagas/(\d+)")
    def job_detail(self, job_id: str) -> None:
        self._send_json(200, self.app.assistant.detail(int(job_id)))

    @route("PATCH", r"/api/vagas/(\d+)/status")
    def job_status(self, job_id: str) -> None:
        self._send_json(200, self.app.assistant.set_status(int(job_id), str(self._json().get("status", ""))))

    @route("POST", r"/api/vagas/(\d+)/notas")
    def job_note(self, job_id: str) -> None:
        self._send_json(201, self.app.assistant.add_note(int(job_id), str(self._json().get("texto", ""))))

    @route("GET", r"/api/vagas/(\d+)/preparo")
    def job_prepare(self, job_id: str) -> None:
        self._send_json(200, self.app.assistant.prepare(int(job_id)))

    # Empresas

    @route("GET", "/api/empresas")
    def list_companies(self) -> None:
        self._send_json(200, self.app.assistant.companies())

    @route("GET", r"/api/empresas/(\d+)")
    def company_detail(self, company_id: str) -> None:
        self._send_json(200, self.app.assistant.company_detail(int(company_id)))

    @route("PATCH", r"/api/empresas/(\d+)")
    def company_edit(self, company_id: str) -> None:
        self._send_json(200, self.app.assistant.set_company_notes(int(company_id), str(self._json().get("notas", ""))))

    @route("POST", r"/api/empresas/(\d+)/atualizar")
    def company_refresh(self, company_id: str) -> None:
        try:
            self._send_json(200, self.app.assistant.refresh_company(int(company_id)))
        except linkedin_public.PublicPageError as exc:
            raise ApiError(502, str(exc)) from exc

    @route("POST", "/api/frias/verificar")
    def cold_check(self) -> None:
        created = self.app.assistant.check_cold(cold_days())
        self._send_json(200, {"rascunhos": [draft["id"] for draft in created]})

    @route("GET", "/api/movimentos")
    def list_movements(self) -> None:
        limit = min(int(self.query.get("limite", "200") or 200), 1000)
        self._send_json(200, self.app.store.movements(limit))

    @route("GET", "/api/buscar")
    def search(self) -> None:
        self._send_json(200, self.app.assistant.search(self.query.get("q", "")))

    @route("GET", "/api/exportar.csv")
    def export(self) -> None:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "status", "titulo", "empresa", "fonte", "link", "capturada_em", "candidatado_em", "atualizada_em"])
        for job in self.app.store.jobs():
            writer.writerow([
                job["id"], job["status"], job["title"], job["company"], job["source"], job["url"],
                job["captured_at"], job["applied_at"] or "", job["status_at"] or "",
            ])
        payload = ("﻿" + buffer.getvalue()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="candidaturas.csv"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # Preferências, pasta do JobScout e exportação para Excel

    def _panel_only(self) -> None:
        """Mexer em pastas do Windows é coisa do painel, não da extensão."""
        if (self.headers.get("Origin") or "").startswith("chrome-extension://"):
            raise ApiError(403, "Só o painel pode fazer isso.")

    @route("GET", "/api/preferencias")
    def get_preferences(self) -> None:
        self._send_json(200, self.app.folder_state())

    @route("PUT", "/api/preferencias")
    def put_preferences(self) -> None:
        self._panel_only()
        data = self._json()
        before = self.app.preferences.load()
        saved = self.app.preferences.save(
            {key: data[key] for key in ("nome", "pasta", "ia", "ia_tarefas", "gemini_chave", "google_cliente", "google_chave") if key in data}
        )
        self.app.apply_ai_choices()
        if saved["pasta"] != before["pasta"] or saved["nome"] != before["nome"] or not self.app.folder_state()["pronta"]:
            try:
                self.app.prepare_folder()
            except OSError as exc:
                self.app.preferences.save({"pasta": before["pasta"]})
                raise ApiError(422, f"Não consegui usar essa pasta: {exc}") from exc
        self.app.hub.publish("preferencias")
        self._send_json(200, self.app.folder_state())

    @route("GET", "/api/ia")
    def ai_state(self) -> None:
        self._send_json(200, {
            "escolhido": self.app.preferences.load()["ia"],
            "ativo": llm.model_name("responder"),
            "ollama": llm.ollama_models(),
            "tarefas": llm.tasks(),
            "gemini": list(llm.GEMINI_MODELS) if llm.gemini_key() else [],
            "baixando": dict(llm.pulling),
        })

    @route("POST", "/api/ia/baixar")
    def ai_pull(self) -> None:
        self._panel_only()
        model = str(self._json().get("modelo") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._\-/]+(?::[A-Za-z0-9._\-]+)?", model):
            raise ApiError(422, "Nome de modelo inválido. Exemplo: qwen2.5:7b")
        if llm.pulling.get("estado") == "baixando":
            raise ApiError(409, f"Já estou baixando {llm.pulling['modelo']}.")
        if llm.ollama_models() is None:
            raise ApiError(502, "Ollama não está rodando.")
        self.app.pull_model(model)
        self._send_json(202, {"modelo": model})

    @route("POST", "/api/ia/testar")
    def ai_test(self) -> None:
        self._panel_only()
        started = time.monotonic()
        try:
            text = llm.ask_llm("responder", "Responda só com a palavra: pronto", system="Responda em uma palavra.", timeout=180)
        except llm.LLMUnavailable as exc:
            raise ApiError(502, str(exc)) from exc
        self._send_json(200, {"modelo": llm.model_name("responder"), "resposta": text[:80], "segundos": round(time.monotonic() - started, 1)})

    @route("POST", "/api/pasta/preparar")
    def prepare_folder(self) -> None:
        self._panel_only()
        try:
            self._send_json(200, self.app.prepare_folder())
        except OSError as exc:
            raise ApiError(422, f"Não consegui preparar a pasta: {exc}") from exc

    @route("POST", "/api/pasta/abrir")
    def open_folder(self) -> None:
        self._panel_only()
        data = self._json()
        state = self.app.folder_state()
        folder = Path(state["pasta"])
        targets = {"pasta": folder, "extensao": Path(state["extensao"]), "exportacoes": Path(state["exportacoes"])}
        target = targets.get(str(data.get("alvo") or "pasta"))
        if data.get("arquivo"):
            target = Path(str(data["arquivo"]))
        if target is None or not preferences.inside(folder, target) or not target.exists():
            raise ApiError(404, "Esse arquivo não está na pasta do JobScout.")
        preferences.reveal(target)
        self._send_json(200, {"aberto": str(target)})

    @route("POST", "/api/exportar")
    def export_xlsx(self) -> None:
        self._panel_only()
        data = self._json()
        folder = Path(self.app.folder_state()["exportacoes"])
        try:
            target = exporting.export(self.app.assistant, folder, list(data.get("abas") or []), list(data.get("status") or []))
        except OSError as exc:
            raise ApiError(422, f"Não consegui gravar a planilha: {exc}") from exc
        self.app.hub.activity(f"Planilha exportada: {target.name}", "ok")
        self._send_json(201, {"arquivo": str(target), "nome": target.name, "pasta": str(folder)})

    # Extensão

    @route("POST", "/api/extensao/sugestoes")
    def extension_suggestions(self) -> None:
        self._send_json(200, {"sugestoes": self.app.assistant.suggestions(list(self._json().get("campos") or []))})

    @route("POST", "/api/extensao/sugestoes-ia")
    def extension_ai_suggestions(self) -> None:
        data = self._json()
        self._send_json(200, self.app.assistant.ai_suggestions(list(data.get("campos") or []), data.get("vaga")))

    @route("POST", "/api/eventos")
    def extension_event(self) -> None:
        drafts = self.app.assistant.intake(self._json())
        self._send_json(200, {"rascunhos": [draft["id"] for draft in drafts], "pendentes": self.app.store.pending_count()})

    @route("GET", "/api/extensao/insercoes")
    def extension_insertions(self) -> None:
        self._send_json(200, self.app.store.pending_insertions(self.query.get("pagina", "")))

    @route("POST", r"/api/extensao/insercoes/(\d+)")
    def extension_insertion_done(self, insertion_id: str) -> None:
        state = "feito" if self._json().get("ok") else "falhou"
        self.app.store.finish_insertion(int(insertion_id), state)
        if state == "feito":
            self.app.hub.activity("Resposta inserida no formulário. Revise e envie você mesmo.", "ok")
        else:
            self.app.hub.activity("Não achei o campo para inserir a resposta. Copie do painel.", "erro")
        self._send_json(200, {"estado": state})

    @route("GET", "/api/extensao/resumo")
    def extension_summary(self) -> None:
        self._send_json(200, {
            "pendentes": self.app.store.pending_count(),
            "rascunhos": self.app.store.drafts("pendente")[:20],
        })

    @route("GET", "/api/extensao/historico")
    def extension_history(self) -> None:
        self._send_json(200, self.app.assistant.answer_history())

    @route("GET", "/api/falhas")
    def failures(self) -> None:
        self._send_json(200, self.app.store.failures())

    # Currículo: editor, backlog de melhoria, revisão pela IA e perfis na internet

    @route("GET", "/api/melhorias")
    def list_improvements(self) -> None:
        self._send_json(200, self.app.store.improvements())

    @route("POST", "/api/melhorias")
    def add_improvement(self) -> None:
        self._send_json(201, self.app.assistant.add_improvement(self._json()))

    @route("PATCH", r"/api/melhorias/(\d+)")
    def edit_improvement(self, improvement_id: str) -> None:
        self._send_json(200, self.app.assistant.set_improvement(int(improvement_id), self._json()))

    @route("POST", r"/api/melhorias/(\d+)/reprocessar")
    def reprocess_improvement(self, improvement_id: str) -> None:
        self._panel_only()
        self._send_json(200, self.app.assistant.reprocess_improvement(int(improvement_id)))

    @route("GET", "/api/curriculo/completo")
    def get_full_resume(self) -> None:
        self._send_json(200, self.app.full_resume())

    @route("PUT", "/api/curriculo/completo")
    def put_full_resume(self) -> None:
        self._panel_only()
        self._send_json(200, self.app.save_full_resume(self._json().get("cv")))

    @route("POST", "/api/curriculo/completo/do-texto")
    def resume_from_text(self) -> None:
        text = str(self._json().get("texto") or self.app.profile.load().get("curriculo") or "")
        self._send_json(200, cv.from_text(text))

    @route("POST", "/api/curriculo/versoes")
    def create_resume_version(self) -> None:
        self._panel_only()
        data = self._json()
        self._send_json(201, self.app.create_version(int(data.get("vaga_id") or 0), bool(data.get("ia"))))

    @route("GET", r"/api/curriculo/versoes/(\d+)")
    def get_resume_version(self, version_id: str) -> None:
        version = self.app.store.resume_version(int(version_id))
        if version is None:
            raise LookupError(f"Versão {version_id} não encontrada.")
        self._send_json(200, version)

    @route("PUT", r"/api/curriculo/versoes/(\d+)")
    def put_resume_version(self, version_id: str) -> None:
        self._panel_only()
        data = self._json()
        if self.app.store.resume_version(int(version_id)) is None:
            raise LookupError(f"Versão {version_id} não encontrada.")
        fields: dict[str, Any] = {}
        if "dados" in data:
            # Mantém as marcas da versão (mostrar, destaques, alvo) além da estrutura limpa.
            raw = data["dados"] if isinstance(data["dados"], dict) else {}
            clean = cv.clean(raw)
            for key in ("alvo",):
                if isinstance(raw.get(key), dict):
                    clean[key] = raw[key]
            for index, skill in enumerate(clean["habilidades"]):
                source = (raw.get("habilidades") or [])[index] if index < len(raw.get("habilidades") or []) else {}
                skill["mostrar"] = bool(source.get("mostrar", True)) if isinstance(source, dict) else True
                skill["vaga"] = bool(source.get("vaga")) if isinstance(source, dict) else False
            for index, role in enumerate(clean["experiencias"]):
                source = (raw.get("experiencias") or [])[index] if index < len(raw.get("experiencias") or []) else {}
                shown = source.get("mostrar_itens") if isinstance(source, dict) else None
                role["mostrar_itens"] = [bool(item) for item in shown][: len(role["itens"])] if isinstance(shown, list) else [True] * len(role["itens"])
                role["mostrar_itens"] += [True] * (len(role["itens"]) - len(role["mostrar_itens"]))
            fields["data"] = clean
        if "nome" in data:
            fields["name"] = " ".join(str(data["nome"] or "").split())[:120] or "Versão"
        if data.get("idioma") in cv.LABELS:
            fields["lang"] = data["idioma"]
        self.app.store.update_resume_version(int(version_id), **fields)
        self._send_json(200, self.app.store.resume_version(int(version_id)))

    @route("POST", r"/api/curriculo/versoes/(\d+)/remover")
    def delete_resume_version(self, version_id: str) -> None:
        self._panel_only()
        self.app.store.delete_resume_version(int(version_id))
        self._send_json(200, {"removido": int(version_id)})

    @route("GET", "/api/curriculo/previa")
    def resume_preview(self) -> None:
        version_id = int(self.query.get("versao") or 0)
        profile = self.app.profile.load()
        if version_id:
            version = self.app.store.resume_version(version_id)
            if version is None:
                raise LookupError(f"Versão {version_id} não encontrada.")
            page = cv.render_html(version["data"], profile, version["lang"])
        else:
            page = cv.render_html(self.app.base_resume(), profile, "pt")
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

    @route("POST", "/api/curriculo/pdf")
    def resume_pdf(self) -> None:
        self._panel_only()
        try:
            target = self.app.export_resume(int(self._json().get("versao") or 0) or None)
        except RuntimeError as exc:
            raise ApiError(502, str(exc)) from exc
        self._send_json(201, {"arquivo": str(target), "nome": target.name})

    @route("POST", "/api/mensagens/responder")
    def write_reply(self) -> None:
        # Também chamada pela barra do chat na extensão: só escreve texto, não grava nada.
        data = self._json()
        assistant = self.app.assistant
        job = self.app.store.job(int(data["vaga_id"])) if data.get("vaga_id") else None
        if job is None and data.get("contato_id"):
            jobs = self.app.store.contact_jobs(int(data["contato_id"]))
            job = jobs[0] if jobs else None
        if job is None and data.get("conversa"):
            texts = [str(turn.get("texto") or "") for turn in data["conversa"] if isinstance(turn, dict)] + [str(data.get("recrutador") or "")]
            job = replies.match_job(texts, self.app.store.jobs())
        profile = self.app.profile.load()
        prefs = self.app.preferences.load()
        style = prefs["mensagens_estilo_email"] if data.get("canal") == "email" else prefs["mensagens_estilo"]
        self._send_json(200, replies.write(data, profile, as_prompt(profile), job, assistant.message_library(), style))

    # Estilo de comunicação: um para chat (LinkedIn, WhatsApp) e outro para e-mail

    def _style_key(self) -> tuple[str, str]:
        channel = "email" if self.query.get("canal") == "email" else "chat"
        return channel, "mensagens_estilo_email" if channel == "email" else "mensagens_estilo"

    def _style(self) -> dict[str, Any]:
        channel, key = self._style_key()
        custom = self.app.preferences.load()[key]
        return {"canal": channel, "texto": custom or replies.default_style(channel), "padrao": not custom, "limite": replies.MAX_STYLE}

    @route("GET", "/api/mensagens/estilo")
    def message_style(self) -> None:
        self._send_json(200, self._style())

    @route("PUT", "/api/mensagens/estilo")
    def edit_message_style(self) -> None:
        self._panel_only()
        channel, key = self._style_key()
        text = str(self._json().get("texto") or "").strip()
        # Igual ao padrão não precisa ficar gravado: assim ele acompanha as melhorias do JobScout.
        self.app.preferences.save({key: "" if text == replies.default_style(channel) else text})
        self._send_json(200, self._style())

    @route("POST", "/api/mensagens/estilo/restaurar")
    def restore_message_style(self) -> None:
        self._panel_only()
        self.app.preferences.save({self._style_key()[1]: ""})
        self._send_json(200, self._style())

    # Modelos de mensagem (intenções): os padrão vêm prontos; a pessoa edita, desliga ou cria

    @route("GET", "/api/mensagens/modelos")
    def message_models(self) -> None:
        self._send_json(200, self.app.assistant.message_library())

    @route("POST", "/api/mensagens/modelos")
    def create_message_model(self) -> None:
        self._panel_only()
        data = self._json()
        overrides = dict(self.app.preferences.load()["mensagens_modelos"])
        name = str(data.get("nome") or "").strip()
        if not name:
            raise ApiError(422, "Dê um nome ao modelo.")
        key = replies.custom_key(name, set(overrides))
        overrides[key] = {k: data.get(k, "") for k in ("nome", "instrucao", "pt", "en")} | {"ativo": True}
        self.app.preferences.save({"mensagens_modelos": overrides})
        self._send_json(201, next(item for item in self.app.assistant.message_library() if item["chave"] == key))

    @route("PUT", r"/api/mensagens/modelos/([a-z0-9_]+)")
    def edit_message_model(self, key: str) -> None:
        self._panel_only()
        data = self._json()
        library = {item["chave"]: item for item in self.app.assistant.message_library()}
        if key not in library:
            raise LookupError(f"Modelo {key} não encontrado.")
        overrides = dict(self.app.preferences.load()["mensagens_modelos"])
        current = {k: library[key][k] for k in ("nome", "instrucao", "pt", "en", "ativo")}
        overrides[key] = current | {k: data[k] for k in ("nome", "instrucao", "pt", "en", "ativo") if k in data}
        self.app.preferences.save({"mensagens_modelos": overrides})
        self._send_json(200, next(item for item in self.app.assistant.message_library() if item["chave"] == key))

    @route("POST", r"/api/mensagens/modelos/([a-z0-9_]+)/restaurar")
    def restore_message_model(self, key: str) -> None:
        """Padrão volta ao texto original; modelo criado pela pessoa é removido."""
        self._panel_only()
        overrides = dict(self.app.preferences.load()["mensagens_modelos"])
        overrides.pop(key, None)
        self.app.preferences.save({"mensagens_modelos": overrides})
        self._send_json(200, self.app.assistant.message_library())

    # Recrutadores e vínculo com as vagas

    @route("GET", "/api/recrutadores")
    def list_contacts(self) -> None:
        self._send_json(200, self.app.store.contacts())

    @route("POST", "/api/recrutadores")
    def create_contact(self) -> None:
        data = self._json()
        self._send_json(201, self.app.assistant.create_contact(data, int(data["vaga_id"]) if data.get("vaga_id") else None))

    @route("PATCH", r"/api/recrutadores/(\d+)")
    def edit_contact(self, contact_id: str) -> None:
        self._send_json(200, self.app.assistant.update_contact(int(contact_id), self._json()))

    @route("POST", r"/api/vagas/(\d+)/recrutadores")
    def link_job_contact(self, job_id: str) -> None:
        data = self._json()
        if data.get("contato_id"):
            self.app.assistant.link_contact(int(job_id), int(data["contato_id"]))
        else:
            self.app.assistant.create_contact(data.get("novo") or {}, int(job_id))
        self._send_json(200, self.app.store.job_contacts(int(job_id)))

    @route("POST", r"/api/vagas/(\d+)/recrutadores/(\d+)/remover")
    def unlink_job_contact(self, job_id: str, contact_id: str) -> None:
        self.app.assistant.unlink_contact(int(job_id), int(contact_id))
        self._send_json(200, self.app.store.job_contacts(int(job_id)))

    @route("POST", "/api/extensao/chat")
    def chat_context(self) -> None:
        self._send_json(200, self.app.assistant.chat_context(self._json()))

    @route("POST", "/api/extensao/chat/vincular")
    def chat_link(self) -> None:
        """Na barra do chat: "esta conversa é sobre a vaga X" — acha ou cria a pessoa e vincula."""
        data = self._json()
        assistant = self.app.assistant
        contact = assistant.find_contact(str(data.get("nome") or ""), str(data.get("email") or ""), str(data.get("linkedin") or ""), str(data.get("telefone") or ""))
        job_id = int(data.get("vaga_id") or 0)
        if contact is None:
            created = assistant.create_contact({key: data.get(key, "") for key in ("nome", "email", "linkedin", "telefone")}, job_id or None)
            contact_id = created["id"]
        else:
            contact_id = contact["id"]
            if job_id:
                assistant.link_contact(job_id, contact_id)
        self._send_json(200, assistant.contact_detail(contact_id))

    @route("POST", "/api/extensao/chat/abordagem")
    def chat_approach(self) -> None:
        """A extensão lê a conversa aberta: recrutador oferecendo vaga nova vira rascunho de oportunidade."""
        self.app.extension_seen = time.time()
        self._send_json(200, self.app.assistant.chat_approach(self._json()))

    # Encaixe com o perfil, currículo enviado e chat da aba Busca

    @route("POST", r"/api/vagas/(\d+)/encaixe")
    def job_fit(self, job_id: str) -> None:
        self._panel_only()
        try:
            self._send_json(200, self.app.assistant.job_fit(int(job_id)))
        except llm.LLMUnavailable as exc:
            raise ApiError(503, str(exc)) from exc

    @route("POST", r"/api/vagas/(\d+)/curriculo")
    def job_resume(self, job_id: str) -> None:
        """Marca à mão qual currículo foi enviado (quando o site não mostrou o nome do arquivo)."""
        self._panel_only()
        document = str(self._json().get("documento") or "").strip()[:200]
        if self.app.store.job(int(job_id)) is None:
            raise LookupError(f"Vaga {job_id} não encontrada.")
        self.app.store.set_sent(int(job_id), document)
        self.app.hub.publish("vaga", id=int(job_id))
        self._send_json(200, self.app.assistant.detail(int(job_id)))

    @route("GET", "/api/chat")
    def chat_list(self) -> None:
        self._send_json(200, self.app.store.chat_threads())

    @route("GET", r"/api/chat/(\d+)")
    def chat_open(self, thread_id: str) -> None:
        self._send_json(200, self.app.assistant.chat_thread(int(thread_id)))

    @route("POST", "/api/chat")
    def chat_ask(self) -> None:
        self._panel_only()
        data = self._json()
        self._send_json(200, self.app.assistant.chat(int(data["conversa"]) if data.get("conversa") else None, str(data.get("texto") or "")))

    @route("POST", r"/api/chat/(\d+)/remover")
    def chat_remove(self, thread_id: str) -> None:
        self._panel_only()
        self.app.store.delete_chat_thread(int(thread_id))
        self._send_json(200, {"ok": True})

    # Aparência: tema (JSON) e personagem no lugar do boneco

    def _appearance(self) -> dict[str, Any]:
        return {
            "tema": self.app.preferences.load()["tema"], "boneco": self.app.avatar.load(),
            "cores": list(appearance.TOKENS), "modelo_tema": appearance.THEME_TEMPLATE,
        }

    @route("GET", "/api/aparencia")
    def get_appearance(self) -> None:
        self._send_json(200, self._appearance())

    @route("PUT", "/api/aparencia/tema")
    def save_theme(self) -> None:
        self._panel_only()
        self.app.preferences.save({"tema": self._json().get("tema")})
        self._send_json(200, self._appearance())

    @route("POST", "/api/aparencia/tema/restaurar")
    def reset_theme(self) -> None:
        self._panel_only()
        self.app.preferences.save({"tema": None})
        self._send_json(200, self._appearance())

    @route("PUT", "/api/aparencia/boneco")
    def save_avatar(self) -> None:
        self._panel_only()
        self.app.avatar.save(self._json())
        self._send_json(200, self._appearance())

    @route("POST", "/api/aparencia/boneco/restaurar")
    def reset_avatar(self) -> None:
        self._panel_only()
        self.app.avatar.reset()
        self._send_json(200, self._appearance())

    # Etapas do processo e quadro (Kanban) de cada empresa

    @route("GET", r"/api/vagas/(\d+)/etapas")
    def job_stages(self, job_id: str) -> None:
        self._send_json(200, self.app.assistant.stages_view(int(job_id)))

    @route("PUT", r"/api/vagas/(\d+)/etapas")
    def save_job_stages(self, job_id: str) -> None:
        self._panel_only()
        self._send_json(200, self.app.assistant.save_stages(int(job_id), self._json().get("etapas")))

    @route("POST", r"/api/vagas/(\d+)/etapas/mover")
    def move_job_stage(self, job_id: str) -> None:
        self._panel_only()
        self._send_json(200, self.app.assistant.move_to_stage(int(job_id), self._json().get("etapa")))

    @route("GET", "/api/quadros")
    def boards(self) -> None:
        """Empresas com vaga salva, para escolher o quadro no Kanban."""
        counts: dict[str, int] = {}
        for job in self.app.store.jobs():
            if job["company"]:
                key = company_key(job["company"])
                counts[key] = counts.get(key, 0) + 1
        rows = [{"id": row["id"], "nome": row["name"], "vagas": counts[row["key"]], "personalizado": bool(row.get("pipeline"))}
                for row in self.app.store.companies() if row["key"] in counts]
        self._send_json(200, sorted(rows, key=lambda row: fold(row["nome"])))

    @route("GET", r"/api/empresas/(\d+)/quadro")
    def company_board(self, company_id: str) -> None:
        self._send_json(200, self.app.assistant.company_board(int(company_id)))

    @route("PUT", r"/api/empresas/(\d+)/quadro")
    def save_company_board(self, company_id: str) -> None:
        self._panel_only()
        data = self._json()
        self._send_json(200, self.app.assistant.save_company_pipeline(int(company_id), data.get("quadro"), bool(data.get("aplicar"))))

    # Lembretes (cobrar retorno, pedir feedback...) e Google Agenda

    @route("GET", "/api/lembretes")
    def list_reminders(self) -> None:
        states = tuple(self.query.get("estado", "ativo").split(","))
        job_id = int(self.query["vaga"]) if self.query.get("vaga") else None
        self._send_json(200, {
            "lembretes": self.app.store.reminders(job_id, states),
            "vencidos": [row["id"] for row in self.app.reminders.due()],
            "modelos": [{**preset, "quando": reminders.preset_date(preset)} for preset in reminders.PRESETS],
            "agenda": {"conectada": self.app.gmail.calendar_ready(), "google": self.app.gmail.connected(),
                       "configurado": self.app.gmail.configured()},
        })

    @route("POST", "/api/lembretes")
    def create_reminder(self) -> None:
        self._panel_only()
        self._send_json(201, self.app.reminders.create(self._json()))

    @route("POST", r"/api/lembretes/(\d+)/(feito|adiar|parar)")
    def act_reminder(self, reminder_id: str, action: str) -> None:
        self._panel_only()
        self._send_json(200, self.app.reminders.act(int(reminder_id), action))

    # Busca automática de vagas

    def _search_state(self) -> dict[str, Any]:
        config = jobsearch.clean_config(self.app.preferences.load()["busca"])
        following = self.app.search.next_run(config)
        prefs = self.app.preferences.load()
        return {
            "config": config,
            "similares": [term for term in jobsearch.search_terms(config) if term not in config["titulos"]],
            "presets": prefs["busca_presets"],
            "modelos": jobsearch.ACCEPTED_MODES,
            "proxima": following.isoformat(timespec="minutes") if following else None,
            "limites": {"min_horas": jobsearch.MIN_HOURS, "max_horas": jobsearch.MAX_HOURS, "max_titulos": jobsearch.MAX_TERMS,
                        "max_inhire": jobsearch.MAX_TENANTS, "pontuacao_minima": jobsearch.MIN_SCORE},
            "gmail": self.app.gmail.connected(),
        }

    @route("GET", "/api/busca/config")
    def search_config(self) -> None:
        self._send_json(200, self._search_state())

    @route("PUT", "/api/busca/config")
    def save_search_config(self) -> None:
        self._panel_only()
        data = self._json()
        data.pop("ultima", None)
        self.app.preferences.save({"busca": data})
        self._send_json(200, self._search_state())

    @route("PUT", "/api/busca/presets")
    def save_search_presets(self) -> None:
        self._panel_only()
        self.app.preferences.save({"busca_presets": self._json().get("presets") or []})
        self._send_json(200, self._search_state())

    @route("POST", "/api/busca/rodar")
    def run_search(self) -> None:
        self._panel_only()
        try:
            summary = self.app.search.run(manual=True)
        except jobsearch.SearchError as exc:
            raise ApiError(409, str(exc)) from exc
        self._send_json(200, {**summary, **self._search_state()})

    @route("GET", "/api/busca/resultados")
    def search_results(self) -> None:
        self._send_json(200, self.app.store.search_results(self.query.get("estado", "novo")))

    @route("POST", r"/api/busca/resultados/(\d+)/(salvar|descartar)")
    def decide_search_result(self, result_id: str, action: str) -> None:
        self._panel_only()
        result = self.app.store.search_result(int(result_id))
        if result is None:
            raise LookupError(f"Resultado {result_id} não encontrado.")
        if action == "descartar":
            self.app.store.set_search_result(result["id"], "descartado")
            self._send_json(200, {"ok": True})
            return
        existing = self.app.store.job_by_url(result["url"])
        job = existing or self.app.assistant.add_job({
            "url": result["url"], "title": result["title"], "company": result["company"], "location": result["location"],
            "description": result["description"], "work_mode": {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial"}.get(result["work_mode"], ""),
        })
        self.app.store.set_search_result(result["id"], "salvo", job["id"])
        self._send_json(201, job)

    @route("POST", "/api/curriculo/conferir")
    def resume_skill_check(self) -> None:
        """Habilidades das experiências x do perfil, com o que está na tela (ainda sem salvar)."""
        self._send_json(200, cv.skill_check(cv.clean(self._json().get("cv"))))

    @route("POST", "/api/curriculo/melhorar-item")
    def resume_item(self) -> None:
        self._panel_only()
        data = self._json()
        item = str(data.get("item") or "").strip()
        if not item:
            raise ApiError(422, "Escreva o item antes de pedir a melhoria.")
        role = cv.clean({"experiencias": [data.get("experiencia") or {}]})["experiencias"]
        try:
            result = cv.ai_item(item[:500], role[0] if role else {})
        except llm.LLMUnavailable as exc:
            raise ApiError(503, str(exc)) from exc
        self._send_json(200, {**result, "modelo": llm.model_name("curriculo")})

    @route("GET", "/api/curriculo/analise")
    def resume_analysis(self) -> None:
        profile = self.app.profile.load()
        self._send_json(200, {**resume_tools.understood(profile), "pontos": resume_tools.checks(profile)})

    @route("POST", "/api/curriculo/revisar-ia")
    def resume_review(self) -> None:
        self._panel_only()
        self.app.hub.activity("IA revisando o currículo…", "trabalhando")
        try:
            profile = self.app.profile.load()
            result = resume_tools.review(as_prompt(profile), profile)
        except llm.LLMUnavailable as exc:
            raise ApiError(502, f"IA indisponível: {exc}") from exc
        self.app.hub.activity(f"Revisão do currículo pronta: {len(result['pontos'])} ponto(s).", "ok")
        self._send_json(200, result)

    @route("POST", "/api/curriculo/online")
    def resume_online(self) -> None:
        self._panel_only()
        self.app.hub.activity("Buscando seus perfis públicos (GitHub, LinkedIn, site)…", "trabalhando")
        result = self.app.resume_online(self.app.profile.load())
        self.app.hub.activity("Busca dos perfis públicos concluída.", "ok")
        self._send_json(200, result)

    # Perfil e currículo

    @route("GET", "/api/perfil")
    def get_profile(self) -> None:
        self._send_json(200, self.app.profile.load())

    @route("PUT", "/api/perfil")
    def put_profile(self) -> None:
        self._send_json(200, self.app.profile.save(self._json()))

    @route("GET", "/api/perfil/campos")
    def profile_fields(self) -> None:
        self._send_json(200, standard_fields(self.app.profile.load()))

    @route("POST", "/api/analisar")
    def analyze(self) -> None:
        filename, data = _file_from_multipart(self.headers.get("Content-Type", ""), self._body())
        try:
            text = read_resume_bytes(filename, data)
        except ResumeReadError as exc:
            raise ApiError(422, str(exc)) from exc
        groups = list_activities(text)
        tools = list_tools(text)
        total = sum(len(group["atividades"]) for group in groups)
        self._send_json(200, {
            "arquivo": Path(filename).name,
            "modo": "local",
            "total": total,
            "ferramentas": tools,
            "grupos": groups,
            "texto": text[:20000],
        })

    # E-mail

    @route("POST", "/api/emails/importar")
    def import_email(self) -> None:
        filename, data = _file_from_multipart(self.headers.get("Content-Type", ""), self._body())
        if not filename.lower().endswith(".eml"):
            raise ApiError(422, "Use um arquivo .eml.")
        parsed = mail.parse_eml(data)
        payload = mail.build_draft(parsed, self.app.store.jobs())
        draft = self.app.assistant.intake_message(payload, "email")
        if draft is None:
            raise ApiError(409, "Este e-mail já foi importado ou descartado.")
        self._send_json(201, draft)

    @route("GET", "/api/gmail/conectar")
    def gmail_connect(self) -> None:
        self._redirect(self.app.gmail.auth_url(self._gmail_redirect()))

    @route("GET", "/api/gmail/retorno")
    def gmail_callback(self) -> None:
        if "error" in self.query:
            self._redirect("/#config")
            return
        self.app.gmail.finish(self.query.get("code", ""), self.query.get("state", ""), self._gmail_redirect())
        self.app.poller.start()
        self.app.hub.publish("gmail")
        self._redirect("/#config")

    @route("POST", "/api/gmail/verificar")
    def gmail_check(self) -> None:
        self._send_json(200, {"novos": self.app.check_gmail()})

    @route("POST", "/api/gmail/desconectar")
    def gmail_disconnect(self) -> None:
        self.app.gmail.disconnect()
        self.app.hub.publish("gmail")
        self._send_json(200, self.app.gmail.status())

    def _gmail_redirect(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/api/gmail/retorno"


def _file_from_multipart(content_type: str, body: bytes) -> tuple[str, bytes]:
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("Envie o arquivo.")
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    message = message_from_bytes(header + body, policy=policy.default)
    if not message.is_multipart():
        raise ValueError("Envie o arquivo.")
    for part in message.iter_parts():
        filename = part.get_filename()
        if not filename:
            continue
        data = part.get_payload(decode=True)
        if not isinstance(data, bytes) or not data:
            raise ValueError("O arquivo está vazio.")
        return filename, data
    raise ValueError("Nenhum arquivo foi enviado.")


class ReusableServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: App) -> None:
        self.app = app
        super().__init__(address, Handler)

    def server_close(self) -> None:
        self.app.stopping.set()
        self.app.hub.close()
        super().server_close()


def make_server(host: str = "127.0.0.1", port: int = 8765, app: App | None = None) -> ReusableServer:
    app = app or App()
    httpd = ReusableServer((host, port), app)
    if app.gmail.configured() and app.gmail.connected():
        app.poller.start()
    return httpd



def serve_in_background(host: str = "127.0.0.1", port: int = 0, app: App | None = None) -> ReusableServer:
    httpd = make_server(host, port, app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
