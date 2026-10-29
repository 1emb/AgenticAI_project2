"""Load the committed CSV dataset (data/seed/) into the database named by DATABASE_URL. Empties the tables first."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.db import DATABASE_URL  # noqa: E402
from registrar.seed.csv_io import load_all  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default="data/seed")
    args = ap.parse_args()
    dsn = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    counts = load_all(dsn, Path(args.dir))
    print(f"loaded {args.dir}/ into {dsn.rsplit('/', 1)[-1]}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
