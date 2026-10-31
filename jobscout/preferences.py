"""Escolhas feitas no painel: o nome do assistente e a pasta do JobScout.

A pasta junta o que a pessoa precisa achar no Windows: a extensão do Chrome para carregar,
as planilhas exportadas e um passo a passo. O banco continua na pasta de dados (JOBSCOUT_DATA_DIR).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from jobscout.config import ROOT

DEFAULT_NAME = "JobScout"
MAX_NAME = 40
EXTENSION_SOURCE = ROOT / "extension"
EXTENSION_FOLDER = "Extensão do Chrome"
EXPORT_FOLDER = "Exportações"
GUIDE_FILE = "Como usar o JobScout.txt"


def default_folder() -> Path:
    return Path.home() / "Documents" / "JobScout"


class Preferences:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, str]:
        stored: dict[str, Any] = {}
        if self.path.is_file():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                stored = {}
        if not isinstance(stored, dict):
            stored = {}
        name = " ".join(str(stored.get("nome") or "").split())[:MAX_NAME]
        folder = str(stored.get("pasta") or "").strip()
        model = str(stored.get("ia") or "").strip()
        tasks = stored.get("ia_tarefas") if isinstance(stored.get("ia_tarefas"), dict) else {}
        return {
            "nome": name or DEFAULT_NAME,
            "pasta": folder or str(default_folder()),
            "ia": model,
            "ia_tarefas": {str(task): str(value) for task, value in tasks.items() if value},
            "gemini_chave": str(stored.get("gemini_chave") or "").strip(),
            "mensagens_modelos": stored.get("mensagens_modelos") if isinstance(stored.get("mensagens_modelos"), dict) else {},
            "mensagens_estilo": str(stored.get("mensagens_estilo") or "") if isinstance(stored.get("mensagens_estilo"), str) else "",
            "mensagens_estilo_email": str(stored.get("mensagens_estilo_email") or "") if isinstance(stored.get("mensagens_estilo_email"), str) else "",
            "busca": stored.get("busca") if isinstance(stored.get("busca"), dict) else {},
            "busca_presets": stored.get("busca_presets") if isinstance(stored.get("busca_presets"), list) else [],
            "google_cliente": str(stored.get("google_cliente") or "").strip(),
            "google_chave": str(stored.get("google_chave") or "").strip(),
            "imap_email": str(stored.get("imap_email") or "").strip(),
            "imap_senha": str(stored.get("imap_senha") or ""),
            "imap_servidor": str(stored.get("imap_servidor") or "").strip(),
            "iniciar_oculto": bool(stored.get("iniciar_oculto")),
            "tema": stored.get("tema") if isinstance(stored.get("tema"), dict) else None,
        }

    def save(self, data: dict[str, Any]) -> dict[str, str]:
        current = self.load()
        if "nome" in data:
            name = " ".join(str(data.get("nome") or "").split())
            if len(name) > MAX_NAME:
                raise ValueError(f"Use um nome de até {MAX_NAME} letras.")
            current["nome"] = name or DEFAULT_NAME
        if "pasta" in data:
            folder = Path(str(data.get("pasta") or "").strip()).expanduser()
            if not str(folder) or not folder.is_absolute():
                raise ValueError("Escolha uma pasta com o caminho completo, como C:\\Users\\voce\\Documents\\JobScout.")
            current["pasta"] = str(folder)
        if "ia" in data:
            from jobscout import llm

            model = str(data.get("ia") or "").strip()
            if not llm.valid_choice(model):
                raise ValueError("Modelo inválido. Use ollama:<modelo> ou gemini:<modelo>.")
            current["ia"] = "" if model == "off" else model
        if "ia_tarefas" in data:
            from jobscout import llm

            tasks = data.get("ia_tarefas") or {}
            if not isinstance(tasks, dict):
                raise ValueError("ia_tarefas deve ser um objeto.")
            chosen = {}
            for task, value in tasks.items():
                value = str(value or "").strip()
                if task not in llm.TASKS:
                    raise ValueError(f"Tarefa desconhecida: {task}")
                if value and not llm.valid_choice(value):
                    raise ValueError(f"Modelo inválido para {task}.")
                if value:
                    chosen[task] = value
            current["ia_tarefas"] = chosen
        if "mensagens_modelos" in data:
            models = data.get("mensagens_modelos")
            if not isinstance(models, dict):
                raise ValueError("mensagens_modelos deve ser um objeto.")
            current["mensagens_modelos"] = models
        for key in ("mensagens_estilo", "mensagens_estilo_email"):
            if key in data:
                style = str(data.get(key) or "").strip()
                if len(style) > 12000:
                    raise ValueError("O estilo de comunicação pode ter até 12.000 caracteres.")
                current[key] = style
        if "busca" in data:
            from jobscout import jobsearch

            current["busca"] = jobsearch.clean_config(data.get("busca"), current.get("busca") or {})
        if "busca_presets" in data:
            from jobscout import jobsearch

            presets = []
            for item in data.get("busca_presets") or []:
                name = " ".join(str(item.get("nome") or "").split())[:60] if isinstance(item, dict) else ""
                if name:
                    config = jobsearch.clean_config(item.get("config"))
                    config.pop("ultima", None)
                    presets.append({"nome": name, "config": config, "auto": bool(item.get("auto"))})
            current["busca_presets"] = presets[:30]
        for key in ("google_cliente", "google_chave", "imap_email", "imap_senha", "imap_servidor"):
            if key in data:
                current[key] = str(data.get(key) or "").strip()
        if "iniciar_oculto" in data:
            current["iniciar_oculto"] = bool(data["iniciar_oculto"])
        if "tema" in data:
            from jobscout import appearance

            current["tema"] = appearance.clean_theme(data["tema"]) if data["tema"] else None
        if "gemini_chave" in data:
            current["gemini_chave"] = str(data.get("gemini_chave") or "").strip()
        self.path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        return current

    def folder(self) -> Path:
        return Path(self.load()["pasta"])


def guide(name: str, folder: Path, backend: str) -> str:
    extension = folder / EXTENSION_FOLDER
    return f"""{name}: como deixar tudo funcionando
{'=' * (len(name) + 31)}

