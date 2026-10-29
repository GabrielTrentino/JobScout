"""Camada única de IA: ask_llm(task, input) escolhe o modelo de cada tarefa."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

from jobscout.config import flag, setting

# Tarefas privadas leem e-mails e conversas: só rodam em modelo local,
# a menos que JOBSCOUT_LLM_NUVEM_PRIVADO=sim.
TASKS = {
    "classificar": {"variavel": "JOBSCOUT_LLM_CLASSIFICAR", "privada": True},
    "resumir": {"variavel": "JOBSCOUT_LLM_RESUMIR", "privada": True},
    "responder": {"variavel": "JOBSCOUT_LLM_RESPONDER", "privada": False},
    "preparar": {"variavel": "JOBSCOUT_LLM_PREPARAR", "privada": False},
}

LOCAL_PROVIDERS = {"ollama"}

RULES = (
    "Use apenas os fatos do perfil e do currículo informados. "
    "Nunca invente experiências, certificações, empresas, datas ou números. "
    "Se faltar informação, escreva [falta: ...] no ponto exato. "
    "Responda no idioma da pergunta, em primeira pessoa, de forma direta."
)


class LLMUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Route:
    provider: str
    model: str


def route(task: str) -> Route | None:
    spec = TASKS.get(task)
    if spec is None:
        raise ValueError(f"Tarefa desconhecida: {task}")
    raw = setting(spec["variavel"]) or setting("JOBSCOUT_LLM_PADRAO")
    if not raw or raw.lower() == "off":
        return None
    provider, _, model = raw.partition(":")
    provider = provider.strip().lower()
    if provider not in {"ollama", "gemini"}:
        return None
    if spec["privada"] and provider not in LOCAL_PROVIDERS and not flag("JOBSCOUT_LLM_NUVEM_PRIVADO"):
        return None
    return Route(provider, model.strip())


def available(task: str) -> bool:
    try:
        return route(task) is not None
    except ValueError:
        return False


def describe() -> dict[str, str]:
    result = {}
    for task in TASKS:
        chosen = route(task)
        result[task] = f"{chosen.provider}:{chosen.model}" if chosen else "regras"
    return result


def ask_llm(task: str, input: str, *, system: str = RULES, timeout: float = 90) -> str:
    chosen = route(task)
    if chosen is None:
        raise LLMUnavailable(f"Nenhum modelo configurado para {task}.")
    if chosen.provider == "ollama":
        return _ollama(chosen.model or "gemma4:e4b", system, input, timeout)
    return _gemini(chosen.model or "gemini-flash-latest", system, input, timeout)


def _post(url: str, body: dict, timeout: float, headers: dict[str, str] | None = None) -> dict:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LLMUnavailable(f"Modelo indisponível: {exc}") from exc


def _ollama(model: str, system: str, prompt: str, timeout: float) -> str:
    base = setting("JOBSCOUT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    payload = _post(
        base + "/api/generate",
        {"model": model, "system": system, "prompt": prompt, "stream": False},
        timeout,
    )
    return str(payload.get("response", "")).strip()


def _gemini(model: str, system: str, prompt: str, timeout: float) -> str:
    key = setting("JOBSCOUT_GEMINI_API_KEY")
    if not key:
        raise LLMUnavailable("JOBSCOUT_GEMINI_API_KEY ausente.")
    payload = _post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        },
        timeout,
        {"x-goog-api-key": key},
    )
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable("Resposta vazia do Gemini.") from exc
    return "".join(str(part.get("text", "")) for part in parts).strip()
