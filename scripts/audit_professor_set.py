"""Independent audit of the professor cases built on enrollment, staff, grade submission and salary (2026-11-05).

    python scripts/audit_professor_set.py      # from the repository root; exit 1 on a mismatch

Recomputes each answer from data/seed/*.csv with no builder code and no SQL, and checks the permission side: allowed
student questions are about students in the asker's sections, refusals about students who never were (except the scenarios
that stay private even for a student in the class)."""
import csv, json, sys
from collections import defaultdict

D = "data/seed/"
rd = lambda t: list(csv.DictReader(open(D + t + ".csv")))
PTS = {"A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7, "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3, "D": 1.0, "D-": 0.7, "F": 0.0}
terms = {t["code"]: t for t in rd("academic_term")}
tname = {c: t["name"] for c, t in terms.items()}
seq = {c: int(t["sequence"]) for c, t in terms.items()}
person = {p["university_id"]: p for p in rd("person")}
name = {u: f"{p['first_name']} {p['last_name']}" for u, p in person.items()}
student = {s["university_id"]: s for s in rd("student")}
instr = {i["university_id"]: i for i in rd("instructor")}
lect = {(l["term_code"], l["crn"]): l for l in rd("lecture")}
enr = defaultdict(list)
for e in rd("enrollment"):
    enr[(e["term_code"], e["crn"])].append(e)
staff = defaultdict(list)          # uid -> [(term, crn, role)]
tas_of = defaultdict(list)
for s in rd("lecture_staff"):
    if lect[(s["term_code"], s["crn"])]["is_cancelled"] == "true":
        continue
    staff[s["university_id"]].append((s["term_code"], s["crn"], s["role"]))
    if s["role"] == "ta":
        tas_of[(s["term_code"], s["crn"])].append(s["university_id"])
subm = {(g["term_code"], g["crn"]): g for g in rd("grade_submission")}
mine_students = {u: {e["student_university_id"] for t, c, _ in ss for e in enr[(t, c)]} for u, ss in staff.items()}
CUR = "202680"
code_of = {v: k for k, v in tname.items()}

problems, checked = [], 0
def bad(case, msg):
    problems.append(f"{case['id']}: {msg}")

