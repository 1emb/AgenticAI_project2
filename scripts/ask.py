"""Ask the registrar agent one question as a given student and print the full trace.

    python scripts/ask.py --uid 800260544 "Who teaches CS 2230 this fall?"
    python scripts/ask.py --uid 800260544 --as-of 2026-12-20T18:00Z --intent who_teaches "..."   # skip the classifier
    python scripts/ask.py --case stu-prerequisites-001                                          # run a test case
    python scripts/ask.py --uid 800260544 --no-reply "..."                                      # skip the English reply (one LLM call fewer)

Needs Postgres (./db/start.sh) and the vLLM server (scripts/serve_llm.sh) running. Every question is appended to runs/chat.jsonl
(scripts/review.py summarises it) unless --no-log is given.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.agent.llm import Client, LLMError  # noqa: E402
from registrar.agent.pipeline import answer_question  # noqa: E402
from registrar.agent.reply import write_reply  # noqa: E402
from registrar.chatlog import record  # noqa: E402
from registrar.db import DATABASE_URL  # noqa: E402
from registrar.testset.common import DEFAULT_AS_OF, Encoder, connect  # noqa: E402


def parse_clock(s: str | None) -> datetime:
    if not s:
        return DEFAULT_AS_OF
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load_case(case_id: str) -> dict:
    persona = {"stu": "student", "prof": "professor"}[case_id.split("-")[0]]
    with open(Path(__file__).resolve().parent.parent / "data" / "testset" / persona / "cases.jsonl") as f:
        for line in f:
            c = json.loads(line)
            if c["id"] == case_id:
                return c
    raise SystemExit(f"no case {case_id}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--uid", help="the authenticated student's university id")
    ap.add_argument("--as-of", help="simulated clock, ISO 8601 (default 2026-11-20T18:00Z)")
    ap.add_argument("--intent", help="skip the classifier and use this intent")
    ap.add_argument("--case", help="run this test case's question (and print its expected answer)")
    ap.add_argument("--sql", action="store_true", help="also print the SQL that was run")
    ap.add_argument("--no-reply", action="store_true", help="do not write the English reply (stage 5)")
    ap.add_argument("--llm-reply", action="store_true", help="render the reply with the model instead of the deterministic writer (comparison only)")
    ap.add_argument("--no-log", action="store_true", help="do not append the question to runs/chat.jsonl")
    args = ap.parse_args()

    expected = None
    if args.case:
        c = load_case(args.case)
        args.question, args.uid, args.as_of = args.question or c["question"], c["student"]["university_id"], c["as_of"]
        expected = c["answer"]
    if not args.question or not args.uid:
        ap.error("a question and --uid are required (or --case)")

    llm = Client()
    try:
        llm.ping()
    except LLMError as e:
        raise SystemExit(f"LLM server: {e}\nstart it with scripts/serve_llm.sh")
    with connect(DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")) as conn:
        t = answer_question(conn, llm, args.question, args.uid, parse_clock(args.as_of), intent_override=args.intent)
    if not args.no_reply:
        write_reply(llm, t, mode="llm" if args.llm_reply else "render")
    if not args.no_log:
        record(t, "ask.py")
    d = t.to_dict()
    if not args.sql:
        d.pop("sql")
    if expected is not None:
        d["expected_answer"] = expected
    print(json.dumps(d, cls=Encoder, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
