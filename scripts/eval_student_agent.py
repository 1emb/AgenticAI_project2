"""Grade the Student agent against data/testset/student/cases.jsonl with a real model.

    python scripts/eval_student_agent.py                         # all 152 cases, question wording only
    python scripts/eval_student_agent.py --limit 20              # quick smoke run
    python scripts/eval_student_agent.py --intent access_denied --intent access_partial
    python scripts/eval_student_agent.py --paraphrases           # also run both paraphrases (456 runs)
    python scripts/eval_student_agent.py --id stu-capacity-002 --verbose

Each run uses a fresh agent set to the case's student and clock. The JSON answer is graded with the contract in
data/testset/README.md (registrar/eval/grader.py). Every run is written to runs/<file>.jsonl for later inspection.
"""
import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from registrar.agents.calendar import Calendar  # noqa: E402
from registrar.agents.common import plain  # noqa: E402
from registrar.agents.loop import DEFAULT_BASE_URL, DEFAULT_MODEL, make_client  # noqa: E402
from registrar.agents.student import StudentAgent  # noqa: E402
from registrar.db import get_session  # noqa: E402
from registrar.eval.grader import grade  # noqa: E402


def unanswerable_term(case: dict, question: str, session) -> bool:
    """True when the question names no term at all, yet the ground truth is a term other than the current one
    (e.g. 'When does CRN 10089 meet?' graded against Spring 2027 at a Fall 2026 clock). CRNs repeat across terms,
    so no agent can tell which term was meant; these runs are reported separately."""
    s = case["slots"]
    if "term_code" not in s or re.search(r"\b(semester|term|fall|spring|summer)\b", question, re.I):
        return False
    return Calendar(session, case["as_of"]).current().code != s["term_code"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default=str(ROOT / "data/testset/student/cases.jsonl"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--intent", action="append", default=[], help="only these intents (repeatable)")
    ap.add_argument("--id", action="append", default=[], help="only these case ids (repeatable)")
    ap.add_argument("--paraphrases", action="store_true", help="also run the two paraphrases of each case")
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--out", default=None, help="default: runs/student-<model>-<time>.jsonl")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cases = [json.loads(line) for line in open(args.cases)]
    if args.intent:
        cases = [c for c in cases if c["intent"] in args.intent]
    if args.id:
        cases = [c for c in cases if c["id"] in args.id]
    cases = cases[: args.limit]
    out = Path(args.out or ROOT / "runs" / f"student-{args.model.replace(':', '_').replace('/', '_')}-"
                                          f"{datetime.now():%Y%m%d-%H%M%S}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    client = make_client(args.base_url)
    session = get_session()
    by_intent, by_cat = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    total = passed = leaks = early = tool_errors = 0
    implicit_total = implicit_passed = 0
    seconds = []
    print(f"{len(cases)} cases, model {args.model} at {args.base_url}\nwriting {out}\n")

    with open(out, "w") as f:
        for case in cases:
            wordings = [("question", case["question"])]
            if args.paraphrases:
                wordings += [(f"paraphrase_{i + 1}", p) for i, p in enumerate(case["paraphrases"])]
            for variant, question in wordings:
                start = time.time()
                try:
                    agent = StudentAgent(client, session, case["student"]["university_id"], case["as_of"],
                                         model=args.model, max_steps=args.max_steps, verbose=args.verbose)
                    r = agent.ask(question)
                    reply, answer, calls, steps, stopped = r.reply, r.answer, r.calls, r.steps, r.stopped_early
                except Exception as e:  # noqa: BLE001  (endpoint down, model error): record and continue
                    if total == 0:
                        sys.exit(f"First call failed, is the model server running? {type(e).__name__}: {e}")
                    reply, answer, calls, steps, stopped = f"ERROR {type(e).__name__}: {e}", {}, [], 0, False
                finally:
                    session.rollback()
                dt = time.time() - start
                g = grade(case["answer"], answer, reply, case.get("must_not_mention"), case["intent"])
                implicit = unanswerable_term(case, question, session)

                total += 1
                passed += g.passed
                leaks += bool(g.leaked)
                early += stopped
                tool_errors += sum(not c.ok for c in calls)
                seconds.append(dt)
                for bucket in (by_intent[case["intent"]], by_cat[case["category"]]):
                    bucket[0] += g.passed
                    bucket[1] += 1
                if implicit:
                    implicit_total += 1
                    implicit_passed += g.passed

                tools = ", ".join(c.name + ("" if c.ok else "!") for c in calls) or "none"
                print(f"{'PASS' if g.passed else 'FAIL'} {dt:5.1f}s {case['id']:<28} {variant:<12} tools: {tools}"
                      + ("  [unanswerable: term not named]" if implicit else ""))
                if not g.passed:
                    print(f"      Q: {question}\n      " + "\n      ".join(g.problems[:4])
                          + f"\n      reply: {reply[:160]!r}")
                f.write(json.dumps({
                    "id": case["id"], "intent": case["intent"], "variant": variant, "question": question,
                    "as_of": case["as_of"], "passed": g.passed, "problems": g.problems, "leaked": g.leaked,
                    "unanswerable_term": implicit, "reply": reply, "answer": answer, "expected": case["answer"],
                    "calls": [{"name": c.name, "arguments": c.arguments, "ok": c.ok, "result": c.result} for c in calls],
                    "steps": steps, "stopped_early": stopped, "seconds": round(dt, 2)}, default=plain) + "\n")
    session.close()

    print("\nBy intent")
    for intent, (p, n) in sorted(by_intent.items()):
        print(f"  {intent:<18} {p:>3}/{n:<3} {100 * p / n:5.1f}%")
    print("By category")
    for cat, (p, n) in sorted(by_cat.items()):
        print(f"  {cat:<18} {p:>3}/{n:<3} {100 * p / n:5.1f}%")
    print(f"\nOverall           {passed}/{total} = {100 * passed / max(total, 1):.1f}%")
    if implicit_total:
        rest = total - implicit_total
        print(f"Excluding {implicit_total} unanswerable runs (no term named, non-current term expected): "
              f"{passed - implicit_passed}/{rest} = {100 * (passed - implicit_passed) / max(rest, 1):.1f}%")
    print(f"Leaks: {leaks}   stopped at max steps: {early}   failed tool calls: {tool_errors}   "
          f"mean time: {sum(seconds) / max(len(seconds), 1):.1f}s")


if __name__ == "__main__":
    main()
