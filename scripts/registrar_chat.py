"""Chat with the registrar system as one logged-in user. The router picks the agent from the user's role.

    python scripts/registrar_chat.py --user 801930214                 # a student
    python scripts/registrar_chat.py --user 801408626                 # an instructor (Professor agent + advising)
    python scripts/registrar_chat.py --user 900000001                 # the registrar administrator
    python scripts/registrar_chat.py --user <TA id> --role student    # a person with two roles picks one
Options: --as-of 2026-11-20T18:00:00Z, --model, --base-url, --verbose, --show-answer. Set LLM_BACKEND=ollama-native
to use Ollama's native API (honors think=false for reasoning models).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from registrar.agents.loop import DEFAULT_BASE_URL, DEFAULT_MODEL, make_client  # noqa: E402
from registrar.agents.router import Router  # noqa: E402
from registrar.db import get_session  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", required=True)
    ap.add_argument("--role", choices=["student", "instructor", "admin"])
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--show-answer", action="store_true")
    ap.add_argument("--question", help="ask one question and exit")
    a = ap.parse_args()
    router = Router(make_client(a.base_url), get_session(), a.user, a.role, a.as_of, a.model, a.verbose)
    print(f"Logged in as {a.user} ({router.role}). Type 'quit' to exit.")
    questions = [a.question] if a.question else iter(lambda: input("\nYou: "), "quit")
    for q in questions:
        r = router.ask(q)
        print(f"\nAgent: {r.reply}")
        if a.show_answer:
            print("answer:", json.dumps(r.answer, default=str))


if __name__ == "__main__":
    main()
