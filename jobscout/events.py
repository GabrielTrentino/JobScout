"""Empurra avisos ao painel aberto (Server-Sent Events)."""

from __future__ import annotations

import json
import queue
import threading
from collections import deque
from datetime import datetime
from typing import Any


LEVELS = {"info", "ok", "aviso", "erro", "trabalhando"}


class Hub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[queue.Queue[str | None]] = []
        self._recent: deque[dict[str, Any]] = deque(maxlen=150)
        self._counter = 0

    def activity(self, text: str, level: str = "info", **data: Any) -> None:
        """Conta ao overlay o que está sendo feito, ou por que algo foi ignorado."""
        with self._lock:
            self._counter += 1
            item = {
                "id": self._counter,
                "em": datetime.now().astimezone().isoformat(timespec="seconds"),
                "texto": text,
                "nivel": level if level in LEVELS else "info",
                **data,
            }
            self._recent.append(item)
        self.publish("atividade", item=item)

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._recent))

    def subscribe(self) -> queue.Queue[str | None]:
        client: queue.Queue[str | None] = queue.Queue(maxsize=200)
        with self._lock:
            self._clients.append(client)
        return client

    def unsubscribe(self, client: queue.Queue[str | None]) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def publish(self, kind: str, **data: Any) -> None:
        message = json.dumps({"tipo": kind, **data}, ensure_ascii=False)
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.put_nowait(message)
            except queue.Full:
                self.unsubscribe(client)

    def close(self) -> None:
        with self._lock:
            clients, self._clients = self._clients, []
        for client in clients:
            try:
                client.put_nowait(None)
            except queue.Full:
                pass
