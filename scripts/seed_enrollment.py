"""Generate the synthetic enrollment history and advisor assignment from data/seed/ into data/seed_enrollment/,
and optionally load them (run scripts/load_seed.py first; it empties these tables through CASCADE).

    python scripts/seed_enrollment.py --load
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from registrar.seed.enrollment import generate, load, write  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-dir", default=str(ROOT / "data/seed"))
    ap.add_argument("--out", default=str(ROOT / "data/seed_enrollment"))
    ap.add_argument("--load", action="store_true", help="also load into DATABASE_URL")
    a = ap.parse_args()
    enroll, advisors = generate(Path(a.seed_dir))
    print("wrote", write(Path(a.out), enroll, advisors))
    if a.load:
        from registrar.db import DATABASE_URL
        print("loaded", load(DATABASE_URL.replace("postgresql+psycopg://", "postgresql://"), Path(a.out)))


if __name__ == "__main__":
    main()
