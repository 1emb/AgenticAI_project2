"""Load a CSV dump (as written by `scripts/seed.py --dump`) into the database named by DATABASE_URL.

    DATABASE_URL=postgresql+psycopg://registrar@localhost:5433/registrar_sample \
        python scripts/load_csv.py data/sample/seed_csv

Run scripts/init_db.py against the same DATABASE_URL first. Tables are truncated before loading.
"""
import ast
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import JSON  # noqa: E402

from registrar.models import Base  # noqa: E402
from registrar.seed.load import load  # noqa: E402


def _parse_json(v: str):
    try:
        return json.loads(v)
    except ValueError:
        return ast.literal_eval(v)  # older dumps wrote python repr


def read_dump(csv_dir: Path) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for table, tbl in Base.metadata.tables.items():
        f = csv_dir / f"{table}.csv"
        if not f.exists():
            continue
        json_cols = {c.name for c in tbl.columns if isinstance(c.type, JSON)}
        with open(f, newline="") as fh:
            data = []
            for r in csv.DictReader(fh):
                for k, v in r.items():
                    if v == "":
                        r[k] = None
                    elif k in json_cols:
                        r[k] = _parse_json(v)
                data.append(r)
        rows[table] = data
    return rows


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/seed_csv")
    rows = read_dump(src)
    print(f"read {sum(len(v) for v in rows.values()):,} rows from {len(rows)} CSVs in {src}")
    load(rows)
