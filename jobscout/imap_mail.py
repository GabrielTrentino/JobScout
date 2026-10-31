"""E-mail por IMAP com senha de app: sem projeto no Google Cloud.

A pessoa gera uma senha de app na conta Google (precisa da verificação em duas etapas) e cola aqui.
Só lê: a caixa abre em modo leitura e BODY.PEEK não marca nada como lido. A senha fica cifrada para o
usuário do Windows (DPAPI), então o arquivo de preferências copiado para outra máquina não serve.
"""

from __future__ import annotations

import base64
import ctypes
import imaplib
import re
import sys
from datetime import date, timedelta
from typing import Any, Callable

from jobscout.config import setting
from jobscout.gmail import ALERT_QUERY, ALERT_SENDERS, QUERY, GmailError

SERVERS = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com", "yahoo.com": "imap.mail.yahoo.com",
           "yahoo.com.br": "imap.mail.yahoo.com", "icloud.com": "imap.mail.me.com"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_char))]


def _dpapi(call: str, payload: bytes) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    source = _Blob(len(payload), ctypes.cast(ctypes.create_string_buffer(payload, len(payload)), ctypes.POINTER(ctypes.c_char)))
    target = _Blob()
    args = (ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target))
    if not getattr(crypt32, call)(*args):
        raise OSError("DPAPI recusou a operação.")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


def protect(secret: str) -> str:
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi("CryptProtectData", raw)).decode("ascii")
    return "b64:" + base64.b64encode(raw).decode("ascii")


def reveal(stored: str) -> str:
    kind, _, body = stored.partition(":")
    raw = base64.b64decode(body or "")
    return (_dpapi("CryptUnprotectData", raw) if kind == "dpapi" else raw).decode("utf-8")


def server_for(email: str) -> str:
    return SERVERS.get(email.rpartition("@")[2].lower(), "")


def _criteria(query: str, gmail: bool) -> list[str]:
    """Consulta do Gmail: direto pelo X-GM-RAW; noutro servidor, pelos critérios básicos do IMAP."""
    if gmail:
        return ["X-GM-RAW", '"' + query.replace('"', "") + '"']
    days = int((re.search(r"newer_than:(\d+)d", query) or [0, 3])[1])
    since = date.today() - timedelta(days=days)
    criteria = ["SINCE", f"{since.day:02d}-{MONTHS[since.month - 1]}-{since.year}"]
    if query == ALERT_QUERY:
        criteria = ["FROM", ALERT_SENDERS[0], *criteria]
    return criteria


class ImapMail:
    """Mesma conversa do Gmail por OAuth: configured, connected, status e fetch_new."""

    def __init__(self, load: Callable[[], dict[str, Any]], save: Callable[[dict[str, Any]], Any],
                 connector: Callable[[str], Any] = imaplib.IMAP4_SSL) -> None:
        self.load = load
        self.save = save
        self.connector = connector
        self.last_check: str | None = None
        self.last_error: str | None = None

    def configured(self) -> bool:
        return True

    def connected(self) -> bool:
        data = self.load()
        return bool(data["imap_email"] and data["imap_senha"])

    def calendar_ready(self) -> bool:
        return False

    def interval_minutes(self) -> int:
        try:
            return max(1, int(setting("JOBSCOUT_GMAIL_INTERVALO_MIN", "5")))
        except ValueError:
            return 5

    def status(self) -> dict[str, Any]:
        return {
            "configurado": True, "conectado": self.connected(), "metodo": "senha_app", "email": self.load()["imap_email"],
            "ultima_verificacao": self.last_check, "erro": self.last_error, "intervalo_min": self.interval_minutes(),
            "agenda": False, "agenda_pendente": False,
        }

    def _open(self, email: str, password: str, host: str) -> Any:
        try:
            client = self.connector(host)
            client.login(email, password)
        except imaplib.IMAP4.error as exc:
            raise GmailError("Login recusado. Confira o e-mail e use uma senha de app (não a senha normal da conta).") from exc
        except OSError as exc:
            raise GmailError(f"Sem conexão com {host}: {exc}") from exc
        client.select("INBOX", readonly=True)
        return client

    def connect(self, email: str, password: str, host: str = "") -> None:
        email = email.strip().lower()
        password = re.sub(r"\s+", "", password)
        host = host.strip() or server_for(email)
        if not email or not password:
            raise ValueError("Informe o e-mail e a senha de app.")
        if not host:
            raise ValueError("Não conheço o servidor desse e-mail; informe o servidor IMAP.")
        self._open(email, password, host).logout()
        self.save({"imap_email": email, "imap_senha": protect(password), "imap_servidor": host})
        self.last_error = None

    def disconnect(self) -> None:
        self.save({"imap_email": "", "imap_senha": "", "imap_servidor": ""})
        self.last_check = None

    def fetch_new(self, seen: Callable[[str], bool], limit: int = 50, query: str = QUERY) -> list[tuple[str, bytes]]:
        data = self.load()
        if not self.connected():
            raise GmailError("E-mail não conectado.")
        host = data["imap_servidor"] or server_for(data["imap_email"])
        client = self._open(data["imap_email"], reveal(data["imap_senha"]), host)
        try:
            status, found = client.uid("SEARCH", None, *_criteria(query, host == "imap.gmail.com"))
            if status != "OK":
                raise GmailError("O servidor recusou a busca de e-mails.")
            uids = (found[0] or b"").split()[-limit:]
            messages = []
            for uid in reversed(uids):
                key = "imap-" + uid.decode("ascii")
                if seen(key):
                    continue
                status, parts = client.uid("FETCH", uid, "(BODY.PEEK[])")
                raw = next((part[1] for part in parts or [] if isinstance(part, tuple)), None)
                if status == "OK" and raw:
                    messages.append((key, raw))
            return messages
        except imaplib.IMAP4.error as exc:
            raise GmailError(f"O servidor de e-mail respondeu com erro: {exc}") from exc
        finally:
            try:
                client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
