"""Grade the whole system (Router + persona agents + shared tools) against the test sets with a real model.

    python scripts/eval_agents.py --persona professor                      # all 118 cases
    python scripts/eval_agents.py --persona administrator --limit 10
    python scripts/eval_agents.py --persona all --per-intent 1             # one case per intent, every persona
    LLM_BACKEND=ollama-native python scripts/eval_agents.py --persona all --per-intent 1 --model qwen3:1.7b
    python scripts/eval_agents.py --persona all --multi                    # through the multi-agent coordinator

Each case runs in a fresh Router logged in as the case's user, at the case's clock. Graded with
registrar/eval/grader.py (the contract in data/testset/README.md). Runs are written to runs/<persona>-<model>-<time>.jsonl.
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from registrar.agents.common import plain  # noqa: E402
from registrar.agents.loop import DEFAULT_BASE_URL, DEFAULT_MODEL, make_client  # noqa: E402
from registrar.agents.router import Router  # noqa: E402
from registrar.db import get_session  # noqa: E402
from registrar.eval.grader import grade  # noqa: E402

SETS = {"student": ("student", "student"), "professor": ("professor", "instructor"),
        "administrator": ("administrator", "admin")}


def user_of(case: dict, persona: str) -> str:
    if persona == "student":
        return case["student"]["university_id"]
    if persona == "professor":
        return case["professor"]["university_id"]
    return "900000001"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--persona", choices=[*SETS, "all"], default="all")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--per-intent", type=int, help="take N cases of each intent")
    ap.add_argument("--skip-per-intent", type=int, default=0, help="skip the first K cases of each intent "
                                                                     "(held-out runs after tuning on the first ones)")
    ap.add_argument("--intent", action="append", default=[])
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--multi", action="store_true", help="ask through the multi-agent coordinator (planner, specialists, "
                                                         "composer) instead of the single persona agent")
    a = ap.parse_args()
    mode = "multi" if a.multi else "single"

    client, session = make_client(a.base_url), get_session()
    personas = list(SETS) if a.persona == "all" else [a.persona]
    out_dir = ROOT / "runs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    totals = {}
    for persona in personas:
        folder, role = SETS[persona]
        cases = [json.loads(l) for l in open(ROOT / f"data/testset/{folder}/cases.jsonl")]
        if a.intent:
            cases = [c for c in cases if c["intent"] in a.intent]
        if a.id:
            cases = [c for c in cases if c["id"] in a.id]
        if a.per_intent:
            seen = defaultdict(int)
            keep = []
            for c in cases:
                seen[c["intent"]] += 1
                if a.skip_per_intent < seen[c["intent"]] <= a.skip_per_intent + a.per_intent:
                    keep.append(c)
            cases = keep
        if a.limit:
            cases = cases[:a.limit]
        path = out_dir / f"{persona}-{mode}-{a.model.replace(':', '_')}-{stamp}.jsonl"
        print(f"\n== {persona} ({mode}): {len(cases)} cases, model {a.model}; writing {path}")
        by_intent = defaultdict(lambda: [0, 0])
        with open(path, "w") as f:
            for c in cases:
                t0 = time.time()
                try:
                    router = Router(client, session, user_of(c, persona), role, c["as_of"], a.model, a.verbose)
                    if a.multi:
                        from registrar.agents.multi import Coordinator
                        r = Coordinator(router, model=a.model).ask(c["question"])
                    else:
                        r = router.ask(c["question"])
                    g = grade(c["answer"], r.answer, r.reply, c.get("must_not_mention"), c["intent"])
                    rec = {"id": c["id"], "passed": g.passed, "problems": g.problems[:5], "reply": r.reply,
                           "answer": r.answer, "expected": c["answer"], "steps": r.steps,
                           "tools": [x.name for x in r.calls], "failed_tools": [x.name for x in r.calls if not x.ok],
                           "calls": [{"name": x.name, "args": x.arguments, "ok": x.ok} for x in r.calls],
                           "grounding_retry": getattr(r, "grounding_retry", False), "mode": mode,
                           "route": getattr(r, "route", None), "plan": getattr(r, "plan", None)}
                except Exception as e:  # noqa: BLE001 - one bad run must not stop the evaluation
                    session.rollback()
                    rec = {"id": c["id"], "passed": False, "problems": [f"{type(e).__name__}: {e}"], "tools": []}
                rec["seconds"] = round(time.time() - t0, 1)
                f.write(json.dumps(rec, default=plain) + "\n")
                f.flush()
                by_intent[c["intent"]][0] += rec["passed"]
                by_intent[c["intent"]][1] += 1
                print(f"{'PASS' if rec['passed'] else 'FAIL'} {rec['seconds']:6.1f}s {c['id']:<36} tools: "
                      f"{', '.join(rec['tools']) or 'none'}" + ("" if rec["passed"] else f"  | {rec['problems'][:1]}"),
                      flush=True)
        ok = sum(p for p, _ in by_intent.values())
        n = sum(t for _, t in by_intent.values())
        totals[persona] = (ok, n)
        for k, (p, t) in sorted(by_intent.items()):
            print(f"  {k:<28} {p}/{t}")
        print(f"  {persona} overall {ok}/{n} = {100 * ok / max(n, 1):.1f}%")
    print("\nSummary:", ", ".join(f"{k} {p}/{n}" for k, (p, n) in totals.items()))


if __name__ == "__main__":
    main()
