"""Pick professors and scenarios from the loaded database and build the professor test set."""
from __future__ import annotations

import random
from collections import Counter

from psycopg.rows import dict_row

from .common import AS_OF_BREAK, AS_OF_LATE, AS_OF_SPRING, CURRENT, DEFAULT_AS_OF, FUTURE, PREVIOUS, SNAPSHOT
from .professor_access import ProfAccess

QUOTA = {"teach_current": 10, "teach_term": 8, "teach_week": 6, "teach_day": 6, "section_meeting": 6, "teach_load": 6, "term_dates": 8,
         "course_catalog": 8, "my_capacity": 6, "course_offered": 6, "dept_offerings": 6, "who_teaches": 6, "taught_history": 6, "load_history": 4}
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
        WHERE i.is_active GROUP BY i.university_id, i.department_code, i.rank ORDER BY i.university_id""", c=CURRENT, f=FUTURE)
    rng.shuffle(profs)
    teaching = [p for p in profs if p["n_current"] > 0]
    students = fetch(conn, "SELECT university_id AS uid FROM student ORDER BY university_id")
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
    # ------------------------------------------------------------ access control
    for i, scenario in enumerate(DENIED_PLAN):
        p = prof(i + 62)
        other = next(o for o in profs[i * 2:] + profs if o["uid"] != p["uid"])
        wants_instructor = scenario in ("other_instructor_private", "impersonation_instructor")
        t_uid = students[i]["uid"] if not wants_instructor and scenario != "student_list" else None
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
        cases.append(pb.partial(p["uid"], scenario, term_code=CURRENT, o_uid=other["uid"], t_uid=students[20 + i]["uid"], crn=l["crn"]))

    counters: Counter = Counter()
    for c in cases:
        counters[c["intent"]] += 1
        c["id"] = f"prof-{c['intent']}-{counters[c['intent']]:03d}"
    return cases
