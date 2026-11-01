"""Summarise the interactive test log (runs/chat.jsonl): what was asked, what the agent did, and the verdicts given.

    python scripts/review.py                      # summary tables
    python scripts/review.py --list wrong         # list every question with that verdict (or: unjudged, refused, error, all)
    python scripts/review.py --intent who_teaches --since 2026-11-01
    python scripts/review.py --csv runs/chat.csv  # flat export, one row per question, for a spreadsheet
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.chatlog import LOG_PATH, VERDICTS, load, outcome  # noqa: E402

COLS = ["id", "ts", "source", "student_id", "student_name", "program", "as_of", "question", "intent", "intent_confidence", "outcome",
        "reply", "answer", "mentions", "resolved", "error", "failed_stage", "total_s", "verdict", "note"]


def flat(r: dict) -> dict:
    st = r.get("student") or {}
    return {
        "id": r["id"], "ts": r["ts"], "source": r.get("source"), "student_id": st.get("university_id"), "student_name": st.get("name"),
        "program": st.get("program_code"), "as_of": r.get("as_of"), "question": r.get("question"), "intent": r.get("intent"),
        "intent_confidence": r.get("intent_confidence"), "outcome": outcome(r), "reply": r.get("reply"),
        "answer": json.dumps(r.get("answer"), ensure_ascii=False), "mentions": json.dumps(r.get("mentions"), ensure_ascii=False),
        "resolved": json.dumps({k: v.get("value") for k, v in (r.get("resolved") or {}).items()}, ensure_ascii=False),
        "error": r.get("error"), "failed_stage": r.get("failed_stage"), "total_s": round(sum((r.get("timings") or {}).values()), 2),
        "verdict": r.get("verdict"), "note": r.get("note"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=None, help=f"default {LOG_PATH}")
    ap.add_argument("--since", help="ISO date or datetime; only questions asked from then on")
    ap.add_argument("--intent")
    ap.add_argument("--source", help="ui or ask.py")
    ap.add_argument("--list", choices=list(VERDICTS) + ["unjudged", "refused", "error", "clarify", "unknown", "all"], help="print the matching questions")
    ap.add_argument("--csv", help="write every (filtered) question to this CSV")
    args = ap.parse_args()

    rows = load(Path(args.log)) if args.log else load()
    if args.since:
        rows = [r for r in rows if r["ts"] >= args.since]
    if args.intent:
        rows = [r for r in rows if r.get("intent") == args.intent]
    if args.source:
        rows = [r for r in rows if r.get("source") == args.source]
    if not rows:
        print(f"nothing in {args.log or LOG_PATH}" + (" matching the filters" if args.since or args.intent or args.source else ""))
        return

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, COLS)
            w.writeheader()
            for r in rows:
                w.writerow(flat(r))
        print(f"wrote {len(rows)} rows to {args.csv}")

    if args.list:
        sel = [r for r in rows if args.list == "all" or r.get("verdict") == args.list or (args.list == "unjudged" and not r.get("verdict")) or outcome(r) == args.list]
        print(f"{len(sel)} questions ({args.list}):")
        for r in sel:
            st = r.get("student") or {}
            print(f"- [{r['ts'][:16]}] {st.get('name')} ({st.get('program_code')}) asked: {r['question']}")
            print(f"    intent {r.get('intent')} -> {outcome(r)}; reply: {r.get('reply')}")
            if r.get("verdict") or r.get("note"):
                print(f"    verdict {r.get('verdict')}" + (f": {r['note']}" if r.get("note") else ""))
            if r.get("error"):
                print(f"    error ({r.get('failed_stage')}): {r['error']}")
        return

    n = len(rows)
    judged = [r for r in rows if r.get("verdict")]
    print(f"{n} questions in {args.log or LOG_PATH}, {rows[0]['ts'][:16]} to {rows[-1]['ts'][:16]}; {len(judged)} judged, {n - len(judged)} not yet")
    print(f"sources: " + ", ".join(f"{k} {v}" for k, v in Counter(r.get('source') for r in rows).most_common()))
    print(f"students: {len({(r.get('student') or {}).get('university_id') for r in rows})} distinct")

    print(f"\n{'outcome':10} {'n':>5}")
    for k, v in Counter(outcome(r) for r in rows).most_common():
        print(f"{k:10} {v:5d}")

    print(f"\n{'verdict':15} {'n':>5}")
    for k in VERDICTS:
        print(f"{k:15} {sum(r.get('verdict') == k for r in rows):5d}")
    print(f"{'unjudged':15} {n - len(judged):5d}")
    if judged:
        print(f"correct among judged: {sum(r['verdict'] == 'correct' for r in judged) / len(judged):.0%}")

    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r.get("intent") or "?"].append(r)
    print(f"\n{'intent':18} {'n':>4} {'answered':>8} {'refused':>7} {'clarify':>7} {'error':>5} {'correct':>7} {'wrong':>5} {'other':>5} {'conf':>5} {'avg s':>6}")
    for k in sorted(by):
        rs = by[k]
        oc = Counter(outcome(r) for r in rs)
        vd = Counter(r.get("verdict") for r in rs)
        confs = [r["intent_confidence"] for r in rs if r.get("intent_confidence") is not None]
        avg_s = sum(sum((r.get("timings") or {}).values()) for r in rs) / len(rs)
        print(f"{k:18} {len(rs):4d} {oc['answered']:8d} {oc['refused']:7d} {oc['clarify'] + oc['unknown']:7d} {oc['error']:5d} {vd['correct']:7d} {vd['wrong']:5d} "
              f"{vd['should_refuse'] + vd['should_answer']:5d} {sum(confs) / len(confs) if confs else 0:5.2f} {avg_s:6.1f}")

    bad = [r for r in rows if r.get("verdict") in ("wrong", "should_refuse", "should_answer")]
    if bad:
        print(f"\n{len(bad)} judged wrong:")
        for r in bad[-15:]:
            print(f"- [{r.get('verdict')}] {r['question']}  -> {r.get('intent')} / {outcome(r)}" + (f"  ({r['note']})" if r.get("note") else ""))
    errs = [r for r in rows if outcome(r) == "error"]
    if errs:
        print(f"\n{len(errs)} errors:")
        for r in errs[-10:]:
            print(f"- {r['question']}  ({r.get('failed_stage')}: {r.get('error')})")
    slow = sorted(rows, key=lambda r: -sum((r.get("timings") or {}).values()))[:5]
    print("\nslowest:")
    for r in slow:
        print(f"- {sum((r.get('timings') or {}).values()):.1f}s  {r['question']}  ({r.get('intent')})")
    print("\nmore: --list wrong | --list unjudged | --csv runs/chat.csv")


if __name__ == "__main__":
    main()
