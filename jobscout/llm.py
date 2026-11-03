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
    "classificar": {"variavel": "JOBSCOUT_LLM_CLASSIFICAR", "privada": True, "nome": "Classificar e-mails"},
    "resumir": {"variavel": "JOBSCOUT_LLM_RESUMIR", "privada": True, "nome": "Resumir e-mails"},
    "responder": {"variavel": "JOBSCOUT_LLM_RESPONDER", "privada": False, "nome": "Perguntas dos formulários"},
    "preparar": {"variavel": "JOBSCOUT_LLM_PREPARAR", "privada": False, "nome": "Preparar entrevista"},
    "curriculo": {"variavel": "JOBSCOUT_LLM_CURRICULO", "privada": False, "nome": "Currículo (revisão e versões por vaga)"},
    # Lê a mensagem do recrutador: conversa privada.
    "mensagem": {"variavel": "JOBSCOUT_LLM_MENSAGEM", "privada": True, "nome": "Respostas a recrutador"},
    "freela": {"variavel": "JOBSCOUT_LLM_FREELA", "privada": False, "nome": "Estimativas de freela"},
    # Lê o histórico (e-mails, respostas, notas): conversa privada.
    "chat": {"variavel": "JOBSCOUT_LLM_CHAT", "privada": True, "nome": "Chat da aba Busca"},
}
GEMINI_MODELS = ("gemini-flash-latest", "gemini-pro-latest")

LOCAL_PROVIDERS = {"ollama"}

RULES = (
    "Use apenas os fatos do perfil e do currículo informados. "
    "Nunca invente experiências, certificações, empresas, datas ou números. "
    "Se faltar informação, escreva [falta: ...] no ponto exato. "
    "Responda no idioma da pergunta, em primeira pessoa, de forma direta."
)


class LLMUnavailable(RuntimeError):
    pass


# Escolhas do painel (Config > IA): o padrão e, se quiser, um modelo por tarefa.
# A variável própria da tarefa no .env ainda ganha de tudo.
_chosen: dict = {"padrao": "", "tarefas": {}, "gemini_chave": ""}


def configure(default: str, per_task: dict[str, str] | None = None, gemini_key: str = "") -> None:
    _chosen["padrao"] = (default or "").strip()
    _chosen["tarefas"] = {task: str(value).strip() for task, value in (per_task or {}).items() if task in TASKS}
    _chosen["gemini_chave"] = (gemini_key or "").strip()


def gemini_key() -> str:
    return setting("JOBSCOUT_GEMINI_API_KEY") or _chosen["gemini_chave"]


def valid_choice(raw: str) -> bool:
    provider, _, model = (raw or "").partition(":")
    return raw in {"", "off"} or (provider.strip().lower() in {"ollama", "gemini"} and bool(model.strip()))


@dataclass(frozen=True)
class Route:
    provider: str
    model: str


def route(task: str) -> Route | None:
    spec = TASKS.get(task)
    if spec is None:
        raise ValueError(f"Tarefa desconhecida: {task}")
    raw = setting(spec["variavel"]) or _chosen["tarefas"].get(task) or _chosen["padrao"] or setting("JOBSCOUT_LLM_PADRAO")
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


def ask_llm(task: str, input: str, *, system: str = RULES, timeout: float = 90, as_json: bool = False) -> str:
    """as_json pede ao modelo um objeto JSON puro (sem texto em volta)."""
    chosen = route(task)
    if chosen is None:
        raise LLMUnavailable(f"Nenhum modelo configurado para {task}.")
    if chosen.provider == "ollama":
        return _ollama(chosen.model or "gemma3:4b", system, input, timeout, as_json)
    return _gemini(chosen.model or "gemini-flash-latest", system, input, timeout, as_json)


def model_name(task: str) -> str:
    chosen = route(task)
    return f"{chosen.provider}:{chosen.model}" if chosen else ""


def tasks() -> list[dict[str, object]]:
    """Cada tarefa com o modelo em uso e de onde vem a escolha (para o Config)."""
    rows = []
    for task, spec in TASKS.items():
        fixed = setting(spec["variavel"])
        chosen = route(task)
        rows.append({
            "tarefa": task,
            "nome": spec["nome"],
            "privada": spec["privada"],
            "escolhido": _chosen["tarefas"].get(task, ""),
            "fixado_no_env": fixed,
            "em_uso": f"{chosen.provider}:{chosen.model}" if chosen else "",
        })
    return rows


# Download de modelo do Ollama em andamento (um por vez).
pulling: dict = {"modelo": "", "pct": 0, "estado": "", "erro": ""}


def pull_ollama(model: str, on_progress=None, timeout: float = 3600) -> None:
    """Baixa um modelo no Ollama, acompanhando o progresso. Levanta LLMUnavailable se falhar."""
    base = setting("JOBSCOUT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    request = Request(
        base + "/api/pull",
        data=json.dumps({"model": model, "stream": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    pulling.update({"modelo": model, "pct": 0, "estado": "baixando", "erro": ""})
    try:
        with urlopen(request, timeout=timeout) as response:
            for raw in response:
                line = json.loads(raw.decode("utf-8") or "{}")
                if line.get("error"):
                    raise LLMUnavailable(str(line["error"]))
                total, done = line.get("total") or 0, line.get("completed") or 0
                if total:
                    pulling["pct"] = int(done * 100 / total)
                if on_progress:
                    on_progress(dict(pulling), line.get("status", ""))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        pulling.update({"estado": "erro", "erro": str(exc)})
        raise LLMUnavailable(f"Não consegui baixar {model}: {exc}") from exc
    except LLMUnavailable as exc:
        pulling.update({"estado": "erro", "erro": str(exc)})
        raise
    pulling.update({"estado": "pronto", "pct": 100})


def ollama_models(timeout: float = 3) -> list[str] | None:
    """Modelos baixados no Ollama deste computador; None se o Ollama não estiver rodando."""
    base = setting("JOBSCOUT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        with urlopen(base + "/api/tags", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    return sorted(str(item.get("name", "")) for item in payload.get("models") or [] if item.get("name"))


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


def _ollama(model: str, system: str, prompt: str, timeout: float, as_json: bool = False) -> str:
    base = setting("JOBSCOUT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    body = {"model": model, "system": system, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}}
    # A janela padrão do Ollama corta prompts longos (estilo de mensagens + perfil + conversa) sem avisar.
    if len(system) + len(prompt) > 12000:
        body["options"]["num_ctx"] = 8192
    if as_json:
        body["format"] = "json"
    payload = _post(base + "/api/generate", body, timeout)
    return str(payload.get("response", "")).strip()


def _gemini(model: str, system: str, prompt: str, timeout: float, as_json: bool = False) -> str:
    key = gemini_key()
    if not key:
        raise LLMUnavailable("Chave do Gemini ausente (Config > IA ou JOBSCOUT_GEMINI_API_KEY).")
    payload = _post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            **({"generationConfig": {"responseMimeType": "application/json"}} if as_json else {}),
        },
        timeout,
        {"x-goog-api-key": key},
    )
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable("Resposta vazia do Gemini.") from exc
    return "".join(str(part.get("text", "")) for part in parts).strip()
