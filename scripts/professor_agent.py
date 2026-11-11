"""Chat with the Professor agent as one instructor, at a chosen clock.

    python scripts/professor_agent.py --professor 801408626 --verbose
    python scripts/professor_agent.py --professor 801408626 --as-of 2026-12-20T18:00:00Z --show-answer

The model endpoint comes from LLM_BASE_URL / LLM_MODEL (.env), default Ollama with qwen3-coder:30b.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.agents.loop import DEFAULT_BASE_URL, DEFAULT_MODEL, make_client  # noqa: E402
from registrar.agents.professor import ProfessorAgent  # noqa: E402
from registrar.db import get_session  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--professor", required=True, help="university_id of the logged-in instructor")
    ap.add_argument("--as-of", default=None, help="ISO clock, e.g. 2026-11-20T18:00:00Z (default: now)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--verbose", action="store_true", help="print every tool call")
    ap.add_argument("--show-answer", action="store_true", help="print the JSON answer the grader would see")
    args = ap.parse_args()

    session = get_session()
    agent = ProfessorAgent(make_client(args.base_url), session, args.professor, args.as_of, model=args.model,
                         verbose=args.verbose)
    t = agent.tools
    print(f"Professor agent for {t.person.first_name} {t.person.last_name} ({t.department.name}, {t.instructor.rank}); "
          f"clock {agent.calendar.as_of:%Y-%m-%d %H:%M} UTC, current term {agent.calendar.current().name}. "
          "Type 'quit' to exit.\n")
    try:
        while True:
            question = input("You: ").strip()
            if question.lower() in ("quit", "exit"):
                break
            if not question:
                continue
            result = agent.ask(question)
            print(f"\nAgent: {result.reply}\n")
            if args.show_answer:
                print("answer:", json.dumps(result.answer, indent=2), "\n")
    except (EOFError, KeyboardInterrupt):
        print()
    finally:
        session.close()


if __name__ == "__main__":
    main()
