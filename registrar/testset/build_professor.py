"""Pick professors and scenarios from the loaded database and build the professor test set."""
from __future__ import annotations

import random
from collections import Counter

from psycopg.rows import dict_row

from .common import AS_OF_BREAK, AS_OF_LATE, AS_OF_SPRING, CURRENT, DEFAULT_AS_OF, FUTURE, PREVIOUS, SNAPSHOT, UNIQUE_NAME
from .professor_access import ProfAccess

QUOTA = {"teach_current": 10, "teach_term": 8, "teach_week": 6, "teach_day": 6, "section_meeting": 6, "teach_load": 6, "term_dates": 8,
         "course_catalog": 8, "my_capacity": 6, "course_offered": 6, "dept_offerings": 6, "who_teaches": 6, "taught_history": 6, "load_history": 4,
         # 2026-11-05: enrollment, staff, grade submission, salary
         "taught_all": 4, "roster": 6, "enrollment_count": 6, "student_in_section": 6, "student_info": 4, "withdrawals": 4, "students_taught": 4,
         "student_grade": 6, "section_grades": 4, "grade_distribution": 4, "dfw_rate": 4, "incompletes": 3, "course_trend": 4, "grades_submitted": 4,
         "my_tas": 4, "ta_sections": 3}
RECORD_DENIED_PLAN = ["other_instructor_salary", "not_my_student_grade", "my_student_other_grade", "my_student_gpa", "my_student_phone", "colleague_roster",
                      "other_instructor_salary", "not_my_student_grade", "my_student_other_grade", "my_student_gpa", "my_student_phone", "colleague_roster"]
DENIED_PLAN = ["student_program", "student_status", "student_contact", "student_personal", "student_graduation", "other_instructor_private", "student_list",
               "impersonation_student", "student_contact", "other_instructor_private", "student_list", "impersonation_instructor", "student_personal", "student_program"]
ALLOWED_PLAN = ["colleague_schedule", "colleague_email", "colleague_rank", "own_hire_date", "own_record", "prerequisites", "colleague_schedule", "colleague_email"]
PARTIAL_PLAN = ["colleague_schedule_and_phone", "my_section_and_student_program", "colleague_schedule_and_phone", "my_section_and_student_program"]
PAST_TERMS = ["202480", "202510", "202580", PREVIOUS]


def fetch(conn, sql, **params):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or None)
        return cur.fetchall()