for line in open("data/testset/professor/cases.jsonl"):
    c = json.loads(line)
    a, sl, me = c["answer"], c["slots"], c["professor"]["university_id"]
    it = c["intent"]
    mysec = {(t, cr) for t, cr, _ in staff[me]}
    tc = sl.get("term_code") or (code_of.get(a.get("term")) if a.get("term") else None)
    def rows(t, cr): return enr[(t, cr)]
    def nonw(t, cr): return [e for e in rows(t, cr) if e["status"] != "withdrawn"]
    checked += 1
    if it == "roster":
        if (tc, a["crn"]) not in mysec: bad(c, "asker not staff on section")
        want = sorted(e["student_university_id"] for e in nonw(tc, a["crn"]))
        got = sorted(s["university_id"] for s in a["students"])
        if want != got: bad(c, "roster members differ")
        for s in a["students"]:
            u = s["university_id"]
            if (s["name"], s["email"], s["program"], s["status"]) != (name[u], person[u]["email"], student[u]["program_code"], student[u]["status"]): bad(c, f"fields of {u}")
    elif it == "enrollment_count":
        for crn, v in a["sections"].items():
            n = len(nonw(tc, crn)); cap = int(lect[(tc, crn)]["capacity"])
            if (v["enrolled"], v["capacity"], v["seats_left"]) != (n, cap, max(0, cap - n)): bad(c, f"count {crn}")
            if (tc, crn) not in mysec: bad(c, "not my section")
    elif it == "student_in_section":
        row = next((e for e in rows(tc, a["crn"]) if e["student_university_id"] == a["student"]), None)
        if a["in_section"] != (row is not None) or a["enrollment_status"] != (row["status"] if row else None): bad(c, "membership")
    elif it == "student_info":
        u = a["student"]
        if u not in mine_students[me]: bad(c, "student not in asker's sections")
        if (a["email"], a["program"], a["status"]) != (person[u]["email"], student[u]["program_code"], student[u]["status"]): bad(c, "info fields")
    elif it == "withdrawals":
        want = sorted(e["student_university_id"] for e in rows(tc, a["crn"]) if e["status"] == "withdrawn")
        if want != sorted(s["university_id"] for s in a["students"]): bad(c, "withdrawals")
    elif it == "students_taught":
        by = defaultdict(set)
        for t, cr, _ in staff[me]:
            if seq[t] <= seq[CUR]:
                by[tname[t]] |= {e["student_university_id"] for e in nonw(t, cr)}
        if a["by_term"] != {k: len(v) for k, v in by.items()}: bad(c, "per-term counts")
        if a["total_distinct"] != len(set().union(*by.values())): bad(c, "total")
        if a["total_distinct"] == 0: bad(c, "trivial zero answer")
    elif it == "student_grade":
        if (tc, a["crn"]) not in mysec: bad(c, "not my section")
        row = next(e for e in rows(tc, a["crn"]) if e["student_university_id"] == a["student"])
        g = row["grade"] or None
        if a["grade"] != g or a["posted"] != (g is not None): bad(c, "grade")
    elif it == "section_grades":
        want = sorted((e["student_university_id"], e["grade"] or None) for e in rows(tc, a["crn"]))
        if want != sorted((x["university_id"], x["grade"]) for x in a["grades"]): bad(c, "section grades")
    elif it == "grade_distribution":
        rs = rows(tc, a["crn"]); cnt = defaultdict(int)
        for e in rs:
            if e["grade"]: cnt[e["grade"]] += 1
        pts = [PTS[e["grade"]] for e in rs if e["grade"] in PTS]
        if dict(cnt) != a["counts"] or a["graded"] != len(pts) or a["average_points"] != (round(sum(pts) / len(pts), 2) if pts else None): bad(c, "distribution")
    elif it == "dfw_rate":
        for crn, v in a["sections"].items():
            rs = rows(tc, crn); d = sum(e["grade"] in ("D+", "D", "D-") for e in rs); f = sum(e["grade"] == "F" for e in rs); w = sum(e["grade"] == "W" for e in rs)
            if (v["d"], v["f"], v["w"], v["total"], v["rate"]) != (d, f, w, len(rs), round((d + f + w) / len(rs), 3)): bad(c, f"dfw {crn}")
        want = {cr for t, cr, _ in staff[me] if t == tc and rows(t, cr)}
        if set(a["sections"]) != want: bad(c, "dfw section set")
    elif it == "incompletes":
        want = sorted((e["student_university_id"], t, cr) for t, cr, _ in staff[me] if seq[t] <= seq[CUR] for e in rows(t, cr) if e["grade"] == "I")
        if want != sorted((s["university_id"], code_of[s["term"]], s["crn"]) for s in a["students"]): bad(c, "incompletes")
    elif it == "course_trend":
        by = defaultdict(lambda: {"sections": 0, "enrolled": 0, "pts": []})
        for t, cr, role in staff[me]:
            if role == "instructor" and lect[(t, cr)]["course_code"] == a["course"] and t <= "202610":
                b = by[tname[t]]; b["sections"] += 1; b["enrolled"] += len(nonw(t, cr)); b["pts"] += [PTS[e["grade"]] for e in rows(t, cr) if e["grade"] in PTS]
        want = {k: {"sections": v["sections"], "enrolled": v["enrolled"], "average_points": round(sum(v["pts"]) / len(v["pts"]), 2) if v["pts"] else None} for k, v in by.items()}
        if want != a["by_term"]: bad(c, "trend")
    elif it == "grades_submitted":
        for crn, v in a["sections"].items():
            g = subm.get((tc, crn))
            if v["submitted"] != (g is not None): bad(c, f"submitted flag {crn}")
        want = {cr for t, cr, role in staff[me] if t == tc and role == "instructor" and rows(t, cr)}
        if set(a["sections"]) != want: bad(c, "submitted section set")
    elif it == "my_tas":
        for crn, v in a["sections"].items():
            if sorted(v["tas"]) != sorted(name[u] for u in tas_of[(tc, crn)]): bad(c, f"tas {crn}")
    elif it == "ta_sections":
        want = sorted(cr for t, cr, role in staff[me] if t == tc and role == "ta")
        if want != sorted(s["crn"] for s in a["sections"]): bad(c, "ta sections")
        if instr[me]["rank"] != "ta": bad(c, "asker is not a TA")
    elif it == "taught_all":
        want = sum(1 for t, cr, role in staff[me] if role == "instructor" and seq[t] <= seq[CUR])
        if a["total_sections"] != want: bad(c, "taught_all total")
    elif it in ("access_denied", "access_partial"):
        sc, t_uid = sl.get("scenario"), sl.get("t_uid")
        if t_uid and sc in ("my_student_other_grade", "my_student_gpa", "my_student_phone"):
            if t_uid not in mine_students[me]: bad(c, f"{sc}: student should be in asker's sections")
        elif t_uid and t_uid in student:
            if t_uid in mine_students.get(me, set()): bad(c, f"{sc}: student IS in asker's sections, refusal would be wrong for program/status/email")
        if sc == "my_student_other_grade":
            tcode = sl["t_term_code"]
            if any(t == tcode and lect[(t, cr)]["course_code"] == sl["t_course"] for t, cr, _ in staff[me]): bad(c, "other-grade course is the asker's")
        if sc == "colleague_roster" and (code_of[a["target"]["term"]], a["target"]["crn"]) in mysec: bad(c, "colleague roster is asker's own")
    elif it == "access_allowed" and sl.get("scenario") == "own_salary":
        if a["salary"] != int(instr[me]["salary"]): bad(c, "salary")
    else:
        checked -= 1

print(f"checked {checked} cases; {len(problems)} problems")
for p in problems[:40]:
    print(" -", p)
sys.exit(1 if problems else 0)
