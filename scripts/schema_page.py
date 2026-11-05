"""Write docs/schema.html: every table in registrar/models/ with its columns, keys and real example rows from the database.

    python scripts/schema_page.py                 # reads DATABASE_URL (data/seed loaded), writes docs/schema.html

Columns, types, keys and nullability come from the SQLAlchemy models, so the page follows the schema. The meanings below
are hand-written; a column without one is listed with an empty meaning and a warning on stderr. Example rows are picked
from the loaded data around one story: a CS professor's Spring 2026 section that had a TA, two of its students, their
grades, and the submitted grade roster. Rerun after a schema or data change; the same database gives the same page.
"""
from __future__ import annotations

import argparse
import html
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from registrar.db import DATABASE_URL  # noqa: E402
from registrar.models import Base  # noqa: E402

PREV, CUR, NEXT = "202610", "202680", "202710"

GROUPS = [
    ("People", ["person", "student", "instructor"], "people.py"),
    ("Structure", ["department", "program", "academic_term"], "academic.py"),
    ("Catalog", ["course", "course_prerequisite", "degree_requirement", "program_category_requirement", "lecture"], "catalog.py"),
    ("Grades", ["grade_scale"], "grades.py"),
    ("Records", ["enrollment", "transfer_credit", "lecture_staff", "grade_submission"], "records.py"),
]

NOTES = {
    "person": "One row per human. Students and instructors are profiles hanging off this row with the same key.",
    "student": "Undergraduate or graduate is not stored: it follows from <code>program.degree</code>.",
    "instructor": "A graduate teaching assistant is also a student: one <code>person</code>, one <code>student</code> and one <code>instructor</code> row share the same key.",
    "department": "One row per subject code, because <code>course.subject</code> points here.",
    "program": "A degree program. Which courses it needs is in <code>degree_requirement</code>; how many credits per category in <code>program_category_requirement</code>.",
    "academic_term": "Every date is a policy date. The agent compares the case clock (<code>as_of</code>) against them to decide which term is current and whether a student can still add, drop or withdraw. The current term is not stored.",
    "course": "The catalog. A retired course keeps its row with <code>is_active</code> false.",
    "course_prerequisite": "One row per (course, required course). A course with no rows has no prerequisites. A course cannot require itself (CHECK).",
    "degree_requirement": "One course in a program's degree plan.",
    "program_category_requirement": "Credits a program needs from one category. Core needs no row: its credits are the sum of the required courses.",
    "lecture": "A section: a course offered in a term with one instructor of record and one weekly meeting pattern. CRNs restart at 10001 every term.",
    "grade_scale": "Reference data: the initial migration inserts these 14 rows, not the seed.",
    "enrollment": "One student in one section. A student who repeats a course has one row per attempt.",
    "transfer_credit": "A course accepted from another institution for a transfer student.",
    "lecture_staff": "Who works on a section, and as what. Every section has its instructor of record here; teaching assistants are added with role <code>ta</code>.",
    "grade_submission": "A section whose final grades were submitted. No row means not submitted yet (every Fall 2026 and Spring 2027 section) or no students to grade.",
}

