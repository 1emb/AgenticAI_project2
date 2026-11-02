"""Append an external judge's verdicts to the interactive test log, marked with who judged.

    python scripts/import_verdicts.py runs/codex/phase2-verdicts.jsonl --by codex
    python scripts/import_verdicts.py some.jsonl --by codex --dry-run

Input: JSONL, one object per judged question with `record_id` (the ask's id in runs/chat.jsonl), `verdict` (correct | wrong |
should_refuse | should_answer) and `note`; `n`, `weak` and `leak` are folded into the note when present. Rows whose record_id
is not an ask in the log are reported and skipped. The page shows these verdicts with the judge's name; clicking a verdict on
the page overrules them (latest wins, by=owner).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.chatlog import LOG_PATH, VERDICTS, load, record_verdict  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--by", required=True, help="judge name, e.g. codex")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    known = {r["id"]: r for r in load()}
    rows = [json.loads(l) for l in open(args.file) if l.strip()]
    done = skipped = 0
    for r in rows:
        rid, v = r.get("record_id"), r.get("verdict")
        if rid not in known or v not in VERDICTS:
            print(f"skip n={r.get('n')}: record {rid!r} {'not in log' if rid not in known else 'has verdict ' + repr(v)}")
            skipped += 1
            continue
        tags = ("[weak reply] " if r.get("weak") else "") + ("[leak-scan hit] " if r.get("leak") else "")
        note = f"[{args.by} n={r.get('n')}] {tags}{(r.get('note') or '').strip()}"
        if known[rid].get("question") != r.get("question"):
            print(f"warning n={r.get('n')}: question text differs from the log for record {rid}")
        if not args.dry_run:
            record_verdict(rid, v, note, by=args.by)
        done += 1
    print(f"{'would append' if args.dry_run else 'appended'} {done} verdicts from {args.by} to {LOG_PATH}; skipped {skipped}")


if __name__ == "__main__":
    main()
