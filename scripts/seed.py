"""Generate and load synthetic registrar data.

    python scripts/seed.py            # full size (~13k active undergrads)
    python scripts/seed.py --scale 0.05 --seed 1
    python scripts/seed.py --dump     # also write CSV copies to $DATA_DIR/seed_csv/
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.seed.generate import Generator  # noqa: E402
from registrar.seed.load import load  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dump", action="store_true", help="also dump CSVs to DATA_DIR/seed_csv")
    ap.add_argument("--no-load", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    gen = Generator(scale=args.scale, seed=args.seed)
    rows = gen.run(log=lambda m: print(f"[gen] {m}", flush=True))
    print(f"[gen] done in {time.time() - t0:.1f}s; {sum(len(v) for v in rows.values()):,} rows across {len(rows)} tables", flush=True)

    if args.dump:
        out = Path(os.environ.get("DATA_DIR", "data")) / "seed_csv"
        out.mkdir(parents=True, exist_ok=True)
        for table, data in rows.items():
            if not data:
                continue
            with open(out / f"{table}.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                w.writeheader()
                w.writerows(data)
        print(f"[dump] CSVs written to {out}")

    if not args.no_load:
        t1 = time.time()
        load(rows, log=lambda m: print(f"[load] {m}", flush=True))
        print(f"[load] done in {time.time() - t1:.1f}s")


if __name__ == "__main__":
    main()
