"""DocuMentor entry point. Run `python app.py`, then open the address it prints."""
from __future__ import annotations

import logging
import sys

from core.config import Settings
from core.web import LOOPBACK, create_app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

settings = Settings.from_env()
app = create_app(settings)


def main() -> int:
    if settings.host.lower() not in LOOPBACK and not settings.allow_remote:
        print(
            "DocuMentor has no login, so it only runs on this computer by default.\n"
            f"Refusing to listen on {settings.host}. To accept the risk of anyone on the network "
            "using your documents and API quota, set DOCUMENTOR_ALLOW_REMOTE=1.",
            file=sys.stderr,
        )
        return 1
    if not settings.api_key:
        print("Note: GEMINI_API_KEY isn't set, so AI features are off. Copy .env.example to .env.")

    from waitress import serve

    print(f"DocuMentor is running at http://{settings.host}:{settings.port}  (Ctrl+C to stop)")
    serve(app, host=settings.host, port=settings.port, threads=8)
    return 0


if __name__ == "__main__":
    sys.exit(main())
