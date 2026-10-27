"""Pick professors and scenarios from the loaded database and build the professor test set."""
from __future__ import annotations

import random
from collections import Counter

from psycopg.rows import dict_row

from .professor import ProfBuilder
from .professor_access import ProfAccess
from .student import CURRENT, DEFAULT_AS_OF, FUTURE, SNAPSHOT

QUOTA = {
    "teach_current": 10, "teach_term": 8, "teach_week": 6, "teach_day": 6, "section_meeting": 5, "term_dates": 8, "teach_load": 5,
    "enrollment_count": 8, "roster": 6, "roster_waitlist": 2, "student_in_section": 6, "drops_withdrawals": 6, "course_catalog": 6,
    "student_prereq_check": 8, "incompletes": 5, "grade_status": 5, "grade_change_status": 3,
    "grade_distribution": 10, "dfw_rate": 6, "enrollment_trend": 6, "fill_rate": 5, "withdrawal_stats": 5, "class_composition": 8, "students_taught": 3,
}
DENIED_PLAN = ["other_roster", "other_section_grades", "student_gpa", "student_transcript", "student_other_classes", "student_holds", "student_contact",
               "student_other_grade", "dept_aggregate", "dept_students", "student_advisor", "student_international",
               "other_roster", "student_gpa", "student_other_classes", "dept_aggregate", "student_other_grade", "student_contact"]
ALLOWED_PLAN = ["other_section_seats", "my_student_grade", "other_instructor", "prereqs_any", "roster_email", "roster_classification", "other_section_meeting", "my_student_grade"]
PARTIAL_PLAN = ["my_grade_and_gpa", "in_section_and_schedule", "roster_with_gpa", "counts_and_other_roster"]


def fetch(conn, sql, **params):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or None)
        return cur.fetchall()


