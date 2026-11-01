"""Abre o JobScout: overlay suspenso no canto direito, ou o painel no navegador."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from urllib.error import URLError
from urllib.request import Request, urlopen

from jobscout import overlay, tray
from jobscout.config import data_dir
from jobscout.server import App, make_server


def _already_running(host: str, port: int) -> bool:
    """Com o JobScout nos ícones ocultos, abrir de novo só traz a janela de volta."""
    request = Request(f"http://{host}:{port}/api/janela/mostrar", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=1.5) as response:
            return b"jobscout" in response.read()
    except (URLError, OSError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Abre o JobScout.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--navegador", action="store_true", help="abre o painel no navegador em vez do overlay")
    parser.add_argument("--no-browser", action="store_true", help="só o servidor, sem janela")
    args = parser.parse_args()
    if not args.no_browser and not args.navegador and _already_running(args.host, args.port):
        print("O JobScout já está aberto: mostrei a janela dele.")
        return
    app = App()
    last_error: OSError | None = None
    httpd = None
    bound = args.port
    for candidate in range(args.port, args.port + 10):
        try:
            httpd = make_server(args.host, candidate, app)
            bound = candidate
            break
        except OSError as exc:
            last_error = exc
    if httpd is None:
        app.close()
        raise SystemExit(f"jobscout: não consegui abrir a porta {args.port}. {last_error}")
    url = f"http://{args.host}:{bound}/"
    print(f"JobScout em {url}")
    print(f"Dados em {data_dir()}")
    if bound != 8765:
        print(f"Aviso: a extensão procura a porta 8765. Ajuste o endereço no popup dela para {url}")
    try:
        prepared = app.prepare_folder(url)
        print(f"Pasta do JobScout em {prepared['pasta']}")
    except OSError as exc:
        print(f"Aviso: não consegui preparar a pasta do JobScout. {exc}")
    app.hub.activity("JobScout ligado. Aguardando vagas, formulários e e-mails.", "ok")
    app.start_cold_check()
    app.reminders.start()
    app.search.start()

    use_overlay = not args.navegador and not args.no_browser and overlay.available()
    if not args.navegador and not args.no_browser and not use_overlay:
        print("Aviso: pywebview não instalado; abrindo no navegador. Instale com: pip install pywebview")
    try:
        if use_overlay:
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            tray.hide_console()
            prefs = app.preferences.load()
            overlay.run(
                url, on_closed=lambda: None, icon=data_dir() / "jobscout.ico", hidden=prefs["iniciar_oculto"], name=prefs["nome"],
                on_bridge=lambda bridge: setattr(app, "show_window", bridge.mostrar),
            )
        else:
            if not args.no_browser:
                threading.Timer(0.3, lambda: webbrowser.open(url)).start()
            httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nJobScout encerrado.")
        httpd.shutdown()
        httpd.server_close()
        app.close()


if __name__ == "__main__":
    main()