MEANING = {
    "person.university_id": "Nine-digit campus id, e.g. 800123456",
    "person.first_name": "", "person.last_name": "Indexed",
    "person.date_of_birth": "Private: own record only",
    "person.sex": "M, F or X (CHECK)",
    "person.ssn": "Raw, synthetic, as 123-45-6789. Private: own record only",
    "person.phone": "Private: own record only",
    "person.email": "A student's email is private; an instructor's is the public directory entry",
    "student.university_id": "Same value as the person row",
    "student.program_code": "The one major. Indexed.",
    "student.status": "active, leave_of_absence, withdrawn, suspended, dismissed, graduated. Indexed.",
    "student.entry_type": "first_time, transfer, readmit",
    "student.residency": "resident, nonresident, international",
    "student.admit_term_code": "Term the student entered",
    "student.expected_graduation_term_code": "For a graduate, the term they finished",
    "instructor.university_id": "Same value as the person row",
    "instructor.department_code": "Home department. Indexed.",
    "instructor.rank": "Free text: professor, associate, assistant, lecturer, adjunct, ta",
    "instructor.is_active": "False for retired and former instructors",
    "instructor.hire_date": "Private: own record only",
    "instructor.salary": "Annual, whole dollars (a TA's stipend, an adjunct's annual equivalent). Private: own record only",
    "department.code": "CS, ENG, MATH, ...", "department.name": "",
    "program.code": "BSCS, BSENG, MSCS, MSENG", "program.department_code": "Indexed", "program.name": "",
    "program.degree": "BS, MS", "program.total_credits_required": "Credits to graduate", "program.min_gpa": "Minimum GPA to graduate",
    "academic_term.code": "Year + term digits: 202680 = Fall 2026, 202710 = Spring 2027",
    "academic_term.name": "", "academic_term.term_type": "fall, spring, summer", "academic_term.academic_year": "2026 means 2026-27",
    "academic_term.start_date": "First day of classes", "academic_term.end_date": "Last day of finals",
    "academic_term.registration_opens": "", "academic_term.add_deadline": "Last day to add",
    "academic_term.drop_deadline": "Last day to drop without a W", "academic_term.withdraw_deadline": "Last day to withdraw with a W",
    "academic_term.grades_due": "Final grades due from instructors", "academic_term.sequence": "Ordinal for next/last term arithmetic",
    "course.code": "Subject + space + number", "course.subject": "The owning department",
    "course.number": "1110, 2210, ...", "course.title": "", "course.description": "", "course.credit_hours": "",
    "course.level": "lower_division, upper_division, graduate", "course.is_active": "False once retired",
    "course_prerequisite.course_code": "The course being entered", "course_prerequisite.required_course_code": "The course that must be passed first",
    "course_prerequisite.min_grade": "Default C-. Met when the earned grade has at least this many points",
    "course_prerequisite.group_number": "Same group = OR; different groups = AND",
    "degree_requirement.program_code": "", "degree_requirement.course_code": "",
    "degree_requirement.category": "core, elective, general_education",
    "degree_requirement.is_required": "False = one of several options in its category",
    "degree_requirement.suggested_term_number": "1 to 8 in the four-year plan",
    "program_category_requirement.program_code": "", "program_category_requirement.category": "elective, general_education",
    "program_category_requirement.min_credits": "Credits the student must earn from this category",
    "lecture.term_code": "", "lecture.crn": "Course reference number, unique within a term",
    "lecture.course_code": "Indexed", "lecture.section_number": "M01, M02, ...",
    "lecture.instructor_university_id": "The instructor of record. Indexed.",
    "lecture.days": "Subset of MTWRFSU (R = Thursday, U = Sunday)", "lecture.start_time": "", "lecture.end_time": "",
    "lecture.room": "e.g. SH 118", "lecture.capacity": "Seats. Seats taken = the section's non-withdrawn enrollment rows",
    "lecture.is_cancelled": "Cancelled sections are never offered, taught or enrolled in",
    "grade_scale.letter": "A through F, plus W (withdrawn) and I (incomplete)",
    "grade_scale.points": "Grade points per credit hour. Null for W and I",
    "enrollment.term_code": "", "enrollment.crn": "", "enrollment.student_university_id": "Indexed",
    "enrollment.status": "enrolled (in progress or registered), completed (graded), withdrawn (W)",
    "enrollment.grade": "Null while enrolled; W when withdrawn; a letter or I once completed (CHECK status_grade)",
    "transfer_credit.student_university_id": "", "transfer_credit.course_code": "The course here it was accepted as",
    "transfer_credit.credit_hours": "Earns credit and meets prerequisites; no grade, outside the GPA",
    "transfer_credit.accepted_term_code": "The term the credit was posted",
    "lecture_staff.term_code": "", "lecture_staff.crn": "", "lecture_staff.university_id": "Indexed",
    "lecture_staff.role": "instructor or ta (CHECK)",
    "grade_submission.term_code": "", "grade_submission.crn": "",
    "grade_submission.submitted_by": "The instructor of record. Indexed.",
    "grade_submission.submitted_at": "UTC. About 8% arrive one to three days after grades_due",
}


def cell(v) -> str:
    if v is None:
        return '<td class="null">null</td>'
    if isinstance(v, bool):
        v = "true" if v else "false"
    elif isinstance(v, time):
        v = v.strftime("%H:%M")
    elif isinstance(v, datetime):
        v = v.strftime("%Y-%m-%d %H:%M UTC")
    elif isinstance(v, (date, Decimal)):
        v = str(v)
    return f"<td>{html.escape(str(v))}</td>"


