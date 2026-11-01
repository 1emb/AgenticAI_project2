"""Start the web chat UI for the registrar agent.

    python scripts/ui.py                       # http://127.0.0.1:8080
    python scripts/ui.py --port 9000 --reload  # another port; reload on code changes

From a laptop, forward the port first: ssh -L 8080:localhost:8080 <this host>, then open http://localhost:8080.
Needs Postgres (./db/start.sh) and the vLLM server (scripts/serve_llm.sh) running.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--reload", action="store_true", help="restart when the code changes (development)")
    args = ap.parse_args()
    uvicorn.run("registrar.ui.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
