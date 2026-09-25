"""Abre a tela inicial no navegador."""

from __future__ import annotations

import argparse
import threading
import webbrowser

from jobscout.server import make_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Abre a tela inicial do JobScout.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    last_error: OSError | None = None
    httpd = None
    bound = args.port
    for candidate in range(args.port, args.port + 10):
        try:
            httpd = make_server(args.host, candidate)
            bound = candidate
            break
        except OSError as exc:
            last_error = exc
    if httpd is None:
        raise SystemExit(f"jobscout: não consegui abrir a porta {args.port}. {last_error}")
    url = f"http://{args.host}:{bound}/"
    print(f"JobScout em {url}")
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nJobScout encerrado.")
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()
