"""Bulk-load generated rows into Postgres with COPY, in FK-safe order, then reset sequences."""
from __future__ import annotations

import json
import time
from datetime import datetime, date, time as dtime
from decimal import Decimal

import psycopg
from sqlalchemy import text

from ..db import engine
from ..models import Base

# Parent tables first.
LOAD_ORDER = [
    "academic_term", "academic_calendar_event", "college", "department", "subject", "program", "course",
    "course_prerequisite", "program_requirement", "program_requirement_course", "building", "room",
    "person", "person_name_history", "address", "emergency_contact", "student", "student_program", "instructor",
    "staff", "advisor_assignment", "section", "section_meeting", "section_instructor", "hold",
    "registration_appointment", "enrollment", "enrollment_event", "waitlist_entry", "registration_override",
    "grade", "grade_change", "student_term_record", "academic_action", "transfer_institution", "articulation_rule",
    "transfer_credit", "test_credit", "graduation_application", "degree_awarded", "degree_audit",
    "transcript_request", "enrollment_verification", "ferpa_release", "ferpa_directory_optout", "disclosure_log",
    "petition", "user_account", "role", "permission", "role_permission", "user_role", "audit_log",
]


def _dsn() -> str:
    url = engine.url
    return f"host={url.host} port={url.port} dbname={url.database} user={url.username}" + (f" password={url.password}" if url.password else "")


def _copy_value(v):
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    if hasattr(v, "value") and not isinstance(v, (str, int, float)):
        return v.value  # python Enum
    return v


def load(rows: dict[str, list[dict]], log=print, truncate=True):
    meta = Base.metadata
    ordered = [t for t in LOAD_ORDER if t in meta.tables]
    missing = set(meta.tables) - set(ordered)
    if missing:
        raise RuntimeError(f"LOAD_ORDER missing tables: {missing}")
    with psycopg.connect(_dsn(), autocommit=False) as conn:
        with conn.cursor() as cur:
            if truncate:
                cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in ordered) + " RESTART IDENTITY CASCADE")
            cur.execute("SET session_replication_role = replica")  # skip FK checks during bulk load; re-validated below
            for table in ordered:
                data = rows.get(table, [])
                if not data:
                    continue
                cols = [c.name for c in meta.tables[table].columns if any(c.name in r for r in data[:1])]
                cols = [c.name for c in meta.tables[table].columns if c.name in data[0]]
                t0 = time.time()
                with cur.copy(f'COPY "{table}" ({", ".join(cols)}) FROM STDIN') as copy:
                    for r in data:
                        copy.write_row([_copy_value(r.get(c)) for c in cols])
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM \"{table}\"")
                log(f"  {table:28s} {len(data):>9,d} rows  {time.time() - t0:5.1f}s")
            cur.execute("SET session_replication_role = DEFAULT")
        conn.commit()
    # Re-validate FKs (replica mode skipped them). Any violation raises here.
    with engine.begin() as c:
        for table in ordered:
            for fk in meta.tables[table].foreign_keys:
                col = fk.parent
                ref = fk.column
                bad = c.execute(text(
                    f'SELECT count(*) FROM "{table}" t LEFT JOIN "{ref.table.name}" r ON t."{col.name}" = r."{ref.name}" '
                    f'WHERE t."{col.name}" IS NOT NULL AND r."{ref.name}" IS NULL')).scalar()
                if bad:
                    raise RuntimeError(f"FK violation: {table}.{col.name} -> {ref.table.name}.{ref.name}: {bad} rows")
    log("foreign keys validated")
