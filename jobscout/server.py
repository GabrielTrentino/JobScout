"""Serve o painel e a API só neste computador."""

from __future__ import annotations

import csv
import io
import json
import queue
import re
import threading
from email import message_from_bytes
from email import policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from jobscout import insights, linkedin_public, llm, mail
from jobscout.activities import (
    MAX_BYTES,
    ResumeReadError,
    list_activities,
    list_tools,
    read_resume_bytes,
)
from jobscout.assistant import Assistant, DraftError
from jobscout.config import data_dir, setting
from jobscout.events import Hub
from jobscout.gmail import Gmail, GmailError, Poller
from jobscout.profile import Profile, standard_fields
from jobscout.store import STATUSES, Store, now

WEB = Path(__file__).with_name("web")
STATIC = {
    "index.html": "text/html; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}
MAX_JSON = 2 * 1024 * 1024
HEARTBEAT = 15
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
        self.assistant = Assistant(self.store, self.hub, self.profile, background=background)
        self.gmail = Gmail(folder / "gmail_token.json")
        self.poller = Poller(self.gmail, self.check_gmail)
        self.stopping = threading.Event()

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

    def my_skills(self) -> list[str]:
        profile = self.profile.load()
        text = "\n".join([profile.get("curriculo") or ""] + [s.get("texto", "") for s in profile.get("historias") or []])
        return insights.skills(text)

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
            if not mail.looks_relevant(parsed, jobs):
                self.hub.activity(f"Gmail: ignorei “{parsed['assunto'][:60]}” (não parece recrutamento).", "info")
            else:
                payload = mail.build_draft(parsed, jobs, external_id="gmail:" + message_id)
                if self.assistant.intake_message(payload):
                    created += 1
            self.store.mark_gmail_seen(message_id)
        self.gmail.last_check = now()
        self.hub.publish("gmail", novos=created)
        level = "aviso" if created else "ok"
        self.hub.activity(f"Gmail: {len(found)} e-mail(s) novo(s), {created} virou(aram) rascunho.", level)
        return created

    def close(self) -> None:
        self.stopping.set()
        self.poller.stop()
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
        })

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

    # Extensão

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
