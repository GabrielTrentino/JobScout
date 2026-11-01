"""Cotação do dólar para converter a pretensão salarial, com cache de uma hora."""

from __future__ import annotations

import json
import time
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

SOURCES = (
    ("https://economia.awesomeapi.com.br/json/last/USD-BRL", lambda data: float(data["USDBRL"]["bid"])),
    ("https://open.er-api.com/v6/latest/USD", lambda data: float(data["rates"]["BRL"])),
)
CACHE_SECONDS = 3600
_cache: dict[str, Any] = {}


class RateError(RuntimeError):
    pass


def usd_brl(opener: Callable[..., Any] = urlopen) -> dict[str, Any]:
    if _cache.get("em", 0) > time.time() - CACHE_SECONDS:
        return {"usd_brl": _cache["valor"], "fonte": _cache["fonte"]}
    for url, read in SOURCES:
        try:
            with opener(Request(url, headers={"User-Agent": "JobScout"}), timeout=10) as response:
                value = read(json.loads(response.read().decode("utf-8")))
        except (URLError, OSError, ValueError, KeyError, TypeError):
            continue
        if value > 0:
            _cache.update(em=time.time(), valor=value, fonte=url.split("/")[2])
            return {"usd_brl": value, "fonte": _cache["fonte"]}
    raise RateError("Não consegui buscar a cotação do dólar agora.")
