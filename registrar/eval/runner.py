"""Run an agent over a persona's test set with a real model and grade every answer.

Used by scripts/eval_student_agent.py and scripts/eval_professor_agent.py. Each run uses a fresh agent set to the
case's user and clock; the JSON answer is graded with registrar/eval/grader.py; every run is written to
runs/<persona>-<model>-<time>.jsonl. Runs the test set itself makes unanswerable are reported separately.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from registrar.agents.calendar import Calendar
from registrar.agents.common import plain
from registrar.agents.loop import DEFAULT_BASE_URL, DEFAULT_MODEL, make_client
from registrar.db import get_session
from registrar.eval.grader import grade

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Persona:
    name: str                      # "student" / "professor"
    agent_class: type              # StudentAgent / ProfessorAgent
    user_key: str                  # case field holding the authenticated user
    unanswerable: Callable[[dict, str, object], str | None]   # (case, question, session) -> reason or None


def term_not_named(case: dict, question: str, session) -> str | None:
    """The question names no term, yet the ground truth is a non-current term (e.g. 'When does CRN 10089 meet?'
    graded against Spring 2027 at a Fall 2026 clock). CRNs repeat across terms, so no agent can know."""
    s = case["slots"]
    if "term_code" not in s or re.search(r"\b(semester|term|fall|spring|summer)\b", question, re.I):
        return None
    if Calendar(session, case["as_of"]).current().code != s["term_code"]:
        return "term not named"
    return None


def parser(persona: str, doc: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default=str(ROOT / f"data/testset/{persona}/cases.jsonl"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--intent", action="append", default=[], help="only these intents (repeatable)")
    ap.add_argument("--id", action="append", default=[], help="only these case ids (repeatable)")
    ap.add_argument("--paraphrases", action="store_true", help="also run the two paraphrases of each case")
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--out", default=None, help=f"default: runs/{persona}-<model>-<time>.jsonl")
    ap.add_argument("--verbose", action="store_true")
    return ap


def run(p: Persona, args: argparse.Namespace, client=None) -> dict:
    cases = [json.loads(line) for line in open(args.cases)]
    if args.intent:
        cases = [c for c in cases if c["intent"] in args.intent]
    if args.id:
        cases = [c for c in cases if c["id"] in args.id]
    cases = cases[: args.limit]
    model_tag = re.sub(r"[^A-Za-z0-9_.-]", "_", args.model)
    out = Path(args.out or ROOT / "runs" / f"{p.name}-{model_tag}-{datetime.now():%Y%m%d-%H%M%S}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    client = client or make_client(args.base_url)
    session = get_session()
    by_intent, by_cat = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    total = passed = leaks = early = tool_errors = skipped_total = skipped_passed = 0
    seconds: list[float] = []
    print(f"{len(cases)} {p.name} cases, model {args.model} at {args.base_url}\nwriting {out}\n")

    with open(out, "w") as f:
        for case in cases:
            wordings = [("question", case["question"])]
            if args.paraphrases:
                wordings += [(f"paraphrase_{i + 1}", q) for i, q in enumerate(case["paraphrases"])]
            for variant, question in wordings:
                start = time.time()
                try:
                    agent = p.agent_class(client, session, case[p.user_key]["university_id"], case["as_of"],
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
                unanswerable = p.unanswerable(case, question, session)

                total += 1
                passed += g.passed
                leaks += bool(g.leaked)
                early += stopped
                tool_errors += sum(not c.ok for c in calls)
                seconds.append(dt)
                for bucket in (by_intent[case["intent"]], by_cat[case["category"]]):
                    bucket[0] += g.passed
                    bucket[1] += 1
                if unanswerable:
                    skipped_total += 1
                    skipped_passed += g.passed

                tools = ", ".join(c.name + ("" if c.ok else "!") for c in calls) or "none"
                print(f"{'PASS' if g.passed else 'FAIL'} {dt:5.1f}s {case['id']:<28} {variant:<12} tools: {tools}"
                      + (f"  [unanswerable: {unanswerable}]" if unanswerable else ""))
                if not g.passed:
                    print(f"      Q: {question}\n      " + "\n      ".join(g.problems[:4])
                          + f"\n      reply: {reply[:160]!r}")
                f.write(json.dumps({
                    "id": case["id"], "intent": case["intent"], "variant": variant, "question": question,
                    "as_of": case["as_of"], "passed": g.passed, "problems": g.problems, "leaked": g.leaked,
                    "unanswerable": unanswerable, "reply": reply, "answer": answer, "expected": case["answer"],
                    "calls": [{"name": c.name, "arguments": c.arguments, "ok": c.ok, "result": c.result} for c in calls],
                    "steps": steps, "stopped_early": stopped, "seconds": round(dt, 2)}, default=plain) + "\n")
    session.close()

    print("\nBy intent")
    for intent, (n_pass, n) in sorted(by_intent.items()):
        print(f"  {intent:<18} {n_pass:>3}/{n:<3} {100 * n_pass / n:5.1f}%")
    print("By category")
    for cat, (n_pass, n) in sorted(by_cat.items()):
        print(f"  {cat:<18} {n_pass:>3}/{n:<3} {100 * n_pass / n:5.1f}%")
    print(f"\nOverall           {passed}/{total} = {100 * passed / max(total, 1):.1f}%")
    if skipped_total:
        rest = total - skipped_total
        print(f"Excluding {skipped_total} unanswerable runs: {passed - skipped_passed}/{rest} = "
              f"{100 * (passed - skipped_passed) / max(rest, 1):.1f}%")
    print(f"Leaks: {leaks}   stopped at max steps: {early}   failed tool calls: {tool_errors}   "
          f"mean time: {sum(seconds) / max(len(seconds), 1):.1f}s")
    return {"total": total, "passed": passed, "leaks": leaks, "unanswerable": skipped_total,
            "unanswerable_passed": skipped_passed, "out": str(out)}