def keys_of(table, col) -> str:
    tags = []
    if col.primary_key:
        tags.append('<span class="tag pk">PK</span>')
    for fk in col.foreign_keys:
        tags.append(f'<span class="tag fk">FK {fk.column.table.name}</span>')
    for c in table.constraints:
        if type(c).__name__ == "ForeignKeyConstraint" and col.name in [x.name for x in c.columns] and len(c.columns) > 1:
            target = list(c.elements)[0].column.table.name
            tag = f'<span class="tag fk">FK {target}</span>'
            if tag not in tags:
                tags.append(tag)
    if col.unique:
        tags.append('<span class="tag uq">UNIQUE</span>')
    for c in table.constraints:
        if type(c).__name__ == "UniqueConstraint" and col.name in [x.name for x in c.columns] and len(c.columns) > 1:
            others = [x.name for x in c.columns if x.name != col.name]
            tags.append(f'<span class="tag uq">UNIQUE with {", ".join(others)}</span>')
    return " ".join(tags)


def type_of(col) -> str:
    try:
        t = col.type.compile(dialect=postgresql.dialect())
    except Exception:  # noqa: BLE001
        t = str(col.type)
    t = t.lower().replace("character varying", "varchar").replace("timestamp with time zone", "timestamptz")
    return t + ("" if col.nullable is False or col.primary_key else ", null")


def fetch(cur, sql, **p):
    cur.execute(sql, p or None)
    return cur.fetchall()


def pick_story(cur) -> dict:
    """One CS professor's Spring 2026 section with a TA and graded students; everything else hangs off it."""
    sec = fetch(cur, """
        SELECT l.*, s.university_id AS ta FROM lecture l
        JOIN lecture_staff s ON s.term_code = l.term_code AND s.crn = l.crn AND s.role = 'ta'
        JOIN instructor i ON i.university_id = l.instructor_university_id
        JOIN grade_submission g ON g.term_code = l.term_code AND g.crn = l.crn
        WHERE l.term_code = %(t)s AND i.rank IN ('professor', 'associate', 'assistant')
          AND (SELECT COUNT(*) FROM enrollment e WHERE e.term_code = l.term_code AND e.crn = l.crn) >= 10
        ORDER BY i.department_code <> 'CS', i.rank <> 'professor', l.crn LIMIT 1""", t=PREV)[0]
    unique = """NOT EXISTS (SELECT 1 FROM person p2 WHERE p2.first_name = p.first_name AND p2.last_name = p.last_name
                AND p2.university_id <> p.university_id)"""
    studs = [r["student_university_id"] for r in fetch(cur, f"""
        SELECT e.student_university_id FROM enrollment e JOIN person p ON p.university_id = e.student_university_id
        JOIN student s ON s.university_id = e.student_university_id
        WHERE e.term_code = %(t)s AND e.crn = %(c)s AND e.status = 'completed' AND s.status = 'active' AND {unique}
          AND EXISTS (SELECT 1 FROM enrollment f WHERE f.student_university_id = e.student_university_id AND f.term_code = %(now)s)
        ORDER BY e.student_university_id LIMIT 2""", t=PREV, c=sec["crn"], now=CUR)]
    transfer = fetch(cur, "SELECT student_university_id FROM transfer_credit ORDER BY 1 LIMIT 1")[0]["student_university_id"]
    return dict(sec=sec, prof=sec["instructor_university_id"], ta=sec["ta"], students=studs, transfer=transfer)