Esta pasta foi criada pelo {name}. Aqui ficam:

  {EXTENSION_FOLDER}\\   a extensão do Chrome (atualizada sempre que o {name} abre)
  {EXPORT_FOLDER}\\       as planilhas que você exportar

1. Abra o {name}
   Ele aparece como um boneco no canto inferior direito da tela.

2. Instale a extensão no Chrome (uma vez só)
   a) Abra chrome://extensions
   b) Ligue o "Modo do desenvolvedor", no canto superior direito
   c) Clique em "Carregar sem compactação" e escolha esta pasta:
      {extension}
   d) Fixe o ícone da extensão na barra do Chrome (ícone de quebra-cabeça)
   Se o {name} mudar de versão, volte em chrome://extensions e clique no botão de recarregar da extensão.

3. Confira o endereço
   No ícone da extensão, o endereço deve ser {backend}

4. Preencha o Perfil
   Menu do boneco > Perfil: dados de contato, respostas rápidas e o currículo.
   É de lá que saem as sugestões de resposta nos formulários.

5. Use normalmente
   Abra vagas no LinkedIn ou na InHire. O {name} registra o que você vê e o que envia
   como rascunhos para você aprovar. Nos formulários, ele sugere respostas ao lado dos campos;
   nada é enviado sem você clicar.

Para exportar: menu do boneco > Config > Exportar para Excel. Os arquivos caem em {EXPORT_FOLDER}\\.
"""


def prepare(folder: Path, name: str, backend: str) -> dict[str, str]:
    """Cria a pasta, copia a extensão e escreve o passo a passo. Pode rodar de novo sem perder nada."""
    folder.mkdir(parents=True, exist_ok=True)
    exports = folder / EXPORT_FOLDER
    exports.mkdir(exist_ok=True)
    extension = folder / EXTENSION_FOLDER
    if EXTENSION_SOURCE.is_dir():
        shutil.copytree(EXTENSION_SOURCE, extension, dirs_exist_ok=True, ignore=shutil.ignore_patterns("tests", "*.test.js"))
    (folder / GUIDE_FILE).write_text(guide(name, folder, backend), encoding="utf-8")
    return {"pasta": str(folder), "extensao": str(extension), "exportacoes": str(exports), "guia": str(folder / GUIDE_FILE)}


def inside(folder: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def reveal(target: Path) -> None:
    """Abre a pasta (ou o arquivo) no Explorer."""
    if sys.platform == "win32":
        os.startfile(str(target))  # noqa: S606 - caminho conferido por quem chama
    else:
        import subprocess

        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])  # noqa: S603
