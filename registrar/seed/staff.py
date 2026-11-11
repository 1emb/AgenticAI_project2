"""Instructor salaries, section staff (instructor of record plus teaching assistants) and grade submissions (added 2026-11-05).

Each function has its own random stream, so none of them moves a row of another table.
- Salary: a static annual amount by rank, with a premium for CS and ENG, rounded to $100. A TA's is the stipend, an adjunct's
  the annual equivalent of their course pay. Own record only: no one sees another instructor's salary.
- Section staff: every section's instructor of record with role `instructor`; each TA assists TA_SECTIONS lower-division
  sections of their department per term, from their first term on, never one they teach and never at a time they teach or
  sit in a class themselves.
- Grade submission: one row per section with students in a graded term (up to LATEST_GRADED_TERM), by the instructor of record,
  usually in the days before the term's grades_due date, sometimes a day or three late. Fall 2026 and Spring 2027 have none.
"""
from __future__ import annotations

import random
from datetime import datetime, time, timedelta, timezone

from .records import LATEST_GRADED_TERM, overlaps

SALARY = {"professor": (118_000, 168_000), "associate": (92_000, 124_000), "assistant": (80_000, 99_000),
          "lecturer": (56_000, 74_000), "adjunct": (28_000, 42_000), "ta": (18_000, 24_000)}
SALARY_PREMIUM = {"CS": 1.10, "ENG": 1.08}
TA_SECTIONS = 2
LATE_RATE = 0.08


def salaries(seed: int, instructors: list[dict]) -> None:
    """Sets `salary` on every instructor row, in university-id order."""
    rng = random.Random(f"{seed}-salary")
    for ins in sorted(instructors, key=lambda r: r["university_id"]):
        lo, hi = SALARY[ins["rank"]]
        base = rng.uniform(lo, hi) * SALARY_PREMIUM.get(ins["department_code"], 1.0)
        ins["salary"] = int(round(base / 100.0)) * 100


def staff_rows(seed: int, lectures: list[dict], instructors: list[dict], enrollment: list[dict], terms: list[dict]) -> list[dict]:
    rng = random.Random(f"{seed}-staff")
    rows = [dict(term_code=l["term_code"], crn=l["crn"], university_id=l["instructor_university_id"], role="instructor") for l in lectures]
    start = {t["code"]: t["start_date"] for t in terms}
    by_key = {(l["term_code"], l["crn"]): l for l in lectures}

    def slot(l: dict) -> tuple:
        return (l["days"], l["start_time"], l["end_time"])

    sits: dict[tuple[str, str], list[tuple]] = {}            # (person, term) -> class times they sit in as a student
    for e in enrollment:
        if e["status"] != "withdrawn":
            sits.setdefault((e["student_university_id"], e["term_code"]), []).append(slot(by_key[(e["term_code"], e["crn"])]))
    term_codes = sorted({l["term_code"] for l in lectures})
    for ta in sorted((i for i in instructors if i["rank"] == "ta"), key=lambda r: r["university_id"]):
        uid = ta["university_id"]
        for term in term_codes:
            if start[term] < ta["hire_date"]:
                continue
            mine = [l for l in lectures if l["term_code"] == term]
            busy = [slot(l) for l in mine if l["instructor_university_id"] == uid] + sits.get((uid, term), [])
            options = [l for l in mine if l["course_code"].split()[0] == ta["department_code"]
                       and l["course_code"].split()[1][0] in "12" and not l["is_cancelled"]
                       and l["instructor_university_id"] != uid]
            rng.shuffle(options)
            picked = 0
            for l in options:
                if picked == TA_SECTIONS:
                    break
                if any(overlaps(slot(l), b) for b in busy):
                    continue
                rows.append(dict(term_code=term, crn=l["crn"], university_id=uid, role="ta"))
                busy.append(slot(l))
                picked += 1
    rows.sort(key=lambda r: (r["term_code"], int(r["crn"]), r["role"] != "instructor", r["university_id"]))
    return rows


def submission_rows(seed: int, lectures: list[dict], enrollment: list[dict], terms: list[dict]) -> list[dict]:
    rng = random.Random(f"{seed}-submission")
    due = {t["code"]: t["grades_due"] for t in terms}
    with_students = {(e["term_code"], e["crn"]) for e in enrollment}
    rows = []
    for l in sorted(lectures, key=lambda l: (l["term_code"], int(l["crn"]))):
        key = (l["term_code"], l["crn"])
        if l["term_code"] > LATEST_GRADED_TERM or l["is_cancelled"] or key not in with_students:
            continue
        days = rng.randint(1, 3) if rng.random() < LATE_RATE else -rng.randint(0, 4)
        day = due[l["term_code"]] + timedelta(days=days)
        local = datetime.combine(day, time(rng.randint(8, 22), rng.choice([0, 15, 30, 45])))
        # entered in Mountain time (December: MST, UTC-7; May: MDT, UTC-6) and stored in UTC
        offset = 6 if day.month == 5 else 7
        rows.append(dict(term_code=l["term_code"], crn=l["crn"], submitted_by=l["instructor_university_id"],
                         submitted_at=(local + timedelta(hours=offset)).replace(tzinfo=timezone.utc).isoformat()))
    return rows


def advisor_rows(students: list[dict], instructors: list[dict], programs: list[dict]) -> list[dict]:
    """One advisor per student (2026-11-11, from Duong's advising-agent branch): the active instructors of the
    department that runs the student's program, TAs left out, handed out in turn in university-ID order. No random
    draw, so adding this table changes no other row."""
    dept_of = {p["code"]: p["department_code"] for p in programs}
    pool: dict[str, list[str]] = {}
    for i in sorted(instructors, key=lambda i: i["university_id"]):
        if i["is_active"] and i["rank"] != "ta":
            pool.setdefault(i["department_code"], []).append(i["university_id"])
    turn: dict[str, int] = {}
    out = []
    for st in sorted(students, key=lambda s: s["university_id"]):
        dept = dept_of[st["program_code"]]
        n = turn.get(dept, 0)
        out.append({"student_university_id": st["university_id"], "advisor_university_id": pool[dept][n % len(pool[dept])]})
        turn[dept] = n + 1
    return out