def examples(cur, s: dict) -> tuple[dict[str, list[dict]], dict[str, str]]:
    sec, prof, ta, studs = s["sec"], s["prof"], s["ta"], s["students"]
    people = [prof, ta] + studs
    course = sec["course_code"]
    ex = {
        "person": fetch(cur, "SELECT * FROM person WHERE university_id = ANY(%(u)s) ORDER BY array_position(%(u)s, university_id)", u=people),
        "student": fetch(cur, "SELECT * FROM student WHERE university_id = ANY(%(u)s) ORDER BY array_position(%(u)s, university_id)", u=[ta] + studs),
        "instructor": fetch(cur, "SELECT * FROM instructor WHERE university_id = ANY(%(u)s) ORDER BY array_position(%(u)s, university_id)", u=[prof, ta]),
        "department": fetch(cur, "SELECT * FROM department WHERE code IN ('CS', 'ENG', 'MATH') ORDER BY code"),
        "program": fetch(cur, "SELECT * FROM program ORDER BY code"),
        "academic_term": fetch(cur, "SELECT * FROM academic_term WHERE code IN (%(a)s, %(b)s, %(c)s) ORDER BY sequence", a=PREV, b=CUR, c=NEXT),
        "course": fetch(cur, """SELECT * FROM course WHERE code = %(c)s OR code IN (SELECT required_course_code FROM course_prerequisite
                                WHERE course_code = %(c)s) ORDER BY code LIMIT 3""", c=course),
        "course_prerequisite": fetch(cur, "SELECT * FROM course_prerequisite WHERE course_code = %(c)s ORDER BY group_number, required_course_code", c=course),
        "degree_requirement": fetch(cur, """SELECT * FROM degree_requirement WHERE program_code = 'BSCS' AND (course_code = %(c)s OR is_required = false)
                                         ORDER BY is_required DESC, course_code LIMIT 3""", c=course),
        "program_category_requirement": fetch(cur, "SELECT * FROM program_category_requirement WHERE program_code = 'BSCS' ORDER BY category"),
        "lecture": fetch(cur, """SELECT * FROM lecture WHERE (term_code = %(t)s AND crn = %(c)s)
                                 OR (term_code = %(now)s AND instructor_university_id = %(p)s) ORDER BY term_code, crn LIMIT 3""",
                         t=PREV, c=sec["crn"], now=CUR, p=prof),
        "grade_scale": fetch(cur, "SELECT * FROM grade_scale WHERE letter IN ('A', 'B+', 'C-', 'F', 'W', 'I') ORDER BY points DESC NULLS LAST, letter"),
        "enrollment": fetch(cur, """(SELECT * FROM enrollment WHERE term_code = %(t)s AND crn = %(c)s AND student_university_id = ANY(%(u)s))
                                    UNION ALL (SELECT * FROM enrollment WHERE term_code = %(now)s AND student_university_id = %(s0)s ORDER BY crn LIMIT 1)
                                    ORDER BY term_code, crn, student_university_id""", t=PREV, c=sec["crn"], u=studs, now=CUR, s0=studs[0]),
        "transfer_credit": fetch(cur, "SELECT * FROM transfer_credit WHERE student_university_id = %(u)s ORDER BY course_code LIMIT 2", u=s["transfer"]),
        "lecture_staff": fetch(cur, "SELECT * FROM lecture_staff WHERE term_code = %(t)s AND crn = %(c)s ORDER BY role <> 'instructor'", t=PREV, c=sec["crn"]),
        "grade_submission": fetch(cur, "SELECT * FROM grade_submission WHERE term_code = %(t)s AND crn = %(c)s", t=PREV, c=sec["crn"]),
    }
    name = {p["university_id"]: f'{p["first_name"]} {p["last_name"]}' for p in ex["person"]}
    title = fetch(cur, "SELECT title FROM course WHERE code = %(c)s", c=course)[0]["title"]
    n = fetch(cur, "SELECT COUNT(*) AS n FROM enrollment WHERE term_code = %(t)s AND crn = %(c)s", t=PREV, c=sec["crn"])[0]["n"]
    sub = ex["grade_submission"][0]
    due = fetch(cur, "SELECT grades_due FROM academic_term WHERE code = %(t)s", t=PREV)[0]["grades_due"]
    grades = {e["student_university_id"]: e["grade"] for e in ex["enrollment"] if e["term_code"] == PREV}
    rank = {"professor": "a professor", "associate": "an associate professor", "assistant": "an assistant professor"}
    prof_rank = rank.get(next(i["rank"] for i in ex["instructor"] if i["university_id"] == prof), "an instructor")
    reads = {
        "person": f"{name[prof]} is {prof_rank} of {sec['course_code'].split()[0]}, {name[ta]} a graduate student who also works as a TA, "
                  f"{' and '.join(name[u] for u in studs)} undergraduates. Their example rows follow them through every table below.",
        "lecture": f"In Spring 2026, {name[prof]} taught {course} ({html.escape(title)}) as CRN {sec['crn']}, section {sec['section_number']}, "
                   f"{sec['days']} {sec['start_time']:%H:%M}-{sec['end_time']:%H:%M} in {sec['room']}, {n} students for {sec['capacity']} seats.",
        "enrollment": f"{name[studs[0]]} earned {grades.get(studs[0])} and {name[studs[1]]} {grades.get(studs[1])} in that section; "
                      f"{name[studs[0]]} is enrolled again this fall, with no grade yet.",
        "lecture_staff": f"The section's staff: {name[prof]} as instructor and {name[ta]} as TA.",
        "grade_submission": f"{name[prof]} submitted the section's grades on {sub['submitted_at']:%Y-%m-%d %H:%M} UTC; grades were due {due}.",
        "course_prerequisite": "Rows in the same group are alternatives (OR); different groups are all required (AND).",
        "grade_scale": "\"C- or better\" means at least 1.7 points. GPA = sum(points x credit hours) / sum(credit hours) over rows with points; F, W and I earn no credit.",
    }
    return ex, reads


