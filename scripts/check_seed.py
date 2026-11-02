"""Check the loaded dataset's enrollment invariants (the rules in registrar/seed/records.py) and print a profile.

    python scripts/check_seed.py          # exit 1 when an invariant fails

Invariants: no enrollment in a cancelled section; one section per course per student per term; no overlapping sections in a
student's term (a TA's taught sections included); no section over capacity; prerequisites met by an earlier grade or transfer
credit at the time of enrollment (presumed for master's students; Spring 2027 counts Fall 2026 in-progress work); Fall 2026 and
Spring 2027 rows are 'enrolled' with no grade and every earlier row is graded or W; every active student is enrolled in Fall
2026 and nobody else is; graduated students meet every requirement with a GPA at or above the program minimum and have no row
after their graduation term; suspended and dismissed students sit below the minimum; withdrawn, on-leave, suspended and dismissed
students have no row in or after the current term except W rows in their first term; transfer credit only for transfer students.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from registrar.db import DATABASE_URL  # noqa: E402

DSN = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
CURRENT, NEXT = "202680", "202710"


def rows(cur, sql, **p):
    cur.execute(sql, p or None)
    return cur.fetchall()


def overlaps(a, b):
    return bool(set(a[0]) & set(b[0])) and a[1] < b[2] and b[1] < a[2]


def main() -> int:
    problems: list[str] = []
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        terms = {t["code"]: t for t in rows(cur, "SELECT * FROM academic_term")}
        seq = {c: t["sequence"] for c, t in terms.items()}
        cur_seq = seq[CURRENT]
        points = {g["letter"]: (float(g["points"]) if g["points"] is not None else None) for g in rows(cur, "SELECT * FROM grade_scale")}
        credits = {c["code"]: float(c["credit_hours"]) for c in rows(cur, "SELECT code, credit_hours FROM course")}
        lectures = {(l["term_code"], l["crn"]): l for l in rows(cur, "SELECT * FROM lecture")}
        programs = {p["code"]: p for p in rows(cur, "SELECT * FROM program")}
        students = {s["university_id"]: s for s in rows(cur, "SELECT * FROM student")}
        plan = defaultdict(list)
        for r in rows(cur, "SELECT * FROM degree_requirement"):
            plan[r["program_code"]].append(r)
        minimums = defaultdict(dict)
        for r in rows(cur, "SELECT * FROM program_category_requirement"):
            minimums[r["program_code"]][r["category"]] = r["min_credits"]
        prereqs = defaultdict(lambda: defaultdict(list))
        for r in rows(cur, "SELECT * FROM course_prerequisite"):
            prereqs[r["course_code"]][r["group_number"]].append((r["required_course_code"], points[r["min_grade"]]))
        transfer = defaultdict(set)
        for r in rows(cur, "SELECT * FROM transfer_credit"):
            transfer[r["student_university_id"]].add(r["course_code"])
            if students[r["student_university_id"]]["entry_type"] != "transfer":
                problems.append(f"{r['student_university_id']}: transfer credit for a {students[r['student_university_id']]['entry_type']} student")
        enr = rows(cur, "SELECT e.*, l.course_code, l.days, l.start_time, l.end_time, l.capacity, l.is_cancelled FROM enrollment e "
                        "JOIN lecture l ON l.term_code = e.term_code AND l.crn = e.crn ORDER BY e.student_university_id, e.term_code, e.crn")
        taught = defaultdict(list)
        for (t, crn), l in lectures.items():
            taught[(l["instructor_university_id"], t)].append((l["days"], l["start_time"], l["end_time"]))
        by_student = defaultdict(lambda: defaultdict(list))
        seats = Counter()
        for e in enr:
            by_student[e["student_university_id"]][e["term_code"]].append(e)
            seats[(e["term_code"], e["crn"])] += 1
            if e["is_cancelled"]:
                problems.append(f"{e['student_university_id']}: enrolled in cancelled CRN {e['crn']} ({e['term_code']})")
            if e["term_code"] in (CURRENT, NEXT) and (e["status"] != "enrolled" or e["grade"] is not None):
                if not (e["term_code"] == CURRENT and e["status"] == "withdrawn"):
                    problems.append(f"{e['student_university_id']}: {e['term_code']} row is {e['status']}/{e['grade']}")
            if seq[e["term_code"]] < cur_seq and e["status"] == "enrolled":
                problems.append(f"{e['student_university_id']}: ungraded row in past term {e['term_code']}")
        for (t, crn), n in seats.items():
            if n > lectures[(t, crn)]["capacity"]:
                problems.append(f"CRN {crn} in {t}: {n} enrolled over capacity {lectures[(t, crn)]['capacity']}")
        gpas, loads, statuses = {}, [], Counter()
        for uid, st in students.items():
            prog = programs[st["program_code"]]
            terms_of = by_student.get(uid, {})
            best: dict[str, float] = {}
            in_progress: set[str] = set()
            gp = gc = 0.0
            earned = 0.0
            cat = Counter()
            cat_of = {r["course_code"]: r["category"] for r in plan[st["program_code"]]}
            for c in transfer[uid]:
                earned += credits[c]
                if c in cat_of:
                    cat[cat_of[c]] += credits[c]
            for term in sorted(terms_of, key=lambda t: seq[t]):
                es = terms_of[term]
                courses = [e["course_code"] for e in es]
                if len(set(courses)) != len(courses):
                    problems.append(f"{uid}: two sections of one course in {term}")
                slots = [(e["days"], e["start_time"], e["end_time"]) for e in es] + taught.get((uid, term), [])
                for i in range(len(slots)):
                    for j in range(i + 1, len(slots)):
                        if overlaps(slots[i], slots[j]):
                            problems.append(f"{uid}: overlapping sections in {term}: {slots[i]} / {slots[j]}")
                load = sum(credits[c] for c in courses)
                loads.append(load)
                for e in es:
                    c = e["course_code"]
                    if prog["degree"] == "BS":
                        for group in prereqs.get(c, {}).values():
                            if not any(req in transfer[uid] or best.get(req, -1) >= mg or (term == NEXT and req in in_progress) for req, mg in group):
                                problems.append(f"{uid}: {c} in {term} without prerequisite group {group} (best {[best.get(r) for r, _ in group]})")
                for e in es:   # grades apply after the term
                    c, g = e["course_code"], e["grade"]
                    if g is None:
                        in_progress.add(c)
                        continue
                    if points[g] is None:
                        continue
                    gp += points[g] * credits[c]
                    gc += credits[c]
                    was = c in transfer[uid] or best.get(c, -1) > 0
                    best[c] = max(best.get(c, -1), points[g])
                    if not was and points[g] > 0:
                        earned += credits[c]
                        if c in cat_of:
                            cat[cat_of[c]] += credits[c]
            gpa = gp / gc if gc else None
            gpas[uid] = gpa
            statuses[st["status"]] += 1
            status = st["status"]
            last_seq = max((seq[t] for t in terms_of), default=None)
            if status == "active":
                if CURRENT not in terms_of or any(e["status"] != "enrolled" for e in terms_of[CURRENT]):
                    problems.append(f"{uid}: active but not enrolled in {CURRENT}")
            else:
                if CURRENT in terms_of and status != "graduated" and any(e["status"] != "withdrawn" for e in terms_of[CURRENT]):
                    problems.append(f"{uid}: {status} but has non-W rows in {CURRENT}")
                if NEXT in terms_of:
                    problems.append(f"{uid}: {status} but registered for {NEXT}")
            if status == "graduated":
                exp = st["expected_graduation_term_code"]
                missing = [r["course_code"] for r in plan[st["program_code"]] if r["is_required"] and not (r["course_code"] in transfer[uid] or best.get(r["course_code"], -1) > 0)]
                short = {k: (cat[k], v) for k, v in minimums[st["program_code"]].items() if cat[k] < v}
                if missing or short or earned < prog["total_credits_required"] or gpa is None or gpa < float(prog["min_gpa"]):
                    problems.append(f"{uid}: graduated but missing {missing}, short {short}, earned {earned}/{prog['total_credits_required']}, gpa {gpa}")
                if last_seq is not None and last_seq > seq[exp]:
                    problems.append(f"{uid}: graduated {exp} but has rows after it")
            if status in ("suspended", "dismissed") and gpa is not None and gpa >= float(prog["min_gpa"]):
                problems.append(f"{uid}: {status} with gpa {gpa:.2f}")
        # profile
        print(f"students {len(students)}, enrollment rows {len(enr)}, transfer rows {sum(len(v) for v in transfer.values())}")
        print("status:", dict(statuses))
        g = sorted(v for v in gpas.values() if v is not None)
        print(f"GPA: n {len(g)}, min {g[0]:.2f}, median {g[len(g)//2]:.2f}, max {g[-1]:.2f}; below 2.0: {sum(v < 2 for v in g)}")
        print(f"term loads: min {min(loads)}, mean {sum(loads)/len(loads):.1f}, max {max(loads)}")
        grades = Counter(e["grade"] for e in enr if e["grade"])
        print("grades:", dict(sorted(grades.items(), key=lambda x: -x[1])))
        per_term = Counter(e["term_code"] for e in enr)
        print("rows per term:", dict(sorted(per_term.items())))
        full = [(t, crn, n) for (t, crn), n in seats.items() if n >= lectures[(t, crn)]["capacity"]]
        print(f"full sections: {len(full)}: {sorted(full)[:12]}")
        print(f"registered for {NEXT}: {sum(1 for uid in students if NEXT in by_student.get(uid, {}))} of {statuses['active']} active")
        retakes = sum(1 for uid in students for c, n in Counter(e['course_code'] for t in by_student.get(uid, {}).values() for e in t if e['grade'] not in (None, 'W')).items() if n > 1)
        print(f"courses retaken (student x course with >1 graded attempt): {retakes}")
    print(f"\n{len(problems)} problems" + (":" if problems else "."))
    for p in problems[:40]:
        print(" -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
