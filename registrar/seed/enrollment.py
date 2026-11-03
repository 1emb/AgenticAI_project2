"""Synthetic enrollment history and advisor assignment, generated from the frozen seed CSVs (data/seed/).

Deterministic (seed 7): same input CSVs -> same output, byte for byte. Rules, per student, term by term from the
admit term:
- Courses come from the student's degree plan in suggested-term order, then category courses until each category
  minimum is met, then free electives (any active undergraduate course whose prerequisites are met) up to the program total.
- A course is taken only when every prerequisite group is met by an earlier grade at or above its minimum, and, in
  terms with lecture rows (Fall 2024 on), only in a non-cancelled section with a free seat that does not
  overlap the student's other sections that term. Earlier terms have no
  sections (crn null).
- Grades come from a per-student ability, the student's status, the course level, and an occasional bad
  outcome in one course (more often for weak students). A grade below a prerequisite
  minimum, or an F, puts the course back on the list (repeat). About 3% of enrollments end in W.
- Graded history ends with Spring 2026. Fall 2026 is in progress at the test sets' default clock (2026-11-20), so
  active students are enrolled in Fall 2026 with no grade. Spring 2027 registration is open with no rows yet, as the
  test sets assume.
- Status shapes the history: graduated students finish their requirements (with loads up to 21 credits when the
  seed's admit term leaves few terms); dismissed and suspended students have low
  ability and stop after a weak term; withdrawn and leave-of-absence students stop early.
"""
from __future__ import annotations

import csv
import random
from collections import defaultdict
from pathlib import Path

GRADES = [("A", 4.0), ("A-", 3.7), ("B+", 3.3), ("B", 3.0), ("B-", 2.7), ("C+", 2.3), ("C", 2.0), ("C-", 1.7),
          ("D+", 1.3), ("D", 1.0), ("D-", 0.7), ("F", 0.0)]
POINTS = dict(GRADES) | {"W": None, "I": None}
LAST_GRADED = "202610"  # Spring 2026
CURRENT = "202680"  # Fall 2026, in progress at the default clock
ABILITY = {"graduated": 0.6, "active": 0.0, "suspended": -1.6, "dismissed": -2.0, "withdrawn": -0.6,
           "leave_of_absence": -0.2}


def _read(d: Path, name: str) -> list[dict]:
    return list(csv.DictReader((d / f"{name}.csv").open()))


def _minutes(t: str) -> int:
    h, m = t.split(":")[:2]
    return int(h) * 60 + int(m)


def _overlap(a: dict, b: dict) -> bool:
    return bool(set(a["days"]) & set(b["days"])) and _minutes(a["start_time"]) < _minutes(b["end_time"]) \
        and _minutes(b["start_time"]) < _minutes(a["end_time"])


def _letter(p: float) -> str:
    return min(GRADES, key=lambda g: abs(g[1] - p))[0]