def render(counts: dict[str, int], ex: dict, reads: dict) -> str:
    tables = Base.metadata.tables
    missing = [t for t in tables if t not in {n for _, names, _ in GROUPS for n in names}]
    if missing:
        print(f"warning: tables not in GROUPS: {missing}", file=sys.stderr)
    total = sum(counts.values())
    nav = "\n".join(f'    <span class="group">{g}</span>' + "".join(f'<a href="#{n}">{n}</a>' for n in names) for g, names, _ in GROUPS)
    sections = []
    for _, names, file in GROUPS:
        for name in names:
            t = tables[name]
            rows = []
            for col in t.columns:
                key = f"{name}.{col.name}"
                if key not in MEANING:
                    print(f"warning: no meaning for {key}", file=sys.stderr)
                rows.append(f'      <tr><td class="col">{col.name}</td><td class="type">{type_of(col)}</td><td>{keys_of(t, col)}</td>'
                            f'<td>{MEANING.get(key, "")}</td></tr>')
            cols = [c.name for c in t.columns]
            exrows = "".join("      <tr>" + "".join(cell(r[c]) for c in cols) + "</tr>\n" for r in ex.get(name, []))
            read = f'\n    <div class="rule">Read: {reads[name]}</div>' if name in reads else ""
            sections.append(f"""  <section class="table" id="{name}">
    <div class="head"><h2>{name}</h2><span class="file">{file}</span><span class="count">{counts[name]:,} rows</span></div>
    <p class="note">{NOTES.get(name, "")}</p>
    <div class="scroll"><table>
      <tr><th>Column</th><th>Type</th><th>Key</th><th>Meaning</th></tr>
{chr(10).join(rows)}
    </table></div>
    <h3>Example rows</h3>
    <div class="scroll"><table class="ex">
      <tr>{"".join(f"<th>{c}</th>" for c in cols)}</tr>
{exrows}    </table></div>{read}
  </section>""")
    return TEMPLATE.replace("{{N}}", str(len(tables))).replace("{{TOTAL}}", f"{total:,}").replace("{{NAV}}", nav) \
        .replace("{{SECTIONS}}", "\n\n".join(sections))


