"""Run the agent over a test set and grade each stage.

    python scripts/grade.py --persona student                 # all cases, question only
    python scripts/grade.py --paraphrases --workers 16        # also the two paraphrases of each case
    python scripts/grade.py --intent who_teaches --limit 5    # a slice
    python scripts/grade.py --out runs/student.jsonl          # per-question results (default runs/<persona>-<timestamp>.jsonl)
    python scripts/grade.py --llm-only                        # no database: classify + extract only, graded on the intent
    python scripts/grade.py --reply                           # also write the English reply and scan it for must_not_mention values

Per question it reports: intent correct, slots correct (resolved keys against the case's slots), answer correct (the verification
contract in data/testset/README.md), and which stage failed. Access-control cases are graded on the intent their scenario
classifies as (see EXPECTED_INTENT).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.agent.intents import BY_NAME, UNKNOWN  # noqa: E402
from registrar.agent.llm import Client, LLMError  # noqa: E402
from registrar.agent.pipeline import answer_question  # noqa: E402
from registrar.agent.reply import write_reply  # noqa: E402
from registrar.db import DATABASE_URL  # noqa: E402
from registrar.testset.common import Encoder, connect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

# access-control scenario -> the question type its wording asks for
EXPECTED_INTENT = {
    "other_program": "person_info", "other_status": "person_info", "other_contact": "person_info", "other_dob": "person_info", "other_ssn": "person_info",
    "other_graduation": "person_info", "impersonation": "person_info", "instructor_private": "person_info", "instructor_rank": "person_info",
    "same_program": "person_info", "student_list": "student_list",
    "instructor_of_lecture": "who_teaches", "instructor_email": "who_teaches", "teacher_and_phone": "who_teaches",
    "lecture_meeting": "lecture_meeting", "prerequisites": "prerequisites", "capacity": "capacity", "course_department": "course_info",
}


def expected_intent(case: dict) -> str:
    if case["intent"].startswith("access_"):
        return EXPECTED_INTENT[case["slots"]["scenario"]]
    return case["intent"]


def expected_slots(case: dict) -> dict:
    """The keys the resolver must reach, from the case's slots."""
    s, out = case["slots"], {}
    if "course" in s and "crn" not in s:          # with a CRN the course is derived, not mentioned
        out["course"] = s["course"]
    if "crn" in s:
        out["crn"] = s["crn"]
    if "term_code" in s:
        out["term"] = s["term_code"]
    if "term_number" in s:
        out["term_number"] = s["term_number"]
    if "event" in s:
        out["event"] = s["event"]
    if "t_uid" in s:
        out["person"] = s["t_uid"]
    if "i_uid" in s:
        out["person"] = s["i_uid"]
    if case["answer"].get("target", {}).get("program"):
        out["program"] = case["answer"]["target"]["program"]
    return out


# ---- the verification contract ----
def norm(v):
    if isinstance(v, str):
        return v.strip().lower()
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def equal(got, exp) -> bool:
    if isinstance(exp, dict):
        return isinstance(got, dict) and all(k in got and equal(got[k], v) for k, v in exp.items())
    if isinstance(exp, list):
        if not isinstance(got, list) or len(got) != len(exp):
            return False
        left = list(got)
        for e in exp:                                   # multiset match
            for i, g in enumerate(left):
                if equal(g, e):
                    del left[i]
                    break
            else:
                return False
        return True
    return norm(got) == norm(exp)


def grade_answer(got: dict | None, exp: dict) -> tuple[bool, str | None]:
    if got is None:
        return False, "no answer"
    got = json.loads(json.dumps(got, cls=Encoder))
    if norm(got.get("allowed")) != norm(exp["allowed"]):
        return False, f"allowed: got {got.get('allowed')}, expected {exp['allowed']}"
    for k, v in exp.items():
        if k not in got:
            return False, f"missing field {k}"
        if not equal(got[k], v):
            return False, f"{k}: got {json.dumps(got[k], ensure_ascii=False)[:120]}, expected {json.dumps(v, ensure_ascii=False)[:120]}"
    return True, None


# ---- running ----
_local = threading.local()


def conn():
    if not hasattr(_local, "conn"):
        _local.conn = connect(DSN)
    return _local.conn


def run_llm_only(llm: Client, case: dict, question: str, which: str) -> dict:
    """Stages 1 and 2 without a database: the intent is graded, the mentions are shown next to the case's slots."""
    exp_int = expected_intent(case)
    try:
        label, res = llm.classify(question)
        mentions, _ = llm.extract(question, BY_NAME.get(label, BY_NAME[UNKNOWN]))
    except LLMError as e:
        return {"id": case["id"], "which": which, "question": question, "error": str(e), "expected_intent": exp_int, "intent_ok": False, "slots_ok": False, "answer_ok": False}
    return {"id": case["id"], "which": which, "question": question, "expected_intent": exp_int, "intent": label, "intent_confidence": res.confidence,
            "intent_ok": label == exp_int, "mentions": mentions, "expected_slots": expected_slots(case), "slots_ok": False, "answer_ok": False,
            "timings": {"classify_s": round(res.latency_s, 3)}}