def generate(conn, seed: int = 11) -> list[dict]:
    rng = random.Random(seed)
    pb = ProfAccess(conn, rng)
    profs = fetch(conn, """
        SELECT i.university_id AS uid, i.department_code, i.rank,
               COUNT(*) FILTER (WHERE l.term_code = %(c)s AND NOT l.is_cancelled) AS n_current,
               COUNT(*) FILTER (WHERE l.term_code = %(f)s AND NOT l.is_cancelled) AS n_future
        FROM instructor i LEFT JOIN lecture l ON l.instructor_university_id = i.university_id
        WHERE i.is_active AND """ + UNIQUE_NAME.format(col="i.university_id") + """
        GROUP BY i.university_id, i.department_code, i.rank ORDER BY i.university_id""", c=CURRENT, f=FUTURE)
    rng.shuffle(profs)
    teaching = [p for p in profs if p["n_current"] > 0]
    students = fetch(conn, "SELECT university_id AS uid FROM student WHERE " + UNIQUE_NAME.format(col="student.university_id")
                     + " ORDER BY university_id")
    rng.shuffle(students)
    courses = fetch(conn, "SELECT code FROM course ORDER BY code")
    all_codes = [c["code"] for c in courses]
    with_prereq = [r["course_code"] for r in fetch(conn, "SELECT DISTINCT course_code FROM course_prerequisite ORDER BY 1")]
    lectures = fetch(conn, "SELECT term_code, crn, course_code, instructor_university_id AS uid, days, is_cancelled FROM lecture ORDER BY term_code, crn")

    def mine(uid: str, term: str) -> list[dict]:
        return [l for l in lectures if l["uid"] == uid and l["term_code"] == term and not l["is_cancelled"]]

    def prof(i: int) -> dict:
        return teaching[i % len(teaching)]

    cases: list[dict] = []
    # ------------------------------------------------------------ schedule
    for i in range(QUOTA["teach_current"]):
        as_of = [DEFAULT_AS_OF, DEFAULT_AS_OF, SNAPSHOT, AS_OF_LATE, DEFAULT_AS_OF][i % 5]
        cases.append(pb.teach(prof(i)["uid"], CURRENT, as_of))
    for i in range(QUOTA["teach_term"]):
        term = [FUTURE, PREVIOUS, "202480", "202580", FUTURE, PREVIOUS, "202510", FUTURE][i]
        p = profs[(i * 3) % len(profs)]
        cases.append(pb.teach(p["uid"], term, DEFAULT_AS_OF if i != 4 else AS_OF_SPRING))
    for i in range(QUOTA["teach_week"]):
        cases.append(pb.teach_week(prof(i + 10)["uid"], CURRENT if i % 3 else FUTURE))
    for i in range(QUOTA["teach_day"]):
        p = prof(i + 16)
        days = sorted({d for l in mine(p["uid"], CURRENT) for d in l["days"]})
        day = rng.choice(days) if i % 3 else rng.choice([d for d in "MTWRF" if d not in days] or days)
        cases.append(pb.teach_day(p["uid"], CURRENT, day))
    for i in range(QUOTA["section_meeting"]):
        p = prof(i + 22)
        term = CURRENT if i % 2 == 0 else FUTURE
        ls = mine(p["uid"], term)
        if not ls:
            term, ls = CURRENT, mine(p["uid"], CURRENT)
        l = rng.choice(ls)
        cases.append(pb.section_meeting(p["uid"], term, crn=l["crn"]) if i % 2 == 0 else pb.section_meeting(p["uid"], term, course=l["course_code"]))
    for i in range(QUOTA["teach_load"]):
        p = profs[(i * 5 + 1) % len(profs)]
        cases.append(pb.teach_load(p["uid"], [CURRENT, FUTURE, PREVIOUS, CURRENT, FUTURE, "202480"][i]))
    events = ["grades_due", "withdraw_deadline", "classes_begin", "registration_opens", "drop_deadline", "classes_end", "add_deadline", "grades_due"]
    clocks = [DEFAULT_AS_OF, SNAPSHOT, DEFAULT_AS_OF, SNAPSHOT, AS_OF_SPRING, AS_OF_LATE, AS_OF_BREAK, AS_OF_SPRING]
    terms = [CURRENT, CURRENT, FUTURE, FUTURE, FUTURE, CURRENT, FUTURE, PREVIOUS]
    for i in range(QUOTA["term_dates"]):
        cases.append(pb.term_dates(prof(i + 28)["uid"], terms[i], events[i], clocks[i]))
    # ------------------------------------------------------------ courses
    for i in range(QUOTA["course_catalog"]):
        p = prof(i + 36)
        own = [l["course_code"] for l in mine(p["uid"], CURRENT)]
        code = rng.choice(own) if i % 2 == 0 else rng.choice(with_prereq if i % 4 == 1 else all_codes)
        cases.append(pb.course_catalog(p["uid"], code))
    for i in range(QUOTA["my_capacity"]):
        p = prof(i + 44)
        term = CURRENT if i % 3 else FUTURE
        ls = mine(p["uid"], term) or mine(p["uid"], CURRENT)
        term = ls[0]["term_code"]
        cases.append(pb.my_capacity(p["uid"], term, crn=rng.choice(ls)["crn"] if i % 2 == 0 else None))
    offered = {t: sorted({l["course_code"] for l in lectures if l["term_code"] == t and not l["is_cancelled"]}) for t in (CURRENT, FUTURE, PREVIOUS)}
    for i in range(QUOTA["course_offered"]):
        term = [FUTURE, CURRENT, FUTURE, PREVIOUS, FUTURE, CURRENT][i]
        code = rng.choice(offered[term] if i % 3 else [c for c in all_codes if c not in offered[term]])
        cases.append(pb.course_offered(prof(i + 50)["uid"], code, term))
    for i in range(QUOTA["dept_offerings"]):
        cases.append(pb.dept_offerings(profs[(i * 7 + 2) % len(profs)]["uid"], [CURRENT, FUTURE, PREVIOUS, FUTURE, CURRENT, FUTURE][i], DEFAULT_AS_OF if i != 3 else AS_OF_BREAK))
    for i in range(QUOTA["who_teaches"]):
        p = prof(i + 56)
        term = [CURRENT, FUTURE, PREVIOUS, CURRENT, FUTURE, CURRENT][i]
        dept_courses = [c for c in offered[term] if c.startswith(p["department_code"] + " ")] or offered[term]
        cases.append(pb.who_teaches(p["uid"], rng.choice(dept_courses), term))
    for i in range(QUOTA["taught_history"]):
        p = profs[(i * 11 + 3) % len(profs)]
        taught = sorted({l["course_code"] for l in lectures if l["uid"] == p["uid"] and not l["is_cancelled"]})
        never = [c for c in all_codes if c.startswith(p["department_code"] + " ") and c not in taught]
        cases.append(pb.taught_history(p["uid"], rng.choice(never if i % 3 == 2 and never else taught)))
    # ------------------------------------------------------------ statistics
    for i in range(QUOTA["load_history"]):
        cases.append(pb.load_history(profs[(i * 13 + 5) % len(profs)]["uid"]))
    # ------------------------------------------------------------ records (2026-11-05): sections, students, grades, staff
    prof_ids = {p["uid"] for p in profs}
    student_ids = [s["uid"] for s in students]                       # unique full names, shuffled
    unique_students = set(student_ids)
    staff = fetch(conn, """SELECT s.term_code, s.crn, s.university_id AS uid, s.role, l.course_code, t.name AS term_name
                           FROM lecture_staff s JOIN lecture l USING (term_code, crn) JOIN academic_term t ON t.code = s.term_code
                           WHERE NOT l.is_cancelled ORDER BY s.term_code, s.crn, s.university_id""")
    enr = fetch(conn, "SELECT term_code, crn, student_university_id AS st, status, grade FROM enrollment ORDER BY term_code, crn, student_university_id")
    rows_of: dict = {}
    for e in enr:
        rows_of.setdefault((e["term_code"], e["crn"]), []).append(e)
    secs_of: dict = {}
    for s in staff:
        secs_of.setdefault(s["uid"], []).append(s)
    students_of = {uid: {e["st"] for s in ss for e in rows_of.get((s["term_code"], s["crn"]), [])} for uid, ss in secs_of.items()}
    by_student: dict = {}
    for e in enr:
        by_student.setdefault(e["st"], []).append(e)
    instructor_of = {(s["term_code"], s["crn"]): s["uid"] for s in staff if s["role"] == "instructor"}
    course_of = {(s["term_code"], s["crn"]): s["course_code"] for s in staff}
    term_name = {s["term_code"]: s["term_name"] for s in staff}

    def sections(uid: str, term: str | None = None, role: str = "instructor", min_rows: int = 1, w: bool | None = None) -> list[dict]:
        out = [s for s in secs_of.get(uid, []) if (term is None or s["term_code"] == term) and s["role"] == role
               and len(rows_of.get((s["term_code"], s["crn"]), [])) >= min_rows]
        if w is not None:
            out = [s for s in out if any(e["grade"] == "W" for e in rows_of[(s["term_code"], s["crn"])]) == w]
        return out

    def teachers(term: str, min_rows: int = 5, **kw) -> list[dict]:
        """Unique-named instructors with a section in the term with at least min_rows students, in the shuffled order."""
        return [p for p in profs if sections(p["uid"], term, min_rows=min_rows, **kw)]

    def never_mine(uid: str, i: int) -> str:
        """A unique-named student who was never in any section the user teaches or assists."""
        theirs = students_of.get(uid, set())
        return next(s for s in student_ids[i:] + student_ids if s not in theirs)

    tas = [p for p in profs if p["rank"] == "ta" and sections(p["uid"], role="ta")]
    prev_teachers = teachers(PREVIOUS)
    cur_teachers = teachers(CURRENT)
    veterans = [p for p in profs if len({s["term_code"] for s in sections(p["uid"])}) >= 4]   # four or more terms of history
    for i in range(QUOTA["taught_all"]):
        cases.append(pb.taught_all(veterans[i]["uid"]))
    for i in range(QUOTA["roster"]):
        if i < 2:                                                     # a TA asks for a section they assist
            t = tas[i % len(tas)]
            s = rng.choice(sections(t["uid"], CURRENT if i == 0 else PREVIOUS, role="ta"))
            cases.append(pb.roster(t["uid"], s["term_code"], s["crn"]))
        else:
            p = (cur_teachers if i % 2 else prev_teachers)[i]
            s = rng.choice(sections(p["uid"], CURRENT if i % 2 else PREVIOUS, min_rows=5))
            cases.append(pb.roster(p["uid"], s["term_code"], s["crn"]))
    for i in range(QUOTA["enrollment_count"]):
        p = cur_teachers[i + 6]
        term = [CURRENT, FUTURE, CURRENT, CURRENT, FUTURE, CURRENT][i]
        ss = sections(p["uid"], term, min_rows=0) or sections(p["uid"], CURRENT, min_rows=0)
        cases.append(pb.enrollment_count(p["uid"], ss[0]["term_code"], crn=rng.choice(ss)["crn"] if i % 2 == 0 else None))
    for i in range(QUOTA["student_in_section"]):
        p = cur_teachers[i + 12]
        s = rng.choice(sections(p["uid"], CURRENT, min_rows=5))
        inside = [e["st"] for e in rows_of[(s["term_code"], s["crn"])] if e["st"] in unique_students]
        t_uid = rng.choice(inside) if i % 2 == 0 else next(x for x in student_ids[i * 9:] if x not in {e["st"] for e in rows_of[(s["term_code"], s["crn"])]})
        cases.append(pb.student_in_section(p["uid"], s["term_code"], s["crn"], t_uid))
    for i in range(QUOTA["student_info"]):
        p = prev_teachers[i + 6]
        s = rng.choice(sections(p["uid"], PREVIOUS if i % 2 else CURRENT, min_rows=5) or sections(p["uid"], PREVIOUS, min_rows=5))
        t_uid = rng.choice([e["st"] for e in rows_of[(s["term_code"], s["crn"])] if e["st"] in unique_students])
        cases.append(pb.student_info(p["uid"], t_uid, s))
    w_teachers = teachers(PREVIOUS, min_rows=5, w=True)
    for i in range(QUOTA["withdrawals"]):
        if i < 3:
            p = w_teachers[i]
            s = rng.choice(sections(p["uid"], PREVIOUS, min_rows=5, w=True))
        else:
            p = prev_teachers[i + 10]
            s = rng.choice(sections(p["uid"], PREVIOUS, min_rows=5, w=False) or sections(p["uid"], PREVIOUS, min_rows=5))
        cases.append(pb.withdrawals(p["uid"], s["term_code"], s["crn"]))
    for i in range(QUOTA["students_taught"]):
        cases.append(pb.students_taught(veterans[i + 4]["uid"]))
    for i in range(QUOTA["student_grade"]):
        if i == 0:                                                    # a TA asks for a grade in a section they assisted
            t = next(t for t in tas if sections(t["uid"], PREVIOUS, role="ta"))
            s = rng.choice(sections(t["uid"], PREVIOUS, role="ta"))
            asker = t["uid"]
        else:
            term = CURRENT if i == 5 else PREVIOUS                    # Fall 2026: enrolled, no grade posted
            p = (cur_teachers if term == CURRENT else prev_teachers)[i + 14]
            s = rng.choice(sections(p["uid"], term, min_rows=5))
            asker = p["uid"]
        rows = [e for e in rows_of[(s["term_code"], s["crn"])] if e["st"] in unique_students]
        cases.append(pb.student_grade(asker, s["term_code"], s["crn"], rng.choice(rows)["st"]))
    for i in range(QUOTA["section_grades"]):
        if i == 0:
            t = next(t for t in tas if sections(t["uid"], PREVIOUS, role="ta"))
            s, asker = rng.choice(sections(t["uid"], PREVIOUS, role="ta")), t["uid"]
        else:
            p = prev_teachers[i + 20]
            s, asker = rng.choice(sections(p["uid"], [PREVIOUS, "202580", PREVIOUS][i - 1], min_rows=5) or sections(p["uid"], PREVIOUS, min_rows=5)), p["uid"]
        cases.append(pb.section_grades(asker, s["term_code"], s["crn"]))
    for i in range(QUOTA["grade_distribution"]):
        p = prev_teachers[(i + 24) % len(prev_teachers)]
        s = max(sections(p["uid"], PREVIOUS, min_rows=5), key=lambda s: (len(rows_of[(s["term_code"], s["crn"])]), s["crn"]))
        cases.append(pb.grade_distribution(p["uid"], s["term_code"], s["crn"]))
    for i in range(QUOTA["dfw_rate"]):
        p = prev_teachers[(i + 28) % len(prev_teachers)]
        cases.append(pb.dfw_rate(p["uid"], [PREVIOUS, "202580", PREVIOUS, "202510"][i]))
    with_i = [p for p in profs if any(e["grade"] == "I" for s in sections(p["uid"]) for e in rows_of[(s["term_code"], s["crn"])])]
    without_i = [p for p in profs if p not in with_i and sections(p["uid"])]
    for i in range(QUOTA["incompletes"]):
        cases.append(pb.incompletes((with_i[i] if i < 2 else without_i[0])["uid"]))
    repeat = [(p, c) for p in profs for c in sorted({s["course_code"] for s in sections(p["uid"]) if s["term_code"] <= PREVIOUS})
              if len({s["term_code"] for s in sections(p["uid"]) if s["course_code"] == c and s["term_code"] <= PREVIOUS}) >= 3]
    for i in range(QUOTA["course_trend"]):
        p, c = repeat[(i * 7) % len(repeat)]
        cases.append(pb.course_trend(p["uid"], c))
    for i in range(QUOTA["grades_submitted"]):
        term = [PREVIOUS, CURRENT, "202580", PREVIOUS][i]
        p = teachers(term)[i + 2]
        cases.append(pb.grades_submitted(p["uid"], term, AS_OF_BREAK if (i == 1) else DEFAULT_AS_OF))
    with_ta = [p for p in profs if p["rank"] != "ta" and any(any(x["role"] == "ta" for x in staff if (x["term_code"], x["crn"]) == (s["term_code"], s["crn"]))
                                                           for s in sections(p["uid"], CURRENT, min_rows=0))]
    for i in range(QUOTA["my_tas"]):
        p = with_ta[i % len(with_ta)] if i < 3 else cur_teachers[i + 30]
        cases.append(pb.my_tas(p["uid"], CURRENT))
    for i in range(QUOTA["ta_sections"]):
        cases.append(pb.ta_sections(tas[i % len(tas)]["uid"], [CURRENT, FUTURE, PREVIOUS][i]))

    # ------------------------------------------------------------ access control
    for i, scenario in enumerate(RECORD_DENIED_PLAN):
        p = prev_teachers[(i * 3 + 1) % len(prev_teachers)]
        if scenario == "other_instructor_salary":
            other = next(o for o in profs[i * 4:] + profs if o["uid"] != p["uid"])
            cases.append(pb.denied_records(p["uid"], scenario, o_uid=other["uid"]))
        elif scenario == "colleague_roster":
            other = next(o for o in cur_teachers[i * 2:] + cur_teachers if o["uid"] != p["uid"] and sections(o["uid"], CURRENT, min_rows=3))
            cases.append(pb.denied_records(p["uid"], scenario, o_uid=other["uid"], theirs=rng.choice(sections(other["uid"], CURRENT, min_rows=3))))
        elif scenario == "not_my_student_grade":
            theirs = students_of.get(p["uid"], set())
            t_uid, row = next((s, e) for s in student_ids[i * 5:] + student_ids if s not in theirs
                              for e in by_student.get(s, []) if e["status"] == "completed")
            cases.append(pb.denied_records(p["uid"], scenario, t_uid=t_uid,
                                           other_row={"term_code": row["term_code"], "term_name": term_name[row["term_code"]], "course_code": course_of[(row["term_code"], row["crn"])]}))
        else:                                                        # the student is in one of the user's sections
            s = rng.choice(sections(p["uid"], PREVIOUS, min_rows=5))
            mine_rows = [e["st"] for e in rows_of[(s["term_code"], s["crn"])] if e["st"] in unique_students]
            if scenario == "my_student_other_grade":
                t_uid, row = next((st, e) for st in mine_rows for e in by_student[st]
                                  if e["status"] == "completed" and instructor_of.get((e["term_code"], e["crn"])) != p["uid"]
                                  and (e["term_code"], e["crn"]) not in {(x["term_code"], x["crn"]) for x in secs_of[p["uid"]]})
                cases.append(pb.denied_records(p["uid"], scenario, t_uid=t_uid, mine=s,
                                               other_row={"term_code": row["term_code"], "term_name": term_name[row["term_code"]], "course_code": course_of[(row["term_code"], row["crn"])]}))
            else:
                cases.append(pb.denied_records(p["uid"], scenario, t_uid=rng.choice(mine_rows), mine=s))
    for i in range(2):
        cases.append(pb.allowed(prof(i + 100)["uid"], "own_salary"))

    for i, scenario in enumerate(DENIED_PLAN):
        p = prof(i + 62)
        other = next(o for o in profs[i * 2:] + profs if o["uid"] != p["uid"])
        wants_instructor = scenario in ("other_instructor_private", "impersonation_instructor")
        # 2026-11-05: a student who was never in the professor's sections (otherwise program, status and email are allowed)
        t_uid = never_mine(p["uid"], i) if not wants_instructor and scenario != "student_list" else None
        o_uid = other["uid"] if wants_instructor else None
        cases.append(pb.denied(p["uid"], scenario, t_uid=t_uid, o_uid=o_uid))
    for i, scenario in enumerate(ALLOWED_PLAN):
        p = prof(i + 76)
        other = next(o for o in profs[i * 3 + 1:] + profs if o["uid"] != p["uid"] and (o["n_current"] > 0 or scenario != "colleague_schedule"))
        cases.append(pb.allowed(p["uid"], scenario, term_code=CURRENT if i % 2 == 0 else FUTURE, o_uid=other["uid"] if scenario.startswith("colleague") else None,
                                course=rng.choice(with_prereq) if scenario == "prerequisites" else None))
    for i, scenario in enumerate(PARTIAL_PLAN):
        p = prof(i + 84)
        other = next(o for o in profs[i * 5 + 2:] + profs if o["uid"] != p["uid"] and o["n_current"] > 0)
        l = rng.choice(mine(p["uid"], CURRENT))
        cases.append(pb.partial(p["uid"], scenario, term_code=CURRENT, o_uid=other["uid"], t_uid=never_mine(p["uid"], 20 + i), crn=l["crn"]))

    counters: Counter = Counter()
    for c in cases:
        counters[c["intent"]] += 1
        c["id"] = f"prof-{c['intent']}-{counters[c['intent']]:03d}"
    return cases
