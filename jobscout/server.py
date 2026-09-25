"""Serve a tela inicial só neste computador."""

from __future__ import annotations

import json
import threading
from email import message_from_bytes
from email import policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from jobscout.activities import MAX_BYTES, ResumeReadError, list_activities, read_resume_bytes

PAGE = Path(__file__).with_name("web") / "index.html"


class Handler(BaseHTTPRequestHandler):
    server_version = "JobScout"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/", "/index.html"}:
            self._send(404, b"Nao encontrado", "text/plain; charset=utf-8")
            return
        self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/analisar":
            self._send_json(404, {"erro": "Não encontrado."})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > MAX_BYTES + 1024 * 64:
            self._send_json(413, {"erro": "O arquivo passa de 8 MB."})
            return
        body = self.rfile.read(length)
        try:
            filename, data = _file_from_multipart(self.headers.get("Content-Type", ""), body)
            text = read_resume_bytes(filename, data)
        except ResumeReadError as exc:
            self._send_json(422, {"erro": str(exc)})
            return
        except ValueError as exc:
            self._send_json(400, {"erro": str(exc)})
            return
        groups = list_activities(text)
        total = sum(len(group["atividades"]) for group in groups)
        self._send_json(
            200,
            {
                "arquivo": Path(filename).name,
                "modo": "local",
                "total": total,
                "grupos": groups,
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, encoded, "application/json; charset=utf-8")


def _file_from_multipart(content_type: str, body: bytes) -> tuple[str, bytes]:
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("Envie o currículo como arquivo.")
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    message = message_from_bytes(header + body, policy=policy.default)
    if not message.is_multipart():
        raise ValueError("Envie o currículo como arquivo.")
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


def make_server(host: str = "127.0.0.1", port: int = 8765) -> ReusableServer:
    return ReusableServer((host, port), Handler)


def serve_in_background(host: str = "127.0.0.1", port: int = 0) -> ReusableServer:
    httpd = make_server(host, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
