"""Pick students and scenarios from the loaded database and build the student test set."""
from __future__ import annotations

import random
from collections import Counter

from psycopg.rows import dict_row

from . import queries as Q
from .common import AS_OF_BREAK, AS_OF_LATE, AS_OF_SPRING, CURRENT, DEFAULT_AS_OF, FUTURE, PREVIOUS, SNAPSHOT
from .student_access import AccessBuilder

QUOTA = {
    "prerequisites": 12, "course_info": 8, "course_offered": 10, "lecture_options": 10, "lecture_meeting": 8, "who_teaches": 8, "capacity": 6,
    "degree_required": 8, "degree_credits": 8, "course_in_plan": 10, "plan_term": 6, "my_program": 6,
    "register_when": 8, "term_dates": 12, "current_term": 6,
    # own record (enrollment and transfer credit, 2026-11-02); capacity gains 4 seats-left cases
    "my_schedule": 8, "can_register": 10, "my_transcript": 8, "my_gpa": 6, "degree_progress": 6,
}
DENIED_PLAN = ["other_program", "other_status", "other_contact", "other_dob", "other_ssn", "other_graduation", "impersonation", "student_list",
               "instructor_private", "other_contact", "impersonation", "student_list", "instructor_private", "other_ssn",
               "instructor_is_student", "instructor_is_student"]
ALLOWED_PLAN = ["instructor_of_lecture", "instructor_email", "instructor_rank", "lecture_meeting", "prerequisites", "capacity", "course_department", "instructor_of_lecture"]
PARTIAL_PLAN = ["teacher_and_phone", "same_program", "teacher_and_phone", "same_program", "ta_or_student", "instructor_rank_and_student", "ta_or_student"]
CLOCKS = [DEFAULT_AS_OF, DEFAULT_AS_OF, DEFAULT_AS_OF, SNAPSHOT, AS_OF_LATE, AS_OF_BREAK, AS_OF_SPRING]


def fetch(conn, sql, **params):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or None)
        return cur.fetchall()


