"""Build the English question -> discrete answer test set from a loaded database (plus a derivation side file).

    python scripts/make_testset.py --persona student      # reads DATABASE_URL (data/seed loaded), writes data/testset/student/cases.jsonl
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.db import DATABASE_URL  # noqa: E402
from registrar.testset.common import Encoder, connect  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="student", choices=["student", "professor"])
    ap.add_argument("--out", default=None, help="default: data/testset/<persona>/cases.jsonl")
    ap.add_argument("--seed", type=int, default=None, help="default: 7 for student, 11 for professor")
    args = ap.parse_args()
    args.out = args.out or f"data/testset/{args.persona}/cases.jsonl"
    args.seed = args.seed if args.seed is not None else {"student": 7, "professor": 11}[args.persona]

    dsn = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with connect(dsn) as conn:
        if args.persona == "student":
            from registrar.testset.build_student import generate
        else:
            from registrar.testset.build_professor import generate
        cases = generate(conn, seed=args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    derivation = out.with_name("derivation.jsonl")
    with open(out, "w") as f, open(derivation, "w") as g:
        for c in cases:
            lean = {k: v for k, v in c.items() if k not in ("sql", "expected_facts", "reference_answer")}
            f.write(json.dumps(lean, cls=Encoder, ensure_ascii=False) + "\n")
            g.write(json.dumps({"id": c["id"], "sql": c["sql"], "expected_facts": c["expected_facts"],
                                "reference_answer": c["reference_answer"]}, cls=Encoder, ensure_ascii=False) + "\n")
    counts = Counter(c["intent"] for c in cases)
    print(f"wrote {len(cases)} cases to {out}; derivations to {derivation} (database {dsn.rsplit('/', 1)[-1]})")
    for k, v in sorted(counts.items()):
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()