def generate(seed_dir: Path, seed: int = 7) -> tuple[list[dict], list[dict]]:
    rnd = random.Random(seed)
    terms = sorted(_read(seed_dir, "academic_term"), key=lambda t: int(t["sequence"]))
    seq = {t["code"]: int(t["sequence"]) for t in terms}
    courses = {c["code"]: c for c in _read(seed_dir, "course")}
    credit = {c: float(r["credit_hours"]) for c, r in courses.items()}
    active_course = {c for c, r in courses.items() if r["is_active"] == "true"}
    prereq: dict[str, dict[int, list[tuple[str, float]]]] = defaultdict(lambda: defaultdict(list))
    for p in _read(seed_dir, "course_prerequisite"):
        prereq[p["course_code"]][int(p["group_number"])].append((p["required_course_code"], POINTS[p["min_grade"]]))
    plans: dict[str, list[dict]] = defaultdict(list)
    for r in _read(seed_dir, "degree_requirement"):
        plans[r["program_code"]].append(r)
    cat_min: dict[str, dict[str, int]] = defaultdict(dict)
    for r in _read(seed_dir, "program_category_requirement"):
        cat_min[r["program_code"]][r["category"]] = int(r["min_credits"])
    programs = {p["code"]: p for p in _read(seed_dir, "program")}
    lectures: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for l in _read(seed_dir, "lecture"):
        if l["is_cancelled"] != "true":
            lectures[(l["term_code"], l["course_code"])].append(l)
    lecture_terms = {t for t, _ in lectures}
    seats: dict[tuple[str, str], int] = defaultdict(int)
    free_electives = sorted(c for c in active_course if courses[c]["level"] != "graduate")  # ok() checks prereqs

    enroll: list[dict] = []
    students = sorted(_read(seed_dir, "student"), key=lambda s: s["university_id"])
    for st in students:
        uid, prog, status = st["university_id"], st["program_code"], st["status"]
        plan = sorted(plans[prog], key=lambda r: (r["is_required"] != "true", int(r["suggested_term_number"] or 9),
                                                  r["course_code"]))
        in_plan = {r["course_code"]: r for r in plan}
        degree = programs[prog]["degree"]
        total = float(programs[prog]["total_credits_required"])
        target_load = 9.0 if degree == "MS" else 15.0
        ability = ABILITY.get(status, 0.0) + rnd.gauss(0, 0.6)
        best: dict[str, float] = {}
        if degree == "MS":  # MS admits bring their undergraduate prerequisites (see the advising policy switch)
            for c, r in courses.items():
                if r["level"] != "graduate" and c not in in_plan:
                    best.setdefault(c, 4.0)
            ms_waived = set(best)
        else:
            ms_waived = set()
        start = seq[st["admit_term_code"]]
        stop_after = None
        if status in ("withdrawn", "leave_of_absence"):
            stop_after = start + rnd.randint(0, 3)
        terms_done = 0

        def earned() -> float:
            return sum(credit[c] for c, p in best.items() if p > 0 and c not in ms_waived)

        def needed(c: str) -> bool:
            p = best.get(c, -1)
            if p <= 0:
                return True
            return any(p < m for g in prereq.values() for alts in g.values() for r, m in alts if r == c)

        for t in terms:
            code = t["code"]
            if seq[code] < start or seq[code] > seq[CURRENT]:
                continue
            if stop_after is not None and seq[code] > stop_after:
                break
            graded = seq[code] <= seq[LAST_GRADED]
            cats = {k: sum(credit[c] for c, p in best.items() if p > 0 and in_plan.get(c, {}).get("category") == k)
                    for k in cat_min[prog]}
            if status == "graduated" and all(not needed(r["course_code"]) for r in plan if r["is_required"] == "true") \
                    and all(cats[k] >= v for k, v in cat_min[prog].items()) and earned() >= total:
                break
            if status == "active" and earned() >= total and terms_done >= 2:
                break  # finished early; nothing left to take
            if status in ("graduated",) and not graded:
                break

            def ok(c: str) -> bool:
                if c not in active_course or not needed(c):
                    return False
                if any(not any(best.get(r, -1) >= m for r, m in alts) for alts in prereq.get(c, {}).values()):
                    return False
                if degree == "BS" and courses[c]["level"] == "graduate":
                    return False
                return True

            pick: list[str] = []
            chosen: list[dict] = []  # sections already taken this term: no two may meet at the same time (7.5)
            load = 0.0
            if status == "graduated":  # finish by Spring 2026: spread what is left over the graded terms left
                left = sum(1 for x in terms if seq[code] <= seq[x["code"]] <= seq[LAST_GRADED])
                target_load = min(21.0, max(15.0, (total - earned()) / max(1, left) + 1))
            cand = [r["course_code"] for r in plan if r["is_required"] == "true"]
            for k, v in cat_min[prog].items():
                if cats[k] < v:
                    opts = [r["course_code"] for r in plan if r["category"] == k and r["is_required"] != "true"]
                    rnd.shuffle(opts)
                    cand += opts
            if earned() < total:  # free electives last: they fill a load only after every plan course that fits
                fe = list(free_electives)
                rnd.shuffle(fe)
                cand += fe
            for c in cand:
                if load >= target_load or c in pick or not ok(c):
                    continue
                crn = None
                if code in lecture_terms:
                    open_secs = [l for l in lectures.get((code, c), []) if seats[(code, l["crn"])] < int(l["capacity"])
                                 and not any(_overlap(l, o) for o in chosen)]
                    if not open_secs:
                        continue
                    sec = rnd.choice(open_secs)
                    crn = sec["crn"]
                    chosen.append(sec)
                    seats[(code, crn)] += 1
                pick.append(c)
                load += credit[c]
                row = {"student_university_id": uid, "term_code": code, "course_code": c, "crn": crn}
                if not graded:
                    row.update(status="enrolled", grade=None)
                elif rnd.random() < 0.03:
                    row.update(status="withdrawn", grade="W")
                else:
                    lvl = {"lower_division": 0.0, "upper_division": 0.25, "graduate": 0.35}[courses[c]["level"]]
                    p = 3.0 + 0.7 * ability - lvl + rnd.gauss(0, 0.55)
                    if rnd.random() < 0.04 * (1 + max(0.0, -ability)) and status != "graduated":
                        p -= 2.2  # a bad term in one course: the source of Ds and Fs
                    p = max(0.0, min(4.0, p))
                    letter = _letter(p)
                    row.update(status="enrolled", grade=letter)
                    best[c] = max(best.get(c, -1), POINTS[letter])
                enroll.append(row)
            terms_done += 1
            if status in ("dismissed", "suspended") and terms_done >= 2 and graded:
                term_pts = [POINTS[r["grade"]] for r in enroll[-len(pick):] if r["grade"] not in (None, "W")] if pick else []
                if term_pts and sum(term_pts) / len(term_pts) < 2.0:
                    break

    instructors = _read(seed_dir, "instructor")
    by_dept: dict[str, list[str]] = defaultdict(list)
    for i in sorted(instructors, key=lambda i: i["university_id"]):
        if i["is_active"] == "true" and i["rank"] != "ta":
            by_dept[i["department_code"]].append(i["university_id"])
    advisors: list[dict] = []
    counter: dict[str, int] = defaultdict(int)
    for st in students:
        dept = programs[st["program_code"]]["department_code"]
        pool = by_dept[dept]
        advisors.append({"student_university_id": st["university_id"],
                         "advisor_university_id": pool[counter[dept] % len(pool)]})
        counter[dept] += 1
    return enroll, advisors


COLUMNS = {"enrollment": ["student_university_id", "term_code", "course_code", "crn", "status", "grade"],
           "advisor_assignment": ["student_university_id", "advisor_university_id"]}


def write(out_dir: Path, enroll: list[dict], advisors: list[dict]) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("enrollment", enroll), ("advisor_assignment", advisors)):
        with open(out_dir / f"{name}.csv", "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(COLUMNS[name])
            for r in rows:
                w.writerow(["" if r[c] is None else r[c] for c in COLUMNS[name]])
    return {"enrollment": len(enroll), "advisor_assignment": len(advisors)}


def load(dsn: str, in_dir: Path) -> dict[str, int]:
    import psycopg
    counts = {}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE enrollment, advisor_assignment")
        for name, cols in COLUMNS.items():
            with open(in_dir / f"{name}.csv", "rb") as f, cur.copy(
                    f"COPY {name} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')") as copy:
                while chunk := f.read(65536):
                    copy.write(chunk)
            cur.execute(f"SELECT COUNT(*) FROM {name}")
            counts[name] = cur.fetchone()[0]
        conn.commit()
    return counts