def generate(conn, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    b = AccessBuilder(conn, rng)

    students = fetch(conn, "SELECT university_id AS uid, program_code, status FROM student ORDER BY university_id")
    rng.shuffle(students)
    active = [s for s in students if s["status"] == "active"]
    courses = fetch(conn, "SELECT code, level, is_active, (SELECT COUNT(DISTINCT group_number) FROM course_prerequisite cp WHERE cp.course_code = c.code) AS n_groups FROM course c ORDER BY code")
    with_prereq = [c["code"] for c in courses if c["n_groups"] > 0]
    without_prereq = [c["code"] for c in courses if c["n_groups"] == 0]
    or_groups = [r["course_code"] for r in fetch(conn, "SELECT course_code FROM course_prerequisite GROUP BY course_code, group_number HAVING COUNT(*) > 1 ORDER BY 1")]
    all_codes = [c["code"] for c in courses]
    lectures = fetch(conn, "SELECT term_code, crn, course_code, is_cancelled FROM lecture WHERE term_code IN (%(c)s, %(f)s, %(p)s) ORDER BY term_code, crn", c=CURRENT, f=FUTURE, p=PREVIOUS)
    by_term = {t: [l for l in lectures if l["term_code"] == t] for t in (CURRENT, FUTURE, PREVIOUS)}
    offered = {t: sorted({l["course_code"] for l in by_term[t] if not l["is_cancelled"]}) for t in by_term}
    multi = {t: sorted(c for c, n in Counter(l["course_code"] for l in by_term[t] if not l["is_cancelled"]).items() if n > 1) for t in by_term}
    cancelled = [l for l in lectures if l["is_cancelled"]]
    instructors = fetch(conn, "SELECT university_id AS uid FROM instructor WHERE is_active ORDER BY university_id")
    rng.shuffle(instructors)
    tas = fetch(conn, "SELECT i.university_id AS uid FROM instructor i JOIN student s USING (university_id) ORDER BY 1")
    pure_instructors = [i for i in instructors if i["uid"] not in {t["uid"] for t in tas}]

    def student(i: int) -> str:
        return active[i % len(active)]["uid"]

    cases: list[dict] = []
    # ------------------------------------------------------------ catalog
    for i in range(QUOTA["prerequisites"]):
        pool = or_groups if i % 4 == 0 else without_prereq if i % 4 == 3 else with_prereq
        cases.append(b.prerequisites(student(i), rng.choice(pool)))
    for i in range(QUOTA["course_info"]):
        pool = [c["code"] for c in courses if not c["is_active"]] if i == 0 else all_codes
        cases.append(b.course_info(student(i + 20), rng.choice(pool)))
    for i in range(QUOTA["course_offered"]):
        term = [CURRENT, FUTURE, FUTURE, PREVIOUS][i % 4]
        as_of = DEFAULT_AS_OF if i % 5 else AS_OF_BREAK
        not_offered = [c for c in all_codes if c not in offered[term]]
        code = rng.choice(not_offered if i % 3 == 0 else offered[term])
        cases.append(b.course_offered(student(i + 40), code, term, as_of))
    for i in range(QUOTA["lecture_options"]):
        term = CURRENT if i % 2 == 0 else FUTURE
        code = rng.choice(multi[term] if i % 3 else offered[term])
        cases.append(b.lecture_options(student(i + 60), code, term, DEFAULT_AS_OF if i % 4 else AS_OF_SPRING))
    for i in range(QUOTA["lecture_meeting"]):
        term = CURRENT if i % 2 == 0 else FUTURE
        l = rng.choice(by_term[term]) if i != 3 else rng.choice([c for c in cancelled if c["term_code"] == term])
        cases.append(b.lecture_meeting(student(i + 80), term, l["crn"]))
    for i in range(QUOTA["who_teaches"]):
        term = [CURRENT, FUTURE, PREVIOUS][i % 3]
        cases.append(b.who_teaches(student(i + 100), rng.choice(multi[term] if i % 2 else offered[term]), term))
    for i in range(QUOTA["capacity"]):
        term = CURRENT if i % 2 == 0 else FUTURE
        cases.append(b.capacity(student(i + 120), term, rng.choice(by_term[term])["crn"]))
    # ------------------------------------------------------------ degree plan
    grads = [s for s in active if s["program_code"].startswith("MS")]
    for i in range(QUOTA["degree_required"]):
        uid = grads[i % len(grads)]["uid"] if i % 4 == 3 else student(i + 140)
        cases.append(b.degree_required(uid))
    for i in range(QUOTA["degree_credits"]):
        uid = grads[(i + 1) % len(grads)]["uid"] if i % 4 == 2 else student(i + 150)
        cases.append(b.degree_credits(uid))
    plan_rows = fetch(conn, "SELECT program_code, course_code, is_required FROM degree_requirement ORDER BY 1, 2")
    for i in range(QUOTA["course_in_plan"]):
        uid = student(i + 160)
        prog = next(s["program_code"] for s in active if s["uid"] == uid)
        in_plan = [r for r in plan_rows if r["program_code"] == prog]
        if i % 3 == 0:
            code = rng.choice([c for c in all_codes if c not in {r["course_code"] for r in in_plan}])
        elif i % 3 == 1:
            code = rng.choice([r["course_code"] for r in in_plan if not r["is_required"]])
        else:
            code = rng.choice([r["course_code"] for r in in_plan if r["is_required"]])
        cases.append(b.course_in_plan(uid, code))
    for i in range(QUOTA["plan_term"]):
        uid = grads[i % len(grads)]["uid"] if i == 5 else student(i + 170)
        cases.append(b.plan_term(uid, [1, 3, 5, 8, 2, 3][i]))
    others = [s for s in students if s["status"] != "active"]
    for i in range(QUOTA["my_program"]):
        uid = others[i % len(others)]["uid"] if i % 2 else student(i + 180)
        cases.append(b.my_program(uid))
    # ------------------------------------------------------------ calendar
    for i, (as_of, term) in enumerate([(DEFAULT_AS_OF, None), (DEFAULT_AS_OF, FUTURE), (SNAPSHOT, None), (SNAPSHOT, FUTURE), (AS_OF_SPRING, None),
                                        (AS_OF_SPRING, FUTURE), (AS_OF_BREAK, None), (DEFAULT_AS_OF, CURRENT)]):
        cases.append(b.register_when(student(i + 190), as_of, term))
    events = ["classes_begin", "classes_end", "add_deadline", "drop_deadline", "withdraw_deadline", "grades_due"]
    for i in range(QUOTA["term_dates"]):
        as_of = CLOCKS[i % len(CLOCKS)]
        term = [CURRENT, FUTURE, CURRENT, PREVIOUS][i % 4]
        cases.append(b.term_dates(student(i + 200), term, events[i % len(events)], as_of))
    for i, as_of in enumerate([DEFAULT_AS_OF, SNAPSHOT, AS_OF_LATE, AS_OF_BREAK, AS_OF_SPRING, DEFAULT_AS_OF]):
        cases.append(b.current_term(student(i + 215), as_of))
    # ------------------------------------------------------------ access control
    for i, scenario in enumerate(DENIED_PLAN):
        uid = student(i + 230)
        t_uid = next(s["uid"] for s in students[i * 3:] if s["uid"] != uid) if scenario not in ("student_list", "instructor_private") else None
        i_uid = instructors[i % len(instructors)]["uid"] if scenario == "instructor_private" else pure_instructors[i % len(pure_instructors)]["uid"] if scenario == "instructor_is_student" else None
        cases.append(b.denied(uid, scenario, t_uid=t_uid, i_uid=i_uid))
    for i, scenario in enumerate(ALLOWED_PLAN):
        uid = student(i + 250)
        term = CURRENT if i % 2 == 0 else FUTURE
        l = rng.choice([x for x in by_term[term] if not x["is_cancelled"]])
        cases.append(b.allowed(uid, scenario, term_code=term, crn=l["crn"] if scenario in ("instructor_of_lecture", "instructor_email", "lecture_meeting", "capacity") else None,
                               course=rng.choice(with_prereq if scenario == "prerequisites" else all_codes) if scenario in ("prerequisites", "course_department") else None,
                               i_uid=instructors[(i + 5) % len(instructors)]["uid"] if scenario == "instructor_rank" else None))
    for i, scenario in enumerate(PARTIAL_PLAN):
        uid = student(i + 260)
        term = CURRENT if i % 2 == 0 else FUTURE
        l = rng.choice([x for x in by_term[term] if not x["is_cancelled"]])
        t_uid = next(s["uid"] for s in students[i * 7 + 1:] if s["uid"] != uid)
        i_uid = tas[i % len(tas)]["uid"] if scenario == "ta_or_student" else pure_instructors[(i + 3) % len(pure_instructors)]["uid"] if scenario == "instructor_rank_and_student" else None
        cases.append(b.partial(uid, scenario, term_code=term, crn=l["crn"], t_uid=t_uid, i_uid=i_uid))
    for i, (scenario, term) in enumerate([("course_roster", CURRENT), ("crn_roster", FUTURE), ("course_roster", FUTURE), ("crn_roster", CURRENT)]):
        l = rng.choice([x for x in by_term[term] if not x["is_cancelled"]])
        cases.append(b.denied(student(i + 270), scenario, term_code=term, crn=l["crn"]))

    # ------------------------------------------------------------ own record (enrollment and transfer credit, 2026-11-02)
    records = {}
    for r in fetch(conn, "SELECT e.student_university_id AS uid, e.term_code, l.course_code, e.status, e.grade FROM enrollment e "
                         "JOIN lecture l ON l.term_code = e.term_code AND l.crn = e.crn ORDER BY 1, 2, 3"):
        records.setdefault(r["uid"], []).append(r)
    history = [s for s in active if any(r["term_code"] < CURRENT and r["grade"] not in (None, "W") for r in records.get(s["uid"], []))]
    registered_next = [s for s in active if any(r["term_code"] == FUTURE for r in records.get(s["uid"], []))]
    transfers = [s for s in history if s["uid"] in {r["uid"] for r in fetch(conn, "SELECT DISTINCT student_university_id AS uid FROM transfer_credit")}]
    graduated = [s for s in students if s["status"] == "graduated"]
    newcomers = [s for s in active if s["uid"] not in {h["uid"] for h in history}]
    suspended = [s for s in students if s["status"] in ("suspended", "dismissed") and records.get(s["uid"])]
    plan_courses = {}
    for r in plan_rows:
        plan_courses.setdefault(r["program_code"], []).append(r["course_code"])

    # schedule: this term, the coming term, last term, and two weekdays
    for i in range(3):
        cases.append(b.my_schedule(student(i + 280), CURRENT))
    cases.append(b.my_schedule(registered_next[0]["uid"], FUTURE))
    cases.append(b.my_schedule(registered_next[1]["uid"], FUTURE, AS_OF_BREAK))
    cases.append(b.my_schedule(history[0]["uid"], PREVIOUS))
    cases.append(b.my_schedule(student(286), CURRENT, day="M"))
    cases.append(b.my_schedule(student(287), CURRENT, day="R"))

    # the registration-rules check: searched for by outcome, so every reason appears
    def reasons_of(uid, course, term_code, as_of=DEFAULT_AS_OF, crn=None):
        q, st = b.start(uid)
        return b.eligibility(q, st, course, Q.term_by_code(q, term_code), as_of, crn)["reasons"]

    def find(pool, term_code, want, as_of=DEFAULT_AS_OF, courses=None):
        for st in rng.sample(pool, len(pool)):
            for c in courses or plan_courses[st["program_code"]]:
                if want(reasons_of(st["uid"], c, term_code, as_of)):
                    return st["uid"], c
        raise RuntimeError("no (student, course) pair with the wanted outcome")

    for _ in range(2):
        uid, c = find(history, FUTURE, lambda r: r == [])
        cases.append(b.can_register(uid, c, FUTURE))
    uid, c = find(history, FUTURE, lambda r: r == [], AS_OF_SPRING)
    cases.append(b.can_register(uid, c, FUTURE, AS_OF_SPRING))
    for pool in (newcomers, history):
        uid, c = find(pool, FUTURE, lambda r: r == ["prerequisites_not_met"])
        cases.append(b.can_register(uid, c, FUTURE))
    uid, c = find(history, FUTURE, lambda r: r == ["already_completed"])
    cases.append(b.can_register(uid, c, FUTURE))
    uid, c = find(grads, FUTURE, lambda r: r == ["not_offered"])
    cases.append(b.can_register(uid, c, FUTURE))
    uid, c = find(history, CURRENT, lambda r: r == ["registration_closed"])
    cases.append(b.can_register(uid, c, CURRENT))
    uid, c = find(suspended, FUTURE, lambda r: "status_not_active" in r)
    cases.append(b.can_register(uid, c, FUTURE))
    crn_pool = [l for l in by_term[FUTURE] if not l["is_cancelled"]]
    found = next((st["uid"], l["crn"], l["course_code"]) for st in rng.sample(history, len(history)) for l in rng.sample(crn_pool, 12)
                 if reasons_of(st["uid"], l["course_code"], FUTURE, crn=l["crn"]) == [])
    cases.append(b.can_register(found[0], found[2], FUTURE, crn=found[1]))

    # transcript: whole record, one term, one course
    cases.append(b.my_transcript(history[1]["uid"]))
    cases.append(b.my_transcript(transfers[0]["uid"]))
    cases.append(b.my_transcript(graduated[0]["uid"]))
    cases.append(b.my_transcript(history[2]["uid"], term_code=PREVIOUS))
    cases.append(b.my_transcript(history[3]["uid"], term_code=CURRENT))
    taken = next(r["course_code"] for r in records[history[4]["uid"]] if r["grade"] not in (None, "W"))
    cases.append(b.my_transcript(history[4]["uid"], course=taken))
    not_taken = next(c for c in plan_courses[history[5]["program_code"]] if c not in {r["course_code"] for r in records[history[5]["uid"]]})
    cases.append(b.my_transcript(history[5]["uid"], course=not_taken))
    in_progress = next(r["course_code"] for r in records[history[6]["uid"]] if r["term_code"] == CURRENT)
    cases.append(b.my_transcript(history[6]["uid"], course=in_progress))

    # GPA: cumulative (including a graduate and a first-term student with none), and one term
    for st in (history[7], history[8], graduated[1], newcomers[0]):
        cases.append(b.my_gpa(st["uid"]))
    cases.append(b.my_gpa(history[9]["uid"], term_code=PREVIOUS))
    cases.append(b.my_gpa(history[10]["uid"], term_code=CURRENT, as_of=AS_OF_BREAK))

    # degree audit
    for st in (history[11], history[12], history[13], graduated[2], newcomers[1], transfers[1]):
        cases.append(b.degree_progress(st["uid"]))

    # seats left (capacity intent), the full section included
    full = fetch(conn, "SELECT e.term_code, e.crn FROM enrollment e JOIN lecture l ON l.term_code = e.term_code AND l.crn = e.crn "
                       "WHERE e.status <> 'withdrawn' GROUP BY e.term_code, e.crn, l.capacity HAVING COUNT(*) >= l.capacity ORDER BY 1, 2")
    if full:
        cases.append(b.seats_left(student(300), full[0]["term_code"], full[0]["crn"]))
    for i in range(3):
        term = CURRENT if i % 2 == 0 else FUTURE
        cases.append(b.seats_left(student(i + 301), term, rng.choice([x for x in by_term[term] if not x["is_cancelled"]])["crn"]))

    # another student's schedule or grades
    for i, scenario in enumerate(["other_schedule", "other_grades", "other_grades", "other_schedule", "other_grades"]):
        uid = student(i + 310)
        t_uid = next(s["uid"] for s in history[i * 5 + 14:] if s["uid"] != uid)
        cases.append(b.denied(uid, scenario, t_uid=t_uid))

    counters: Counter = Counter()
    for c in cases:
        counters[c["intent"]] += 1
        c["id"] = f"stu-{c['intent']}-{counters[c['intent']]:03d}"
    return cases
