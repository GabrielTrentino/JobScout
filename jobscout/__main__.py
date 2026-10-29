"""Abre o JobScout: overlay suspenso no canto direito, ou o painel no navegador."""

from __future__ import annotations

import argparse
import threading
import webbrowser

from jobscout import overlay
from jobscout.config import data_dir
from jobscout.server import App, make_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Abre o JobScout.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--navegador", action="store_true", help="abre o painel no navegador em vez do overlay")
    parser.add_argument("--no-browser", action="store_true", help="só o servidor, sem janela")
    args = parser.parse_args()
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
    app.hub.activity("JobScout ligado. Aguardando vagas, formulários e e-mails.", "ok")
    app.start_cold_check()

    use_overlay = not args.navegador and not args.no_browser and overlay.available()
    if not args.navegador and not args.no_browser and not use_overlay:
        print("Aviso: pywebview não instalado; abrindo no navegador. Instale com: pip install pywebview")
    try:
        if use_overlay:
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            overlay.run(url, on_closed=lambda: None)
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
