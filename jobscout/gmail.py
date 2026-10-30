"""Google no próprio computador: Gmail só leitura e eventos do Google Agenda (lembretes), num OAuth só."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from jobscout.config import setting

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
# Só eventos (criar e apagar os lembretes); não lê nem mexe no resto da agenda.
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
SCOPE = f"{GMAIL_SCOPE} {CALENDAR_SCOPE}"
CALENDAR_API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
# Alertas de vagas do LinkedIn: vão para a busca automática, não para os rascunhos de recrutador.
ALERT_SENDERS = ("jobalerts-noreply@linkedin.com", "jobs-listings@linkedin.com", "jobs-noreply@linkedin.com")
ALERT_QUERY = "from:(" + " OR ".join(ALERT_SENDERS) + ") newer_than:7d"
QUERY = "newer_than:3d -category:promotions -category:social"


class GmailError(RuntimeError):
    pass


class Gmail:
    def __init__(self, token_path: Path, opener: Callable[..., Any] = urlopen,
                 credentials: Callable[[], tuple[str, str]] | None = None) -> None:
        self.token_path = token_path
        self._open = opener
        # Cliente OAuth salvo em Config; sem ele, vale o do .env.
        self._credentials = credentials or (lambda: ("", ""))
        self._pending: dict[str, str] = {}
        self._lock = threading.Lock()
        self.last_check: str | None = None
        self.last_error: str | None = None

    @property
    def client_id(self) -> str:
        return self._credentials()[0] or setting("JOBSCOUT_GMAIL_CLIENT_ID")

    @property
    def client_secret(self) -> str:
        return self._credentials()[1] or setting("JOBSCOUT_GMAIL_CLIENT_SECRET")

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def connected(self) -> bool:
        return self.token_path.is_file()

    def status(self) -> dict[str, Any]:
        return {
            "configurado": self.configured(),
            "conectado": self.connected(),
            "ultima_verificacao": self.last_check,
            "erro": self.last_error,
            "intervalo_min": self.interval_minutes(),
            "agenda": self.calendar_ready(),
            "agenda_pendente": self.connected() and not self.calendar_ready(),
        }

    def granted(self) -> set[str]:
        if not self.connected():
            return set()
        try:
            token = json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        # Tokens antigos não guardavam o escopo: eram só do Gmail.
        return set(str(token.get("scope") or GMAIL_SCOPE).split())

    def calendar_ready(self) -> bool:
        return CALENDAR_SCOPE in self.granted()

    def interval_minutes(self) -> int:
        try:
            return max(1, int(setting("JOBSCOUT_GMAIL_INTERVALO_MIN", "5")))
        except ValueError:
            return 5

    def auth_url(self, redirect_uri: str) -> str:
        if not self.configured():
            raise GmailError("Preencha o ID e a chave do cliente do Google em Config > Gmail.")
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        with self._lock:
            self._pending[state] = verifier
        return AUTH_URL + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })

    def finish(self, code: str, state: str, redirect_uri: str) -> None:
        with self._lock:
            verifier = self._pending.pop(state, None)
        if verifier is None:
            raise GmailError("A autorização expirou. Tente conectar de novo.")
        token = self._token_request({
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        })
        if "refresh_token" not in token:
            raise GmailError("O Google não devolveu refresh_token.")
        self._save(token)

    def disconnect(self) -> None:
        if self.token_path.is_file():
            self.token_path.unlink()

    def _save(self, token: dict[str, Any]) -> None:
        token["expires_at"] = time.time() + int(token.get("expires_in", 3600)) - 60
        self.token_path.write_text(json.dumps(token), encoding="utf-8")

    def _token_request(self, fields: dict[str, str]) -> dict[str, Any]:
        request = Request(
            TOKEN_URL,
            data=urlencode(fields).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self._open(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GmailError(f"O Google recusou o token ({exc.code}).") from exc
        except (URLError, OSError) as exc:
            raise GmailError(f"Sem conexão com o Google: {exc}") from exc

    def _access_token(self) -> str:
        if not self.connected():
            raise GmailError("Gmail não conectado.")
        token = json.loads(self.token_path.read_text(encoding="utf-8"))
        if token.get("expires_at", 0) > time.time() and token.get("access_token"):
            return token["access_token"]
        fresh = self._token_request({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        })
        fresh.setdefault("refresh_token", token["refresh_token"])
        self._save(fresh)
        return fresh["access_token"]

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = API + path + ("?" + urlencode(params) if params else "")
        request = Request(url, headers={"Authorization": "Bearer " + self._access_token()})
        try:
            with self._open(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GmailError(f"Gmail respondeu {exc.code}.") from exc
        except (URLError, OSError) as exc:
            raise GmailError(f"Sem conexão com o Gmail: {exc}") from exc

    def fetch_new(self, seen: Callable[[str], bool], limit: int = 50, query: str = QUERY) -> list[tuple[str, bytes]]:
        """Devolve (id, bytes .eml) dos e-mails recentes que ainda não foram vistos."""
        listing = self._get("/messages", {"q": query, "maxResults": limit})
        found = []
        for item in listing.get("messages", []):
            message_id = item["id"]
            if seen(message_id):
                continue
            raw = self._get(f"/messages/{message_id}", {"format": "raw"})["raw"]
            found.append((message_id, base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))))
        return found


class Poller:
    """Verifica o Gmail a cada poucos minutos, numa thread de fundo."""

    def __init__(self, gmail: Gmail, check: Callable[[], int]) -> None:
        self.gmail = gmail
        self.check = check
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.gmail.configured() and self.gmail.connected():
                try:
                    self.check()
                except GmailError:
                    pass
            self._stop.wait(self.gmail.interval_minutes() * 60)

    # Google Agenda (lembretes)

    def _send(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": "Bearer " + self._access_token()}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self._open(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except HTTPError as exc:
            if exc.code == 403:
                raise GmailError("O Google não deu permissão de agenda. Desconecte e conecte o Google de novo.") from exc
            raise GmailError(f"Google Agenda respondeu {exc.code}.") from exc
        except (URLError, OSError) as exc:
            raise GmailError(f"Sem conexão com o Google Agenda: {exc}") from exc

    def create_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if not self.calendar_ready():
            raise GmailError("Conecte o Google com a permissão de agenda.")
        return self._send("POST", CALENDAR_API, event)

    def delete_event(self, event_id: str) -> None:
        self._send("DELETE", f"{CALENDAR_API}/{event_id}")
