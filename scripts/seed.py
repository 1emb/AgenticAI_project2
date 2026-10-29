"""Generate the dataset as CSV files (default data/seed/), optionally loading them into DATABASE_URL.

    python scripts/seed.py            # write data/seed/*.csv
    python scripts/seed.py --load     # write, then load into the database
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.seed.csv_io import load_all, write_all  # noqa: E402
from registrar.seed.generate import generate  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/seed")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--load", action="store_true", help="also load the CSVs into DATABASE_URL")
    args = ap.parse_args()
    data = generate(seed=args.seed)
    counts = write_all(Path(args.out), data)
    print(f"wrote {sum(counts.values())} rows to {args.out}/: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if args.load:
        from registrar.db import DATABASE_URL
        dsn = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        loaded = load_all(dsn, Path(args.out))
        print(f"loaded into {dsn.rsplit('/', 1)[-1]}: " + ", ".join(f"{k} {v}" for k, v in loaded.items()))


if __name__ == "__main__":
    main()
