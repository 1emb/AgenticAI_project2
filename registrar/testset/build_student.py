"""Pick students and scenarios from the loaded database and build the student test set."""
from __future__ import annotations

import random
from collections import Counter

from psycopg.rows import dict_row

from .student import AS_OF_APPT_PENDING, AS_OF_LATE, CURRENT, DEFAULT_AS_OF, FUTURE, SNAPSHOT, Builder
from .student_access import AccessBuilder

QUOTA = {  # intent -> target count (~150 total)
    "can_add": 32, "seats_left": 15, "taken_all": 8, "taken_term": 7, "taken_course": 8,
    "schedule_current": 15, "schedule_previous": 15, "schedule_week": 12, "schedule_day": 8,
    "transcript": 18, "gpa": 12, "register_when": 12,
}
CAN_ADD_MIX = {  # bucket -> share of can_add cases
    "yes": 10, "appointment_not_started": 4, "registration_hold": 4, "prerequisite_not_met": 5,
    "fall_add_deadline_passed": 5, "registration_not_open": 4,
}


def fetch(conn, sql, **params):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or None)
        return cur.fetchall()


def generate(conn, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    b = Builder(conn, rng)
    term_ids = {r["code"]: r["id"] for r in fetch(conn, "SELECT code, id FROM academic_term")}
    cur_id, fut_id = term_ids[CURRENT], term_ids[FUTURE]

    active = fetch(conn, """
        SELECT p.university_id AS uid, s.id AS sid,
               COUNT(e.id) FILTER (WHERE e.status = 'registered') AS reg,
               COUNT(e.id) FILTER (WHERE e.status = 'waitlisted') AS wl,
               EXISTS (SELECT 1 FROM hold h WHERE h.student_id = s.id AND h.released_at IS NULL AND h.blocks_registration) AS reg_hold,
               EXISTS (SELECT 1 FROM hold h WHERE h.student_id = s.id AND h.released_at IS NULL AND h.blocks_transcript) AS tr_hold,
               EXISTS (SELECT 1 FROM transfer_credit t WHERE t.student_id = s.id AND t.status = 'awarded') AS transfer,
               (SELECT begins_at FROM registration_appointment a WHERE a.student_id = s.id AND a.term_id = %(fut)s) AS appt,
               s.admit_term_id = %(cur)s AS new_this_term
        FROM student s JOIN person p ON p.id = s.person_id
        LEFT JOIN enrollment e ON e.student_id = s.id AND e.term_id = %(cur)s
        WHERE s.status = 'active'
        GROUP BY p.university_id, s.id, s.admit_term_id
        HAVING COUNT(e.id) FILTER (WHERE e.status = 'registered') >= 2
        ORDER BY p.university_id""", cur=cur_id, fut=fut_id)
    others = fetch(conn, """
        SELECT p.university_id AS uid, s.id AS sid, s.status
        FROM student s JOIN person p ON p.id = s.person_id WHERE s.status <> 'active' ORDER BY p.university_id""")
    rng.shuffle(active)
    rng.shuffle(others)
    by_status = {}
    for r in others:
        by_status.setdefault(r["status"], []).append(r)

    def spring_candidates(sid: int, n: int) -> list[dict]:
        """Open Spring 2027 sections of courses in the student's primary program that they have not completed."""
        rows = fetch(conn, """
            WITH done AS (
                SELECT sec.course_id FROM enrollment e JOIN section sec ON sec.id = e.section_id
                WHERE e.student_id = %(sid)s AND e.status = 'completed')
            SELECT sec.crn, sub.code AS subject, c.course_number, (SELECT COUNT(*) FROM course_prerequisite cp WHERE cp.course_id = c.id) AS n_prereq,
                   (SELECT COUNT(*) FROM section s2 WHERE s2.course_id = c.id AND s2.term_id = %(fut)s) AS n_sections
            FROM student_program sp
            JOIN program_requirement pr ON pr.program_id = sp.program_id AND pr.catalog_term_id = sp.catalog_term_id
            JOIN program_requirement_course prc ON prc.requirement_id = pr.id
            JOIN course c ON c.id = prc.course_id
            JOIN subject sub ON sub.id = c.subject_id
            JOIN section sec ON sec.course_id = c.id AND sec.term_id = %(fut)s AND sec.status = 'open'
            WHERE sp.student_id = %(sid)s AND sp.is_primary AND sp.status = 'declared' AND c.id NOT IN (SELECT course_id FROM done)
            ORDER BY sec.crn""", sid=sid, fut=fut_id)
        return rng.sample(rows, min(n, len(rows)))

    def fall_sections(sid: int) -> list[dict]:
        rows = fetch(conn, """
            SELECT sec.crn, sub.code AS subject, c.course_number, sec.status, e.student_id IS NOT NULL AS mine,
                   (SELECT COUNT(*) FROM course_prerequisite cp WHERE cp.course_id = c.id) AS n_prereq
            FROM section sec JOIN course c ON c.id = sec.course_id JOIN subject sub ON sub.id = c.subject_id
            LEFT JOIN enrollment e ON e.section_id = sec.id AND e.student_id = %(sid)s AND e.status IN ('registered', 'waitlisted')
            WHERE sec.term_id = %(cur)s ORDER BY sec.crn""", sid=sid, cur=cur_id)
        return rng.sample(rows, min(30, len(rows)))

    multi_fall = fetch(conn, """
        SELECT MIN(sec.crn) AS crn FROM section sec WHERE sec.term_id = %(cur)s
        GROUP BY sec.course_id HAVING COUNT(*) > 1 ORDER BY 1""", cur=cur_id)
    cases: list[dict] = []

    # ---------------------------------------------------------------- can_add
    buckets: dict[str, list[dict]] = {k: [] for k in CAN_ADD_MIX}
    pool = list(active)
    attempts = 0
    while any(len(buckets[k]) < v for k, v in CAN_ADD_MIX.items()) and attempts < 400:
        attempts += 1
        s = pool[attempts % len(pool)]
        want = [k for k, v in CAN_ADD_MIX.items() if len(buckets[k]) < v]
        target = rng.choice(want)
        if target == "fall_add_deadline_passed":
            secs = fall_sections(s["sid"])
            if not secs:
                continue
            # prefer the student's own section, a closed one, or a random one
            r = rng.random()
            sec = (next((x for x in secs if x["mine"]), None) if r < 0.25 else
                   next((x for x in secs if x["status"] == "closed"), None) if r < 0.5 else
                   next((x for x in secs if x["n_prereq"] == 0 and not x["mine"]), None))
            sec = sec or secs[0]
            by_course = rng.random() < 0.4
            if by_course and multi_fall and rng.random() < 0.6:
                sec = rng.choice(multi_fall)  # a course with several sections, so the answer compares them
            c = b.can_add(s["uid"], CURRENT, sec["crn"], DEFAULT_AS_OF, by_course=by_course)
            buckets[target].append(c)
            continue
        if target == "registration_not_open":
            cands = spring_candidates(s["sid"], 1)
            if not cands:
                continue
            c = b.can_add(s["uid"], FUTURE, cands[0]["crn"], SNAPSHOT, by_course=rng.random() < 0.5)
            buckets[target].append(c)
            continue
        # spring, registration open: evaluate and bucket by the first blocker
        if target == "registration_hold" and not s["reg_hold"]:
            s = next((x for x in pool if x["reg_hold"]), s)
        if target == "appointment_not_started":
            as_of = AS_OF_APPT_PENDING
            s = next((x for x in rng.sample(pool, len(pool)) if x["appt"] and x["appt"] > as_of and not x["reg_hold"]), s)
        else:
            as_of = rng.choice([DEFAULT_AS_OF, DEFAULT_AS_OF, DEFAULT_AS_OF, AS_OF_LATE])
        cands = spring_candidates(s["sid"], 6)
        if not cands:
            continue
        if target == "prerequisite_not_met":
            cands.sort(key=lambda x: -x["n_prereq"])
        elif target != "yes":
            cands.sort(key=lambda x: x["n_prereq"])
        by_course = rng.random() < 0.5
        if by_course and target == "yes":
            cands.sort(key=lambda x: -x["n_sections"])
        c = b.can_add(s["uid"], FUTURE, cands[0]["crn"], as_of, by_course=by_course)
        bl = c["expected_facts"]["sections"][0]["blockers"]
        key = "yes" if not bl else bl[0] if bl[0] in buckets else None
        if key and len(buckets[key]) < CAN_ADD_MIX[key]:
            buckets[key].append(c)
    for k in CAN_ADD_MIX:
        cases += buckets[k]

    # ---------------------------------------------------------------- when can I register
    hold_students = [x for x in active if x["reg_hold"]]
    pending = [x for x in active if x["appt"] and x["appt"] > AS_OF_APPT_PENDING and not x["reg_hold"]]
    plan = ([(active[i * 23 % len(active)], DEFAULT_AS_OF, None) for i in range(5)]
            + [(active[i * 29 % len(active)], DEFAULT_AS_OF, FUTURE) for i in range(2)]
            + [(hold_students[0], DEFAULT_AS_OF, None), (hold_students[1], DEFAULT_AS_OF, FUTURE)]
            + [(pending[0], AS_OF_APPT_PENDING, None), (pending[1], AS_OF_APPT_PENDING, FUTURE)]
            + [(active[3], SNAPSHOT, None), (by_status["withdrawn"][1], DEFAULT_AS_OF, None)])
    for s, as_of, code in plan[: QUOTA["register_when"] + 1]:
        cases.append(b.register_when(s["uid"], as_of, code))

    # ---------------------------------------------------------------- seats_left
    for i in range(QUOTA["seats_left"]):
        s = active[i]
        term = CURRENT if i % 2 == 0 else FUTURE
        rows = fetch(conn, """SELECT sec.crn, sub.code AS subject, c.course_number, sec.status FROM section sec JOIN course c ON c.id = sec.course_id
                              JOIN subject sub ON sub.id = c.subject_id WHERE sec.term_id = %(t)s ORDER BY sec.crn""", t=term_ids[term])
        closed = [x for x in rows if x["status"] == "closed"]
        r = rng.choice(closed or rows) if i % 3 == 0 else rng.choice(rows)
        if i % 5 in (1, 3):
            cases.append(b.seats(s["uid"], term, None, (r["subject"], r["course_number"]), DEFAULT_AS_OF))
        else:
            cases.append(b.seats(s["uid"], term, r["crn"], None, DEFAULT_AS_OF))

    # ---------------------------------------------------------------- classes taken
    for i in range(QUOTA["taken_all"]):
        s = active[(i * 3) % len(active)] if i < 7 else next(x for x in active if x["transfer"])
        cases.append(b.classes_taken(s["uid"], DEFAULT_AS_OF, "all"))
    for i in range(QUOTA["taken_term"]):
        s = active[(i * 5 + 1) % len(active)]
        terms = fetch(conn, "SELECT DISTINCT t.code FROM enrollment e JOIN academic_term t ON t.id = e.term_id WHERE e.student_id = %(sid)s AND t.sequence < (SELECT sequence FROM academic_term WHERE is_current) ORDER BY 1", sid=s["sid"])
        if not terms:
            terms = [{"code": CURRENT}]
        cases.append(b.classes_taken(s["uid"], DEFAULT_AS_OF, "term", term_code=rng.choice(terms)["code"]))
    for i in range(QUOTA["taken_course"]):
        s = active[(i * 7 + 2) % len(active)]
        if i % 2 == 0:
            r = fetch(conn, """SELECT sub.code AS subject, c.course_number FROM enrollment e JOIN section sec ON sec.id = e.section_id
                               JOIN course c ON c.id = sec.course_id JOIN subject sub ON sub.id = c.subject_id
                               WHERE e.student_id = %(sid)s AND e.status = 'completed' ORDER BY e.term_id, sub.code, c.course_number""", sid=s["sid"])
            r = [rng.choice(r)] if r else r
        if i % 2 == 1 or not r:
            r = spring_candidates(s["sid"], 1) or [rng.choice(fetch(conn, "SELECT sub.code AS subject, c.course_number FROM course c JOIN subject sub ON sub.id = c.subject_id ORDER BY 1, 2"))]
        cases.append(b.classes_taken(s["uid"], DEFAULT_AS_OF, "course", course=(r[0]["subject"], r[0]["course_number"])))

    # ---------------------------------------------------------------- schedule
    for i in range(QUOTA["schedule_current"]):
        if i == 0:
            s = next(x for x in active if x["wl"] > 0)
        elif i == 1:
            s = by_status["graduated"][0]
        elif i == 2:
            s = by_status["withdrawn"][0]
        else:
            s = active[(i * 11) % len(active)]
        cases.append(b.schedule(s["uid"], CURRENT, DEFAULT_AS_OF, "current"))
    for i in range(QUOTA["schedule_previous"]):
        s = active[(i * 13 + 3) % len(active)] if i < 13 else by_status["graduated"][i - 12]
        terms = fetch(conn, "SELECT DISTINCT t.code, t.sequence FROM enrollment e JOIN academic_term t ON t.id = e.term_id WHERE e.student_id = %(sid)s AND t.sequence < (SELECT sequence FROM academic_term WHERE is_current) ORDER BY t.sequence DESC", sid=s["sid"])
        if not terms:
            continue
        code = terms[0]["code"] if i % 3 == 0 else rng.choice(terms)["code"]
        cases.append(b.schedule(s["uid"], code, DEFAULT_AS_OF, "previous"))
    for i in range(QUOTA["schedule_week"]):
        s = active[(i * 17 + 5) % len(active)]
        cases.append(b.schedule(s["uid"], CURRENT, DEFAULT_AS_OF, "week"))
    for i in range(QUOTA["schedule_day"]):
        s = active[(i * 19 + 7) % len(active)]
        cases.append(b.schedule(s["uid"], CURRENT, DEFAULT_AS_OF, "day", day=rng.choice("MTWRF")))

    # ---------------------------------------------------------------- transcript
    picks = ([x for x in active if x["tr_hold"]][:3] + [x for x in active if x["transfer"]][:3] + [x for x in active if x["new_this_term"]][:2]
             + by_status["graduated"][:3] + by_status["suspended"][:1] + by_status["withdrawn"][:1])
    picks += [x for x in active if x not in picks][: QUOTA["transcript"] - len(picks)]
    for s in picks[: QUOTA["transcript"]]:
        cases.append(b.transcript(s["uid"], DEFAULT_AS_OF, "full"))
    gp = [x for x in active if x["new_this_term"]][2:3] + by_status["graduated"][3:4] + active[-10:]
    for s in gp[: QUOTA["gpa"]]:
        cases.append(b.transcript(s["uid"], DEFAULT_AS_OF, "gpa"))

    # ---------------------------------------------------------------- access control
    ab = AccessBuilder(conn, rng)
    history = [x for x in active if not x["new_this_term"]]
    denied_plan = ["other_schedule", "other_gpa", "other_grade", "other_in_section", "roster", "waitlist_names", "other_contact", "other_holds",
                   "other_transcript", "other_standing", "impersonation", "aggregate_grades", "other_schedule", "other_gpa", "roster", "impersonation",
                   "other_grade", "other_contact"]
    needs_target = {"roster", "waitlist_names", "aggregate_grades"}
    for i, sc in enumerate(denied_plan):
        s = next(x for x in active if x["wl"] > 0) if sc == "waitlist_names" else active[(i * 7 + 11) % len(active)]
        t = next(x for x in history[(i * 5 + 3) % len(history):] + history if x["uid"] != s["uid"])
        cases.append(ab.denied(s["uid"], DEFAULT_AS_OF, sc, t_uid=None if sc in needs_target else t["uid"]))
    allowed_plan = ["instructor_of_section", "instructor_email", "section_headcount", "section_meeting", "prerequisites", "waitlist_length",
                    "instructor_of_section", "section_meeting"]
    for i, sc in enumerate(allowed_plan):
        s = active[(i * 9 + 4) % len(active)]
        cases.append(ab.allowed(s["uid"], DEFAULT_AS_OF, sc))
    partial_plan = ["compare_gpa", "same_section", "classes_overlap", "compare_gpa"]
    for i, sc in enumerate(partial_plan):
        s = history[(i * 13 + 6) % len(history)]
        if sc == "same_section":  # someone registered in the same course this term
            mate = fetch(conn, """
                SELECT p.university_id AS uid FROM enrollment e JOIN section sec ON sec.id = e.section_id JOIN student st ON st.id = e.student_id JOIN person p ON p.id = st.person_id
                WHERE e.term_id = %(cur)s AND e.status = 'registered' AND e.student_id <> %(sid)s
                  AND sec.course_id IN (SELECT s2.course_id FROM enrollment e2 JOIN section s2 ON s2.id = e2.section_id WHERE e2.student_id = %(sid)s AND e2.term_id = %(cur)s AND e2.status = 'registered')
                ORDER BY p.university_id""", cur=cur_id, sid=s["sid"])
            t = rng.choice(mate) if mate else history[(i * 13 + 7) % len(history)]
        else:
            t = next(x for x in history[(i * 11 + 2) % len(history):] + history if x["uid"] != s["uid"])
        cases.append(ab.partial(s["uid"], DEFAULT_AS_OF, sc, t["uid"]))

    counts = Counter()
    for c in cases:
        counts[c["intent"]] += 1
        c["id"] = f"stu-{c['intent']}-{counts[c['intent']]:03d}"
    return cases
