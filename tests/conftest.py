"""Shared fixtures. Database tests need the seeded registrar database from the README Setup section
(DATABASE_URL in .env); they are skipped when it cannot be reached."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STUDENT_CASES = [json.loads(line) for line in open(ROOT / "data/testset/student/cases.jsonl")]


@pytest.fixture(scope="session")
def session():
    from sqlalchemy import text
    from registrar.db import get_session
    s = get_session()
    try:
        s.execute(text("SELECT 1 FROM lecture LIMIT 1"))
    except Exception as e:  # noqa: BLE001
        s.close()
        pytest.skip(f"registrar database not reachable: {type(e).__name__}")
    yield s
    s.rollback()
    s.close()