def run_one(llm: Client, case: dict, question: str, which: str, reply: bool = False) -> dict:
    as_of = datetime.fromisoformat(case["as_of"])
    try:
        t = answer_question(conn(), llm, question, case["student"]["university_id"], as_of)
    except Exception as e:  # noqa: BLE001
        return {"id": case["id"], "which": which, "question": question, "error": f"{type(e).__name__}: {e}", "intent_ok": False, "slots_ok": False, "answer_ok": False}
    exp_int, exp_slots = expected_intent(case), expected_slots(case)
    got_slots = {k: v["value"] for k, v in t.resolved.items() if k in exp_slots}
    slot_diffs = {k: (got_slots.get(k), v) for k, v in exp_slots.items() if norm(got_slots.get(k)) != norm(v)}
    answer_ok, why = grade_answer(t.answer, case["answer"])
    out = {
        "id": case["id"], "which": which, "question": question, "expected_intent": exp_int, "intent": t.intent, "intent_confidence": t.intent_confidence,
        "intent_ok": t.intent == exp_int, "mentions": t.mentions, "resolved": t.resolved, "expected_slots": exp_slots, "slot_diffs": slot_diffs,
        "slots_ok": not slot_diffs, "answer": t.answer, "expected_answer": case["answer"], "answer_ok": answer_ok, "answer_why": why,
        "error": t.error, "failed_stage": t.failed_stage, "timings": t.timings,
    }
    if reply:
        # the verification contract: the prose of an access-control case must not carry any protected value
        text = write_reply(llm, t)
        leaked = [m for m in case.get("must_not_mention") or [] if m.lower() in text.lower()]
        out.update({"reply": text, "leaked": leaked})
        if leaked:
            out["answer_ok"], out["answer_why"] = False, f"reply mentions protected value(s) {leaked}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="student", choices=["student"])
    ap.add_argument("--paraphrases", action="store_true")
    ap.add_argument("--intent", help="only cases of this (case) intent, e.g. who_teaches or access_denied")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out")
    ap.add_argument("--quiet", action="store_true", help="do not list failures")
    ap.add_argument("--llm-only", action="store_true", help="classify and extract only; needs no database")
    ap.add_argument("--reply", action="store_true", help="also write the English reply (stage 5) and fail a case whose reply leaks a must_not_mention value")
    args = ap.parse_args()

    cases = [json.loads(l) for l in open(ROOT / "data" / "testset" / args.persona / "cases.jsonl")]
    if args.intent:
        cases = [c for c in cases if c["intent"] == args.intent]
    if args.limit:
        cases = cases[: args.limit]
    jobs = [(c, c["question"], "question") for c in cases]
    if args.paraphrases:
        jobs += [(c, p, f"paraphrase{i + 1}") for c in cases for i, p in enumerate(c["paraphrases"])]

    llm = Client()
    try:
        models = llm.ping()
    except LLMError as e:
        raise SystemExit(f"LLM server: {e}\nstart it with scripts/serve_llm.sh")
    print(f"model {llm.model} at {llm.base_url} (served: {', '.join(models)}); {len(jobs)} questions, {args.workers} workers")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(lambda j: run_llm_only(llm, *j) if args.llm_only else run_one(llm, *j, reply=args.reply), jobs))
    elapsed = time.perf_counter() - t0

    out = Path(args.out) if args.out else ROOT / "runs" / f"{args.persona}-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for r in results:
            f.write(json.dumps(r, cls=Encoder, ensure_ascii=False) + "\n")

    by_intent: dict[str, list] = defaultdict(list)
    case_intent = {c["id"]: c["intent"] for c in cases}
    for r in results:
        by_intent[case_intent[r["id"]]].append(r)
    print(f"\n{'intent':18} {'n':>4} {'intent':>7} {'slots':>7} {'answer':>7}")
    for k in sorted(by_intent):
        rs = by_intent[k]
        print(f"{k:18} {len(rs):4d} {sum(r['intent_ok'] for r in rs) / len(rs):7.0%} {sum(r['slots_ok'] for r in rs) / len(rs):7.0%} {sum(r['answer_ok'] for r in rs) / len(rs):7.0%}")
    n = len(results)
    print(f"{'all':18} {n:4d} {sum(r['intent_ok'] for r in results) / n:7.0%} {sum(r['slots_ok'] for r in results) / n:7.0%} {sum(r['answer_ok'] for r in results) / n:7.0%}")
    print(f"{elapsed:.0f}s, {elapsed / n:.1f}s per question; results in {out}")

    if not args.quiet:
        fails = [r for r in results if not (r["intent_ok"] if args.llm_only else r["answer_ok"])]
        if fails:
            print(f"\n{len(fails)} failures:")
        for r in fails:
            stage = "classify" if not r["intent_ok"] else "resolve" if not r["slots_ok"] else r.get("failed_stage") or "program"
            print(f"- {r['id']} [{r['which']}] ({stage}) {r['question']}")
            if not r["intent_ok"]:
                print(f"    intent {r.get('intent')} (expected {r.get('expected_intent')}, confidence {r.get('intent_confidence') or 0:.2f})")
            if r.get("mentions"):
                print(f"    mentions {json.dumps(r['mentions'], ensure_ascii=False)}")
            if args.llm_only and r.get("expected_slots"):
                print(f"    expected {json.dumps(r['expected_slots'], ensure_ascii=False)}")
            if r.get("slot_diffs"):
                print(f"    slots {json.dumps(r['slot_diffs'], cls=Encoder, ensure_ascii=False)}")
            if r.get("answer_why"):
                print(f"    answer {r['answer_why']}")
            if r.get("leaked"):
                print(f"    reply {r['reply']}")
            if r.get("error"):
                print(f"    error {r['error']}")


if __name__ == "__main__":
    main()