def generate(conn, seed: int = 11) -> list[dict]:
    rng = random.Random(seed)
    pb = ProfBuilder(conn, rng)
    pa = ProfAccess(pb)
    terms = {r["code"]: r for r in fetch(conn, "SELECT code, id, sequence, term_type FROM academic_term")}
    cur, fut = terms[CURRENT], terms[FUTURE]

    pool = fetch(conn, """
        SELECT p.university_id AS uid, i.id AS iid, i.person_id AS pid, d.code AS dept,
               COUNT(DISTINCT sec.id) FILTER (WHERE sec.term_id = %(cur)s) AS n_cur,
               COUNT(DISTINCT sec.id) FILTER (WHERE sec.term_id = %(fut)s) AS n_fut,
               COUNT(DISTINCT sec.term_id) FILTER (WHERE t.sequence < %(cseq)s) AS n_past,
               BOOL_OR(w.id IS NOT NULL) AS has_waitlist
        FROM instructor i JOIN person p ON p.id = i.person_id JOIN department d ON d.id = i.department_id
        JOIN section_instructor si ON si.instructor_id = i.id AND si.role = 'primary'
        JOIN section sec ON sec.id = si.section_id JOIN academic_term t ON t.id = sec.term_id
        LEFT JOIN waitlist_entry w ON w.section_id = sec.id AND sec.term_id = %(cur)s AND w.status = 'waiting'
        GROUP BY 1, 2, 3, 4
        HAVING COUNT(DISTINCT sec.id) FILTER (WHERE sec.term_id = %(cur)s) >= 1
        ORDER BY 1""", cur=cur["id"], fut=fut["id"], cseq=cur["sequence"])
    rng.shuffle(pool)
    core = [x for x in pool if x["n_past"] >= 2 and x["n_fut"] >= 1]
    with_wl = [x for x in pool if x["has_waitlist"]]

    def past_terms(iid: int) -> list[dict]:
        return fetch(conn, """SELECT DISTINCT t.code, t.sequence FROM section_instructor si JOIN section sec ON sec.id = si.section_id
                              JOIN academic_term t ON t.id = sec.term_id WHERE si.instructor_id = %(iid)s AND t.sequence < %(cseq)s ORDER BY t.sequence DESC""", iid=iid, cseq=cur["sequence"])

    def sections_of(iid: int, term_id: int) -> list[dict]:
        return fetch(conn, """
            SELECT sec.id AS section_id, sec.crn, sub.code || ' ' || c.course_number AS course,
                   (SELECT COUNT(*) FROM course_prerequisite cp WHERE cp.course_id = c.id) AS n_prereq,
                   (SELECT COUNT(*) FROM enrollment e WHERE e.section_id = sec.id AND e.status = 'registered') AS registered,
                   (SELECT COUNT(*) FROM enrollment e WHERE e.section_id = sec.id AND e.status IN ('completed', 'withdrawn')) AS finished,
                   (SELECT COUNT(*) FROM enrollment e WHERE e.section_id = sec.id AND e.status IN ('dropped', 'withdrawn')) AS left_count
            FROM section_instructor si JOIN section sec ON sec.id = si.section_id JOIN course c ON c.id = sec.course_id JOIN subject sub ON sub.id = c.subject_id
            WHERE si.instructor_id = %(iid)s AND si.role = 'primary' AND sec.term_id = %(tid)s ORDER BY sec.crn""", iid=iid, tid=term_id)

    def multi_term_courses(iid: int) -> list[dict]:
        return fetch(conn, """
            SELECT sub.code || ' ' || c.course_number AS course, array_agg(DISTINCT t.code ORDER BY t.code) AS term_codes
            FROM section_instructor si JOIN section sec ON sec.id = si.section_id JOIN course c ON c.id = sec.course_id JOIN subject sub ON sub.id = c.subject_id
            JOIN academic_term t ON t.id = sec.term_id
            WHERE si.instructor_id = %(iid)s AND si.role = 'primary' AND t.sequence <= %(cseq)s
            GROUP BY 1 HAVING COUNT(DISTINCT t.id) >= 2 ORDER BY 1""", iid=iid, cseq=cur["sequence"])

    def roster_uid(section_id: int, status: str = "registered") -> str | None:
        r = fetch(conn, """SELECT p.university_id FROM enrollment e JOIN student s ON s.id = e.student_id JOIN person p ON p.id = s.person_id
                           WHERE e.section_id = %(sid)s AND e.status = %(st)s ORDER BY p.university_id""", sid=section_id, st=status)
        return rng.choice(r)["university_id"] if r else None

    def other_section(iid: int, term_id: int, same_subject_of: str | None = None, graded: bool = False) -> int:
        subj = same_subject_of.split()[0] if same_subject_of else None
        rows = fetch(conn, f"""
            SELECT sec.id FROM section sec JOIN course c ON c.id = sec.course_id JOIN subject sub ON sub.id = c.subject_id
            JOIN section_instructor si ON si.section_id = sec.id AND si.role = 'primary'
            WHERE si.instructor_id <> %(iid)s {'AND sec.term_id = %(tid)s' if term_id else 'AND sec.term_id < %(tid)s'}
              {"AND sub.code = %(subj)s" if subj else ""}
              {"AND EXISTS (SELECT 1 FROM enrollment e JOIN grade g ON g.enrollment_id = e.id WHERE e.section_id = sec.id)" if graded else ""}
              AND EXISTS (SELECT 1 FROM enrollment e WHERE e.section_id = sec.id AND e.status IN ('registered', 'completed'))
            ORDER BY sec.id""", iid=iid, tid=term_id or cur["id"], subj=subj)
        if not rows and subj:
            return other_section(iid, term_id, None, graded)
        return rng.choice(rows)["id"]

    def random_student(exclude_section: int, with_history: bool = True) -> str:
        return rng.choice(fetch(conn, """SELECT p.university_id FROM student s JOIN person p ON p.id = s.person_id
                              WHERE s.status = 'active' AND NOT EXISTS (SELECT 1 FROM enrollment e WHERE e.student_id = s.id AND e.section_id = %(x)s)
                              AND (%(hist)s = FALSE OR EXISTS (SELECT 1 FROM student_term_record r WHERE r.student_id = s.id))
                              ORDER BY p.university_id""", x=exclude_section, hist=with_history))["university_id"]

    cases: list[dict] = []
    k = 0

    def nxt(lst):
        nonlocal k
        k += 1
        return lst[k % len(lst)]

    # ---------------------------------------------------------------- schedule
    for i in range(QUOTA["teach_current"]):
        cases.append(pb.teach(nxt(pool)["uid"], CURRENT, DEFAULT_AS_OF, "current"))
    for i in range(QUOTA["teach_term"]):
        s = nxt(core)
        code = FUTURE if i % 3 == 0 else rng.choice(past_terms(s["iid"]))["code"]
        cases.append(pb.teach(s["uid"], code, DEFAULT_AS_OF, "term"))
    for i in range(QUOTA["teach_week"]):
        cases.append(pb.teach_week(nxt(pool)["uid"], CURRENT, DEFAULT_AS_OF))
    for i in range(QUOTA["teach_day"]):
        cases.append(pb.teach_week(nxt(pool)["uid"], CURRENT, DEFAULT_AS_OF, day=rng.choice("MTWRF")))
    for i in range(QUOTA["section_meeting"]):
        s = nxt(pool)
        sec = rng.choice(sections_of(s["iid"], cur["id"]))
        cases.append(pb.section_meeting(s["uid"], CURRENT, DEFAULT_AS_OF, sec["crn"] if i % 2 else None, None if i % 2 else sec["course"]))
    events = ["grades_due", "finals", "withdraw_deadline", "drop_deadline", "classes_begin", "census", "holiday:Thanksgiving break", "add_deadline", "commencement"]
    for i, ev in enumerate(events[: QUOTA["term_dates"]]):
        s = nxt(pool)
        code = FUTURE if ev in ("classes_begin", "add_deadline") else CURRENT
        as_of = SNAPSHOT if ev in ("withdraw_deadline",) and i % 2 else DEFAULT_AS_OF
        cases.append(pb.term_dates(s["uid"], code, as_of, ev))
    for i in range(QUOTA["teach_load"]):
        s = nxt(core)
        cases.append(pb.teach_load(s["uid"], FUTURE if i == 4 else CURRENT, DEFAULT_AS_OF))

    # ---------------------------------------------------------------- courses
    for i in range(QUOTA["enrollment_count"]):
        s = nxt(pool)
        secs = sections_of(s["iid"], cur["id"] if i % 4 else fut["id"])
        sec = rng.choice(secs)
        mode = i % 3
        cases.append(pb.enrollment_count(s["uid"], CURRENT if i % 4 else FUTURE, DEFAULT_AS_OF, sec["crn"] if mode == 0 else None, sec["course"] if mode == 1 else None))
    for i in range(QUOTA["roster"]):
        s = nxt(core)
        if i < 4:
            sec = max(sections_of(s["iid"], cur["id"]), key=lambda x: x["registered"])
            cases.append(pb.roster(s["uid"], CURRENT, DEFAULT_AS_OF, sec["crn"]))
        else:
            code = past_terms(s["iid"])[0]["code"]
            sec = max(sections_of(s["iid"], terms[code]["id"]), key=lambda x: x["finished"])
            cases.append(pb.roster(s["uid"], code, DEFAULT_AS_OF, sec["crn"]))
    for s in with_wl[: QUOTA["roster_waitlist"]]:
        sec = fetch(conn, """SELECT sec.crn FROM waitlist_entry w JOIN section sec ON sec.id = w.section_id JOIN section_instructor si ON si.section_id = sec.id
                             WHERE si.instructor_id = %(iid)s AND sec.term_id = %(tid)s ORDER BY sec.crn LIMIT 1""", iid=s["iid"], tid=cur["id"])[0]
        cases.append(pb.roster(s["uid"], CURRENT, DEFAULT_AS_OF, sec["crn"], waitlist=True))
    for i in range(QUOTA["student_in_section"]):
        s = nxt(pool)
        sec = rng.choice(sections_of(s["iid"], cur["id"]))
        if i % 3 == 2:
            t = random_student(sec["section_id"])  # not in the section
        else:
            t = roster_uid(sec["section_id"], "dropped" if i % 3 == 1 and sec["left_count"] else "registered") or roster_uid(sec["section_id"])
        cases.append(pb.student_in_section(s["uid"], CURRENT, DEFAULT_AS_OF, t, sec["crn"] if i % 2 else None))
    for i in range(QUOTA["drops_withdrawals"]):
        s = nxt(core)
        secs = sections_of(s["iid"], cur["id"])
        sec = max(secs, key=lambda x: x["left_count"])
        if i == 5:
            t = roster_uid(sec["section_id"], "withdrawn") or roster_uid(sec["section_id"], "dropped") or roster_uid(sec["section_id"])
            cases.append(pb.drops(s["uid"], CURRENT, DEFAULT_AS_OF, sec["crn"], None, target_uid=t))
        else:
            cases.append(pb.drops(s["uid"], CURRENT, DEFAULT_AS_OF, sec["crn"] if i % 3 == 0 else None, sec["course"] if i % 3 == 1 else None))
    for i in range(QUOTA["course_catalog"]):
        s = nxt(pool)
        secs = sections_of(s["iid"], cur["id"])
        sec = max(secs, key=lambda x: x["n_prereq"]) if i % 2 == 0 else rng.choice(secs)
        cases.append(pb.course_catalog(s["uid"], DEFAULT_AS_OF, tuple(sec["course"].split())))
    for i in range(QUOTA["student_prereq_check"]):
        s = nxt(core)
        secs = sections_of(s["iid"], fut["id"])
        sec = max(secs, key=lambda x: x["n_prereq"]) if i % 2 == 0 else rng.choice(secs)
        cases.append(pb.prereq_check(s["uid"], FUTURE, DEFAULT_AS_OF, sec["crn"], random_student(sec["section_id"], with_history=i % 4 != 3)))
    inc = fetch(conn, """SELECT DISTINCT p.university_id AS uid, i.id AS iid, t.code, sp.university_id AS student_uid
                         FROM grade g JOIN enrollment e ON e.id = g.enrollment_id JOIN section sec ON sec.id = e.section_id JOIN academic_term t ON t.id = sec.term_id
                         JOIN section_instructor si ON si.section_id = sec.id AND si.role = 'primary' JOIN instructor i ON i.id = si.instructor_id JOIN person p ON p.id = i.person_id
                         JOIN student st ON st.id = e.student_id JOIN person sp ON sp.id = st.person_id
                         WHERE g.grade = 'I' AND NOT g.is_final ORDER BY 1, 3, 4""")
    rng.shuffle(inc)
    plan = [(inc[0]["uid"], None, None, False), (inc[1]["uid"], inc[1]["code"], None, False), (inc[2]["uid"], inc[2]["code"], inc[2]["student_uid"], False),
            (inc[3]["uid"], None, None, True), (nxt(pool)["uid"], None, None, False)]
    for uid, code, t, exp in plan[: QUOTA["incompletes"]]:
        cases.append(pb.incompletes(uid, DEFAULT_AS_OF, term_code=code, target_uid=t, only_expired=exp))
    for i in range(QUOTA["grade_status"]):
        s = nxt(core)
        code = CURRENT if i == 4 else past_terms(s["iid"])[0]["code"]
        secs = sections_of(s["iid"], terms[code]["id"])
        sec = rng.choice(secs)
        cases.append(pb.grade_status(s["uid"], code, DEFAULT_AS_OF, sec["crn"] if i % 3 == 0 else None, sec["course"] if i % 3 == 1 else None))
    gc = fetch(conn, """SELECT DISTINCT p.university_id AS uid, sp.university_id AS student_uid, sec.crn
                        FROM grade_change gc JOIN person p ON p.id = gc.requested_by_person_id JOIN grade g ON g.id = gc.grade_id
                        JOIN enrollment e ON e.id = g.enrollment_id JOIN section sec ON sec.id = e.section_id JOIN student st ON st.id = e.student_id JOIN person sp ON sp.id = st.person_id ORDER BY 1, 3, 2""")
    for i, r in enumerate(gc[: QUOTA["grade_change_status"]]):
        cases.append(pb.grade_change_status(r["uid"], DEFAULT_AS_OF, r["student_uid"] if i == 0 else None, r["crn"] if i == 1 else None))

    # ---------------------------------------------------------------- statistics
    for i in range(QUOTA["grade_distribution"]):
        s = nxt(core)
        if i % 5 == 0:
            cases.append(pb.grade_distribution(s["uid"], DEFAULT_AS_OF, None, None, CURRENT))  # not available
        elif i % 5 == 1:
            code = past_terms(s["iid"])[0]["code"]
            sec = rng.choice(sections_of(s["iid"], terms[code]["id"]))
            cases.append(pb.grade_distribution(s["uid"], DEFAULT_AS_OF, sec["crn"], None, code))
        elif i % 5 == 2:
            mc = multi_term_courses(s["iid"])
            course = rng.choice(mc)["course"] if mc else rng.choice(sections_of(s["iid"], cur["id"]))["course"]
            cases.append(pb.grade_distribution(s["uid"], DEFAULT_AS_OF, None, course, None))
        elif i % 5 == 3:
            code = rng.choice(past_terms(s["iid"]))["code"]
            cases.append(pb.grade_distribution(s["uid"], DEFAULT_AS_OF, None, None, code))
        else:
            code = past_terms(s["iid"])[0]["code"]
            sec = rng.choice(sections_of(s["iid"], terms[code]["id"]))
            cases.append(pb.grade_distribution(s["uid"], DEFAULT_AS_OF, None, sec["course"], code))
    for i in range(QUOTA["dfw_rate"]):
        s = nxt(core)
        mc = multi_term_courses(s["iid"])
        if i % 3 == 0 and mc:
            cases.append(pb.dfw_rate(s["uid"], DEFAULT_AS_OF, None, rng.choice(mc)["course"], None))
        elif i % 3 == 1:
            code = past_terms(s["iid"])[0]["code"]
            sec = rng.choice(sections_of(s["iid"], terms[code]["id"]))
            cases.append(pb.dfw_rate(s["uid"], DEFAULT_AS_OF, sec["crn"], None, code))
        else:
            cases.append(pb.dfw_rate(s["uid"], DEFAULT_AS_OF, None, None, None))
    for i in range(QUOTA["enrollment_trend"]):
        s = nxt(core)
        mc = multi_term_courses(s["iid"])
        if i % 3 == 2 or not mc:
            cases.append(pb.enrollment_trend(s["uid"], DEFAULT_AS_OF, None))
        else:
            c = rng.choice(mc)
            cmp = (c["term_codes"][0], c["term_codes"][-1]) if i % 3 == 1 else None
            cases.append(pb.enrollment_trend(s["uid"], DEFAULT_AS_OF, c["course"], cmp))
    for i in range(QUOTA["fill_rate"]):
        s = nxt(core)
        cases.append(pb.fill_rate(s["uid"], FUTURE if i == 4 else CURRENT, DEFAULT_AS_OF))
    for i in range(QUOTA["withdrawal_stats"]):
        s = nxt(core)
        pts = [t["code"] for t in past_terms(s["iid"])]
        fall_prev = next((c for c in pts if c.endswith("80")), None)
        sec = max(sections_of(s["iid"], cur["id"]), key=lambda x: x["left_count"])
        cases.append(pb.withdrawal_stats(s["uid"], CURRENT, DEFAULT_AS_OF, sec["crn"] if i % 3 == 1 else None, fall_prev if i % 3 == 2 else None))
    dims = ["classification", "major", "college", "first_term"] * 2
    for i, dim in enumerate(dims[: QUOTA["class_composition"]]):
        s = nxt(pool)
        sec = max(sections_of(s["iid"], cur["id"]), key=lambda x: x["registered"])
        cases.append(pb.class_composition(s["uid"], CURRENT, DEFAULT_AS_OF, sec["crn"] if i % 3 == 0 else None, sec["course"] if i % 3 == 1 else None, dim))
    for i in range(QUOTA["students_taught"]):
        cases.append(pb.students_taught(nxt(core)["uid"], DEFAULT_AS_OF))

    # ---------------------------------------------------------------- access control
    for i, sc in enumerate(DENIED_PLAN):
        s = nxt(core)
        secs = sections_of(s["iid"], cur["id"])
        mine = max(secs, key=lambda x: x["registered"])
        kw = {"my_section_id": mine["section_id"]}
        if sc in ("other_roster", "other_section_grades"):
            kw["other_section_id"] = other_section(s["iid"], None if sc == "other_section_grades" else cur["id"], mine["course"], graded=sc == "other_section_grades")
        elif sc not in ("dept_aggregate", "dept_students"):
            kw["target_uid"] = roster_uid(mine["section_id"])
        cases.append(pa.denied(s["uid"], DEFAULT_AS_OF, sc, **kw))
    for i, sc in enumerate(ALLOWED_PLAN):
        s = nxt(core)
        kw = {}
        if sc in ("other_section_seats", "other_instructor", "prereqs_any", "other_section_meeting"):
            mine = rng.choice(sections_of(s["iid"], cur["id"]))
            kw["other_section_id"] = other_section(s["iid"], cur["id"], mine["course"])
        elif sc == "my_student_grade":
            code = past_terms(s["iid"])[0]["code"]
            sec = max(sections_of(s["iid"], terms[code]["id"]), key=lambda x: x["finished"])
            kw.update(term_code=code, my_section_id=sec["section_id"], target_uid=roster_uid(sec["section_id"], "completed"))
        else:
            sec = max(sections_of(s["iid"], cur["id"]), key=lambda x: x["registered"])
            kw.update(my_section_id=sec["section_id"], target_uid=roster_uid(sec["section_id"]))
        cases.append(pa.allowed(s["uid"], DEFAULT_AS_OF, sc, **kw))
    for i, sc in enumerate(PARTIAL_PLAN):
        s = nxt(core)
        kw = {}
        if sc == "my_grade_and_gpa":
            code = past_terms(s["iid"])[0]["code"]
            sec = max(sections_of(s["iid"], terms[code]["id"]), key=lambda x: x["finished"])
            kw.update(term_code=code, my_section_id=sec["section_id"], target_uid=roster_uid(sec["section_id"], "completed"))
        else:
            sec = max(sections_of(s["iid"], cur["id"]), key=lambda x: x["registered"])
            kw["my_section_id"] = sec["section_id"]
            if sc == "in_section_and_schedule":
                kw["target_uid"] = roster_uid(sec["section_id"])
            if sc == "counts_and_other_roster":
                kw["other_section_id"] = other_section(s["iid"], cur["id"], sec["course"])
        cases.append(pa.partial(s["uid"], DEFAULT_AS_OF, sc, **kw))

    counts = Counter()
    for c in cases:
        counts[c["intent"]] += 1
        c["id"] = f"prof-{c['intent']}-{counts[c['intent']]:03d}"
    return cases
