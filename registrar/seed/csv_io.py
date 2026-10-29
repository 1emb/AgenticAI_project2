"""CSV files for the dataset: one file per table in data/seed/, and a COPY loader for Postgres."""
from __future__ import annotations

import csv
from pathlib import Path

import psycopg

# Load order respects foreign keys. grade_scale is not here: the initial migration inserts it.
TABLES: dict[str, list[str]] = {
    "department": ["code", "name"],
    "program": ["code", "department_code", "name", "degree", "total_credits_required", "min_gpa"],
    "academic_term": ["code", "name", "term_type", "academic_year", "start_date", "end_date", "registration_opens",
                      "add_deadline", "drop_deadline", "withdraw_deadline", "grades_due", "sequence"],
    "person": ["university_id", "first_name", "last_name", "date_of_birth", "sex", "ssn", "phone", "email"],
    "student": ["university_id", "program_code", "status", "entry_type", "residency", "admit_term_code", "expected_graduation_term_code"],
    "instructor": ["university_id", "department_code", "rank", "is_active", "hire_date"],
    "course": ["code", "subject", "number", "title", "description", "credit_hours", "level", "is_active"],
    "course_prerequisite": ["course_code", "required_course_code", "min_grade", "group_number"],
    "degree_requirement": ["program_code", "course_code", "category", "is_required", "suggested_term_number"],
    "program_category_requirement": ["program_code", "category", "min_credits"],
    "lecture": ["term_code", "crn", "course_code", "section_number", "instructor_university_id", "days", "start_time",
                "end_time", "room", "capacity", "is_cancelled"],
}


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def write_all(out_dir: Path, data: dict[str, list[dict]]) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for table, cols in TABLES.items():
        rows = data[table]
        with open(out_dir / f"{table}.csv", "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(cols)
            for r in rows:
                w.writerow([_cell(r[c]) for c in cols])
        counts[table] = len(rows)
    return counts


def load_all(dsn: str, in_dir: Path) -> dict[str, int]:
    """Empty the eleven tables and COPY the CSVs in, in foreign-key order. Foreign keys and CHECKs are enforced by Postgres."""
    counts = {}
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
            for table, cols in TABLES.items():
                path = in_dir / f"{table}.csv"
                with open(path, "rb") as f, cur.copy(
                        f"COPY {table} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')") as copy:
                    while chunk := f.read(65536):
                        copy.write(chunk)
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cur.fetchone()[0]
        conn.commit()
    return counts
