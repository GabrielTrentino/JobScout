"""Lembretes de acompanhamento: cobrar retorno, pedir feedback, agradecer... com ou sem repetição.

Ficam no JobScout (aviso na bolha quando vencem) e, com o Google conectado com permissão de agenda,
viram evento no Google Agenda com a mesma repetição. Ao vencer, o lembrete leva à mensagem pronta
da intenção (aba Mensagens); "Feito" passa para a próxima ocorrência, e a vaga encerrada para tudo.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode

from jobscout.activities import clean_space
from jobscout.config import setting

MAX_COUNT = 30
MAX_EVERY = 90
# Vaga nesses status não precisa mais de cobrança: os lembretes dela param sozinhos.
CLOSED = {"recusada", "fria", "proposta"}

PRESETS: tuple[dict[str, Any], ...] = (
    {"chave": "cobrar_retorno", "nome": "Cobrar retorno", "intent": "cobrar_retorno", "dias": 7, "cada": 7, "vezes": 3,
     "titulo": "Cobrar retorno: {vaga}"},
    {"chave": "pedir_feedback", "nome": "Pedir feedback da entrevista", "intent": "pedir_feedback", "dias": 3, "cada": 5, "vezes": 2,
     "titulo": "Pedir feedback: {vaga}"},
    {"chave": "agradecer_entrevista", "nome": "Agradecer pela entrevista", "intent": "agradecer_entrevista", "dias": 0, "cada": 0, "vezes": 1,
     "titulo": "Agradecer pela entrevista: {vaga}"},
    {"chave": "responder_proposta", "nome": "Responder a proposta", "intent": "", "dias": 2, "cada": 0, "vezes": 1,
     "titulo": "Responder a proposta: {vaga}"},
    {"chave": "livre", "nome": "Outro lembrete", "intent": "", "dias": 1, "cada": 0, "vezes": 1, "titulo": ""},
)


def timezone_name() -> str:
    # O Google Agenda pede o fuso por nome para repetir no horário certo.
    return setting("JOBSCOUT_FUSO", "America/Sao_Paulo")


def _when(raw: Any, default_hour: int = 9) -> datetime:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Escolha a data do lembrete.")
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("Data inválida; use AAAA-MM-DD ou AAAA-MM-DDTHH:MM.") from exc
    if len(text) <= 10:
        value = value.replace(hour=default_hour)
    if value.tzinfo is None:
        value = value.astimezone()
    return value


def clean(data: dict[str, Any], job: dict[str, Any] | None) -> dict[str, Any]:
    """Valida o que veio do painel: título, data, repetição (a cada N dias, M vezes) e intenção."""
    label = " — ".join(part for part in ((job or {}).get("title"), (job or {}).get("company")) if part) or "vaga"
    title = clean_space(str(data.get("titulo") or "")).replace("{vaga}", label)[:160]
    if not title:
        raise ValueError("Dê um título ao lembrete.")
    every = int(data.get("cada_dias") or 0)
    count = int(data.get("vezes") or 1)
    if not 0 <= every <= MAX_EVERY:
        raise ValueError(f"Repita a cada 1 a {MAX_EVERY} dias (0 = não repete).")
    if not 1 <= count <= MAX_COUNT:
        raise ValueError(f"Use de 1 a {MAX_COUNT} vezes.")
    return {
        "job_id": job["id"] if job else None,
        "intent": clean_space(str(data.get("intencao") or ""))[:40],
        "title": title,
        "notes": str(data.get("notas") or "").strip()[:1000],
        "next_at": _when(data.get("quando")).isoformat(timespec="minutes"),
        "every_days": every,
        "remaining": count if every else 1,
    }


def preset_date(preset: dict[str, Any], base: datetime | None = None) -> str:
    base = (base or datetime.now().astimezone()) + timedelta(days=int(preset["dias"]))
    return base.replace(hour=9, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")


def calendar_event(reminder: dict[str, Any], link: str = "") -> dict[str, Any]:
    """Evento do Google Agenda: 30 minutos no horário do lembrete, com a mesma repetição."""
    start = datetime.fromisoformat(reminder["next_at"])
    end = start + timedelta(minutes=30)
    job = " — ".join(part for part in (reminder.get("job_title"), reminder.get("job_company")) if part)
    description = "\n".join(line for line in (
        "Lembrete do JobScout.",
        f"Vaga: {job}" if job else "",
        reminder.get("notes") or "",
        f"Abra o JobScout para escrever a mensagem: {link}" if link else "",
    ) if line)
    event: dict[str, Any] = {
        "summary": reminder["title"],
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": timezone_name()},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone_name()},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]},
        "source": {"title": "JobScout", "url": link or "http://127.0.0.1:8765/"},
    }
    if reminder["every_days"] and reminder["remaining"] > 1:
        event["recurrence"] = [f"RRULE:FREQ=DAILY;INTERVAL={reminder['every_days']};COUNT={reminder['remaining']}"]
    return event


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _rule(reminder: dict[str, Any]) -> str:
    if reminder["every_days"] and reminder["remaining"] > 1:
        return f"RRULE:FREQ=DAILY;INTERVAL={reminder['every_days']};COUNT={reminder['remaining']}"
    return ""


def calendar_link(reminder: dict[str, Any]) -> str:
    """Link que abre o Google Agenda com o evento pronto: um clique em Salvar, sem API nem projeto no Google."""
    start = datetime.fromisoformat(reminder["next_at"])
    fields = {
        "action": "TEMPLATE", "text": reminder["title"], "dates": f"{_utc(start)}/{_utc(start + timedelta(minutes=30))}",
        "details": calendar_event(reminder)["description"], "ctz": timezone_name(),
    }
    if _rule(reminder):
        fields["recur"] = _rule(reminder)
    return "https://calendar.google.com/calendar/render?" + urlencode(fields)


def ics(reminder: dict[str, Any]) -> str:
    """Arquivo .ics para Outlook, Apple e qualquer agenda."""
    start = datetime.fromisoformat(reminder["next_at"])
    escape = lambda text: str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")  # noqa: E731
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobScout//PT", "BEGIN:VEVENT",
        f"UID:jobscout-{reminder['id']}@local", f"DTSTAMP:{_utc(datetime.now().astimezone())}",
        f"DTSTART:{_utc(start)}", f"DTEND:{_utc(start + timedelta(minutes=30))}",
        f"SUMMARY:{escape(reminder['title'])}", f"DESCRIPTION:{escape(calendar_event(reminder)['description'])}",
    ]
    if _rule(reminder):
        lines.append(_rule(reminder))
    lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:PT0M", f"DESCRIPTION:{escape(reminder['title'])}", "END:VALARM", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


class Reminders:
    """Guarda, avisa e espelha no Google Agenda. A agenda é opcional: sem ela, tudo segue local."""

    def __init__(self, store: Any, hub: Any, calendar: Any = None, link: Callable[[], str] | None = None) -> None:
        self.store = store
        self.hub = hub
        self.calendar = calendar
        self.link = link or (lambda: "")
        self._stop = threading.Event()

    def calendar_ready(self) -> bool:
        return bool(self.calendar and self.calendar.calendar_ready())

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        job = self.store.job(int(data["vaga_id"])) if data.get("vaga_id") else None
        if data.get("vaga_id") and job is None:
            raise LookupError(f"Vaga {data['vaga_id']} não encontrada.")
        reminder_id = self.store.add_reminder(clean(data, job))
        self.store.log("lembrete", f"Lembrete: {self.store.reminder(reminder_id)['title']}", "painel", job_id=job["id"] if job else None)
        note = self._push(reminder_id) if data.get("agenda", True) else ""
        self.hub.publish("lembretes")
        result = self.store.reminder(reminder_id)
        if note:
            result["aviso"] = note
        return result

    def _push(self, reminder_id: int) -> str:
        """Cria o evento na agenda; se falhar, o lembrete continua valendo no JobScout."""
        if not self.calendar_ready():
            return ""
        reminder = self.store.reminder(reminder_id)
        try:
            event = self.calendar.create_event(calendar_event(reminder, self.link()))
        except Exception as exc:  # noqa: BLE001 - a agenda é um extra, não pode impedir o lembrete
            return f"Lembrete salvo, mas o Google Agenda recusou: {exc}"
        self.store.update_reminder(reminder_id, calendar_id=event.get("id") or "")
        return ""

    def _drop_event(self, reminder: dict[str, Any]) -> None:
        if reminder.get("calendar_id") and self.calendar_ready():
            try:
                self.calendar.delete_event(reminder["calendar_id"])
            except Exception:  # noqa: BLE001 - o evento pode já ter sido apagado na agenda
                pass

    def act(self, reminder_id: int, action: str) -> dict[str, Any]:
        reminder = self.store.reminder(reminder_id)
        if reminder is None:
            raise LookupError(f"Lembrete {reminder_id} não encontrado.")
        if action == "feito":
            left = reminder["remaining"] - 1
            if reminder["every_days"] and left > 0:
                following = datetime.fromisoformat(reminder["next_at"]) + timedelta(days=reminder["every_days"])
                # Se ficou atrasado, a próxima conta a partir de hoje, sem acumular cobranças.
                while following < datetime.now().astimezone():
                    following += timedelta(days=reminder["every_days"])
                    left -= 1
                if left > 0:
                    self.store.update_reminder(reminder_id, next_at=following.isoformat(timespec="minutes"), remaining=left, notified_at=None)
                else:
                    self.store.update_reminder(reminder_id, state="concluido", remaining=0)
            else:
                # O evento passado fica na agenda como histórico.
                self.store.update_reminder(reminder_id, state="concluido", remaining=0)
        elif action == "adiar":
            later = max(datetime.fromisoformat(reminder["next_at"]), datetime.now().astimezone()) + timedelta(days=1)
            self.store.update_reminder(reminder_id, next_at=later.isoformat(timespec="minutes"), notified_at=None)
            if reminder.get("calendar_id"):
                # O evento acompanha o adiamento: sai o antigo, entra um na data nova, com a repetição que falta.
                self._drop_event(reminder)
                self.store.update_reminder(reminder_id, calendar_id="")
                self._push(reminder_id)
        elif action == "parar":
            self.store.update_reminder(reminder_id, state="parado")
            self._drop_event(reminder)
        else:
            raise ValueError("Ação inválida: use feito, adiar ou parar.")
        self.hub.publish("lembretes")
        return self.store.reminder(reminder_id)

    def sync_stages(self, job_id: int, stages: list[dict[str, Any]]) -> None:
        """Etapa com data marcada vira lembrete (e evento, com a agenda ligada) na hora marcada."""
        now_at = datetime.now().astimezone()
        current = {row["intent"]: row for row in self.store.reminders(job_id) if row["intent"].startswith("etapa:")}
        wanted = {}
        for stage in stages:
            if not stage.get("scheduled_at") or stage["state"] in {"feita", "pulada"}:
                continue
            try:
                moment = _when(stage["scheduled_at"])
            except ValueError:
                continue
            if moment > now_at:
                wanted[f"etapa:{stage['name']}"[:40]] = (stage["name"], moment.isoformat(timespec="minutes"))
        for key, row in current.items():
            if key not in wanted or wanted[key][1] != row["next_at"]:
                self.store.update_reminder(row["id"], state="parado")
                self._drop_event(row)
                current[key] = None
        for key, (name, moment) in wanted.items():
            if not current.get(key):
                self.create({"vaga_id": job_id, "titulo": f"{name}: {{vaga}}", "quando": moment, "intencao": key, "cada_dias": 0, "vezes": 1})

    def stop_for_job(self, job_id: int, why: str) -> int:
        stopped = 0
        for reminder in self.store.reminders(job_id):
            self.store.update_reminder(reminder["id"], state="parado")
            self._drop_event(reminder)
            stopped += 1
        if stopped:
            self.store.log("lembrete", f"{stopped} lembrete(s) parado(s): {why}", "jobscout", job_id=job_id)
            self.hub.publish("lembretes")
        return stopped

    def due(self) -> list[dict[str, Any]]:
        moment = datetime.now().astimezone()
        return [r for r in self.store.reminders() if datetime.fromisoformat(r["next_at"]) <= moment]

    def check(self) -> list[dict[str, Any]]:
        """Avisa uma vez cada lembrete que venceu; vaga encerrada encerra os lembretes dela."""
        warned = []
        for reminder in self.due():
            if reminder.get("job_status") in CLOSED:
                self.stop_for_job(reminder["job_id"], f"vaga em {reminder['job_status']}")
                continue
            if reminder.get("notified_at"):
                continue
            self.store.update_reminder(reminder["id"], notified_at=datetime.now().astimezone().isoformat(timespec="seconds"))
            self.hub.activity(f"Lembrete: {reminder['title']}", "aviso", lembrete=reminder["id"])
            warned.append(reminder)
        if warned:
            self.hub.publish("lembretes")
        return warned

    def start(self, every_seconds: int = 60) -> None:
        def loop() -> None:
            while not self._stop.wait(every_seconds):
                try:
                    self.check()
                except Exception as exc:  # noqa: BLE001 - não derruba o servidor
                    self.hub.activity(f"Lembretes: falhou. {exc}", "erro")

        threading.Thread(target=loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