TEMPLATE = """<title>Registrar Schema</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one column of reference cards with a table index; each table = definition grid + real example rows */
:root {
  --bg: #f7f6f2; --surface: #ffffff; --fg: #1d1f24; --muted: #5d6270; --line: #d9d7cf;
  --accent: #1f5f8b; --accent-soft: #e4eef5; --pk: #8a4b12; --pk-soft: #f6e9da; --fk: #2f6b3a; --fk-soft: #e2f0e4;
  --display: "Source Serif 4", Georgia, serif;
  --body: "IBM Plex Sans", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #15171c; --surface: #1d2027; --fg: #e8e6e0; --muted: #a0a4ad; --line: #353943;
  --accent: #7fb4dc; --accent-soft: #223544; --pk: #e3a568; --pk-soft: #3d2d1c; --fk: #8fcf9b; --fk-soft: #1f3524;
  color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #15171c; --surface: #1d2027; --fg: #e8e6e0; --muted: #a0a4ad; --line: #353943;
  --accent: #7fb4dc; --accent-soft: #223544; --pk: #e3a568; --pk-soft: #3d2d1c; --fk: #8fcf9b; --fk-soft: #1f3524;
  color-scheme: dark; }

body { background: var(--bg); color: var(--fg); font-family: var(--body); font-size: 15px; line-height: 1.5;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 32px 64px; }
.wrap { max-width: 1040px; margin: 0 auto; display: grid; gap: 28px; }
h1 { font-family: var(--display); font-weight: 600; font-size: 2rem; margin: 0; text-wrap: balance; }
h2 { font-family: var(--display); font-weight: 600; font-size: 1.35rem; margin: 0; }
h3 { font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin: 0; }
p { margin: 0; max-width: 68ch; }
.lead { color: var(--muted); }
code { font-family: var(--mono); font-size: 0.9em; }
nav { display: flex; flex-wrap: wrap; gap: 8px 14px; font-size: 0.85rem; padding: 12px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
nav a { color: var(--accent); text-decoration: none; font-family: var(--mono); }
nav a:hover, nav a:focus-visible { text-decoration: underline; outline: none; }
.group { font-size: 0.75rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-right: 6px; }
.legend { display: flex; flex-wrap: wrap; gap: 10px 18px; font-size: 0.85rem; color: var(--muted); align-items: center; }
.tag { display: inline-block; font-family: var(--mono); font-size: 0.7rem; font-weight: 500; padding: 1px 6px; border-radius: 3px; letter-spacing: 0.04em; white-space: nowrap; }
.tag.pk { background: var(--pk-soft); color: var(--pk); }
.tag.fk { background: var(--fk-soft); color: var(--fk); }
.tag.uq { background: var(--accent-soft); color: var(--accent); }
section.table { background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 20px 22px; display: grid; gap: 16px; scroll-margin-top: 16px; min-width: 0; }
.head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 14px; }
.head .file, .head .count { font-family: var(--mono); font-size: 0.8rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.scroll { overflow-x: auto; min-width: 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.875rem; }
th { text-align: left; font-weight: 600; font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); padding: 6px 10px 6px 0; border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 6px 14px 6px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
tr:last-child td { border-bottom: none; }
td.col { font-family: var(--mono); white-space: nowrap; }
td.type { font-family: var(--mono); color: var(--muted); white-space: nowrap; font-size: 0.8rem; }
.ex td { font-family: var(--mono); font-size: 0.8rem; white-space: nowrap; font-variant-numeric: tabular-nums; }
.ex td.null { color: var(--muted); font-style: italic; }
.note { font-size: 0.875rem; color: var(--muted); max-width: 72ch; }
.rule { background: var(--accent-soft); border-left: 3px solid var(--accent); padding: 8px 12px; font-size: 0.875rem; max-width: 72ch; }
footer { font-size: 0.8rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: 14px; }
@media (max-width: 520px) { section.table { padding: 16px 14px; } h1 { font-size: 1.6rem; } }
</style>

<div class="wrap">
  <header style="display:grid;gap:10px">
    <h1>Registrar schema</h1>
    <p class="lead">{{N}} tables in <code>registrar/models/</code>, PostgreSQL 18, {{TOTAL}} rows in <code>data/seed/</code>. Natural keys throughout: a human is a <code>university_id</code>, a course is its catalog code, a term is its six-digit code, a section is term plus CRN. The example rows are real rows from the dataset (every value is synthetic) and follow the same people across tables.</p>
    <div class="legend">
      <span><span class="tag pk">PK</span> primary key</span>
      <span><span class="tag fk">FK</span> foreign key, must match a row in the named table</span>
      <span><span class="tag uq">UNIQUE</span> no two rows share the value</span>
      <span><code>, null</code> after a type: the column may be empty. Enum columns are VARCHAR with a CHECK constraint.</span>
    </div>
  </header>

  <nav>
{{NAV}}
  </nav>

{{SECTIONS}}

  <footer>Generated by <code>scripts/schema_page.py</code> from <code>registrar/models/*.py</code> and the loaded <code>data/seed/</code>; rerun it after a schema or data change. The schema section of <code>README.md</code> holds the rules behind the data.</footer>
</div>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/schema.html")
    args = ap.parse_args()
    dsn = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        counts = {t: fetch(cur, f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in Base.metadata.tables}
        ex, reads = examples(cur, pick_story(cur))
    Path(args.out).write_text(render(counts, ex, reads))
    print(f"wrote {args.out}: {len(Base.metadata.tables)} tables, {sum(counts.values()):,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
