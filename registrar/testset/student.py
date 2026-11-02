"""Student-persona test cases: catalog, degree plan and calendar questions the twelve-table schema can answer.

Each case records the question (plus paraphrases), the simulated clock (`as_of`), the authenticated student, the SQL that
was run, the facts a correct answer must contain, a discrete `answer` and one prose reference. Answer shapes are
documented in data/testset/README.md.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime

from . import queries as Q
from .common import (DAY_NAMES, DEFAULT_AS_OF, EVENTS, ORDINAL, QueryLog, fmt_date, fmt_groups, fmt_list, fmt_meeting, fmt_time, num, pick,
                     term_phrase, with_allowed)


def person_name(r: dict) -> str:
    return f"{r['first_name']} {r['last_name']}"


def section_dict(l: dict) -> dict:
    return {"crn": l["crn"], "section_number": l["section_number"], "days": l["days"], "start": l["start_time"], "end": l["end_time"],
            "room": l["room"], "instructor": l["instructor"], "capacity": l["capacity"]}


def describe_section(l: dict) -> str:
    return f"CRN {l['crn']} ({l['section_number']}), {fmt_meeting(l['days'], l['start_time'], l['end_time'], l['room'])}, {l['instructor']}, capacity {l['capacity']}"


class Builder:
    def __init__(self, conn, rng: random.Random):
        self.conn = conn
        self.rng = rng
        self.counter = defaultdict(int)

    def case(self, intent: str, category: str, st: dict, as_of: datetime, q: QueryLog, question: str, paraphrases: list[str],
             slots: dict, facts: dict, answer: str, discrete: dict, must_not_mention: list[str] | None = None) -> dict:
        out = {
            "id": None,
            "persona": "student",
            "category": category,
            "intent": intent,
            "as_of": as_of,
            "as_of_is_default": as_of == DEFAULT_AS_OF,
            "student": {"university_id": st["university_id"], "name": person_name(st), "email": st["email"], "program_code": st["program_code"],
                        "status": st["status"]},
            "question": question,
            "paraphrases": paraphrases,
            "slots": slots,
            "answer": with_allowed(discrete),
            "sql": q.entries,
            "expected_facts": facts,
            "reference_answer": answer,
        }
        if must_not_mention:
            out["must_not_mention"] = must_not_mention
        return out

    def start(self, uid: str):
        q = QueryLog(self.conn)
        return q, Q.student_by_uid(q, uid)

    def term_slots(self, q: QueryLog, term_code: str, as_of: datetime) -> tuple[dict, dict, dict]:
        current = Q.current_term(q, as_of)
        term = current if term_code == current["code"] else Q.term_by_code(q, term_code)
        phrase, name = term_phrase(self.rng, term, current, as_of)
        return term, current, {"term": phrase, "term_name": name, "term_code": term["code"]}

    @staticmethod
    def crn_templates(templates: list[str], term: dict, current: dict) -> list[str]:
        """CRNs restart at 10001 every term, so a CRN question about any term but the current one must name the term."""
        return templates if term["code"] == current["code"] else [t for t in templates if "{term" in t]

    # ------------------------------------------------------------------ catalog
    PREREQ = ["What are the prerequisites for {course}?", "What do I need to have taken before {course}?", "Does {course} have any prerequisites?",
              "Which courses are required before I can take {course} ({title})?", "Is there a prerequisite for {course}?"]

    def prerequisites(self, uid: str, course: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        c = Q.course(q, course)
        groups = Q.prerequisites(q, course)
        question, paras = pick(self.rng, self.PREREQ, course=course, title=c["title"])
        facts = {"course": course, "groups": groups}
        discrete = {"course": course, "has_prerequisites": bool(groups), "groups": [[{"course": m["course"], "min_grade": m["min_grade"]} for m in g] for g in groups]}
        ref = f"{course} has no prerequisites." if not groups else f"{course} requires {fmt_groups(groups)}."
        return self.case("prerequisites", "catalog", st, as_of, q, question, paras, {"course": course}, facts, ref, discrete)

    COURSE_INFO = ["How many credits is {course}?", "Is {course} a lower-division, upper-division or graduate course?", "Tell me about {course}: title, credits and level.",
                   "What's the title of {course} and how many credit hours is it?", "Is {course} still an active course in the catalog?"]

    def course_info(self, uid: str, course: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        c = Q.course(q, course)
        question, paras = pick(self.rng, self.COURSE_INFO, course=course)
        discrete = {"course": course, "title": c["title"], "credit_hours": num(c["credit_hours"]), "level": c["level"], "is_active": c["is_active"],
                    "department": c["department_name"]}
        ref = (f"{course}, {c['title']}, is a {num(c['credit_hours'])}-credit {c['level'].replace('_', ' ')} course offered by {c['department_name']}"
               + ("." if c["is_active"] else "; it is no longer active."))
        return self.case("course_info", "catalog", st, as_of, q, question, paras, {"course": course}, {"course": dict(c)}, ref, discrete)

    OFFERED = ["Is {course} offered {term}?", "Will {course} be available {term}?", "Are there any sections of {course} {term}?",
               "Can I find {course} on the {term_name} schedule?"]

    def course_offered(self, uid: str, course: str, term_code: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        c = Q.course(q, course)
        lectures = [l for l in Q.lectures_of_course(q, course, term_code) if not l["is_cancelled"]]
        question, paras = pick(self.rng, self.OFFERED, course=course, **slots)
        discrete = {"course": course, "term": term["name"], "offered": bool(lectures), "crns": [l["crn"] for l in lectures], "is_active": c["is_active"]}
        ref = (f"Yes, {course} is offered in {term['name']}: {fmt_list('CRN ' + l['crn'] for l in lectures)}." if lectures
               else f"No, {course} is not offered in {term['name']}" + ("; it is no longer an active course." if not c["is_active"] else "."))
        return self.case("course_offered", "catalog", st, as_of, q, question, paras, {"course": course, **slots}, {"course": dict(c), "lectures": lectures}, ref, discrete)

    OPTIONS = ["What sections of {course} are there {term}?", "Show me the {course} sections {term} with their times.",
               "Which {course} lectures can I choose from {term}, and who teaches them?", "List the meeting times and rooms for {course} {term}."]

    def lecture_options(self, uid: str, course: str, term_code: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        lectures = [l for l in Q.lectures_of_course(q, course, term_code) if not l["is_cancelled"]]
        question, paras = pick(self.rng, self.OPTIONS, course=course, **slots)
        discrete = {"course": course, "term": term["name"], "sections": [section_dict(l) for l in lectures]}
        ref = (f"{course} in {term['name']}: " + "; ".join(describe_section(l) for l in lectures) + "." if lectures
               else f"{course} has no sections in {term['name']}.")
        return self.case("lecture_options", "catalog", st, as_of, q, question, paras, {"course": course, **slots}, {"lectures": lectures}, ref, discrete)

    MEETING = ["When does CRN {crn} meet?", "Where is CRN {crn} held {term}?", "What are the meeting days and times for CRN {crn}?",
               "Which room is CRN {crn} in, and when does it meet?", "When does CRN {crn} meet {term}?", "What are the meeting days and times for CRN {crn} {term}?",
               "Which room is CRN {crn} in {term}, and when does it meet?"]

    def lecture_meeting(self, uid: str, term_code: str, crn: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        l = Q.lecture(q, term_code, crn)
        question, paras = pick(self.rng, self.crn_templates(self.MEETING, term, current), crn=crn, **slots)
        discrete = {"crn": crn, "course": l["course_code"], "term": term["name"], "is_cancelled": l["is_cancelled"], "days": l["days"],
                    "start": l["start_time"], "end": l["end_time"], "room": l["room"], "instructor": l["instructor"]}
        ref = (f"CRN {crn} is {l['course_code']} ({l['title']}) in {term['name']}, {fmt_meeting(l['days'], l['start_time'], l['end_time'], l['room'])}, taught by {l['instructor']}"
               + (" (cancelled)." if l["is_cancelled"] else "."))
        return self.case("lecture_meeting", "catalog", st, as_of, q, question, paras, {"crn": crn, **slots}, {"lecture": l}, ref, discrete)

    WHO = ["Who teaches {course} {term}?", "Who is the instructor for {course} {term}?", "Which professor has {course} {term}?",
           "Can you tell me who's teaching {course} {term} and how to email them?"]

    def who_teaches(self, uid: str, course: str, term_code: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        lectures = [l for l in Q.lectures_of_course(q, course, term_code) if not l["is_cancelled"]]
        question, paras = pick(self.rng, self.WHO, course=course, **slots)
        discrete = {"course": course, "term": term["name"], "instructors": [{"crn": l["crn"], "instructor": l["instructor"], "email": l["instructor_email"]} for l in lectures]}
        ref = (f"{course} in {term['name']}: " + "; ".join(f"CRN {l['crn']} with {l['instructor']} ({l['instructor_email']})" for l in lectures) + "." if lectures
               else f"{course} is not offered in {term['name']}.")
        return self.case("who_teaches", "catalog", st, as_of, q, question, paras, {"course": course, **slots}, {"lectures": lectures}, ref, discrete)

    CAPACITY = ["What's the capacity of CRN {crn}?", "How many seats does CRN {crn} have in total?", "How big is the {course} section CRN {crn} {term}?",
                "What's the capacity of CRN {crn} {term}?", "How many seats does CRN {crn} have {term}?"]

    def capacity(self, uid: str, term_code: str, crn: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        l = Q.lecture(q, term_code, crn)
        taken = Q.seats_taken(q, term_code, crn)
        question, paras = pick(self.rng, self.crn_templates(self.CAPACITY, term, current), crn=crn, course=l["course_code"], **slots)
        discrete = {"crn": crn, "course": l["course_code"], "term": term["name"], "capacity": l["capacity"], "enrolled": taken, "seats_left": max(0, l["capacity"] - taken)}
        ref = f"CRN {crn} ({l['course_code']}, {term['name']}) has a capacity of {l['capacity']} seats; {taken} are taken and {discrete['seats_left']} are left."
        return self.case("capacity", "catalog", st, as_of, q, question, paras, {"crn": crn, "course": l["course_code"], **slots}, {"lecture": l, "seats_taken": taken}, ref, discrete)

    SEATS = ["How many seats are left in CRN {crn} {term}?", "Is CRN {crn} full?", "How many students are enrolled in CRN {crn} {term}?",
             "Is there still space in CRN {crn} {term}?", "Are there open seats in CRN {crn}?"]

    def seats_left(self, uid: str, term_code: str, crn: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        """The seats wording of the capacity intent (enrollment counts, 2026-11-02)."""
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        l = Q.lecture(q, term_code, crn)
        taken = Q.seats_taken(q, term_code, crn)
        question, paras = pick(self.rng, self.crn_templates(self.SEATS, term, current), crn=crn, **slots)
        discrete = {"crn": crn, "course": l["course_code"], "term": term["name"], "capacity": l["capacity"], "enrolled": taken, "seats_left": max(0, l["capacity"] - taken)}
        ref = f"CRN {crn} ({l['course_code']}, {term['name']}): {taken} of {l['capacity']} seats taken, {discrete['seats_left']} left" + (" (full)." if taken >= l["capacity"] else ".")
        return self.case("capacity", "catalog", st, as_of, q, question, paras, {"crn": crn, "course": l["course_code"], **slots}, {"lecture": l, "seats_taken": taken}, ref, discrete)

    # ------------------------------------------------------------------ degree plan
    REQUIRED = ["Which courses are required for my degree?", "What are the required courses in my program?", "List every course I have to take for my major.",
                "What's the required coursework for my degree?"]

    def degree_required(self, uid: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        rows = [r for r in Q.plan(q, st["program_code"]) if r["is_required"]]
        question, paras = pick(self.rng, self.REQUIRED)
        discrete = {"program": st["program_code"], "required": [r["course_code"] for r in rows], "required_credits": num(sum(r["credit_hours"] for r in rows))}
        ref = f"{st['program_name']} requires {len(rows)} courses ({discrete['required_credits']} credits): {fmt_list(r['course_code'] for r in rows)}."
        return self.case("degree_required", "degree", st, as_of, q, question, paras, {}, {"required": rows}, ref, discrete)

    CREDITS = ["How many credits do I need to graduate?", "How many elective credits does my program require?", "What are the credit requirements for my degree, by category?",
               "How many general education credits do I need?", "What's the total credit count for my degree, and how many must be electives?"]

    def degree_credits(self, uid: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        mins = Q.category_minimums(q, st["program_code"])
        question, paras = pick(self.rng, self.CREDITS)
        discrete = {"program": st["program_code"], "total_credits_required": st["total_credits_required"], "minimums": mins}
        ref = (f"{st['program_name']} needs {st['total_credits_required']} credits in all, including "
               + fmt_list(f"{v} {k.replace('_', ' ')} credits" for k, v in mins.items()) + "; the rest are the required courses and free electives.")
        return self.case("degree_credits", "degree", st, as_of, q, question, paras, {}, {"minimums": mins}, ref, discrete)

    IN_PLAN = ["Is {course} required for my degree?", "Does {course} count toward my program, and as what?", "Can I use {course} as an elective in my major?",
               "Where does {course} fit in my degree plan?", "Do I have to take {course} for my degree?"]

    def course_in_plan(self, uid: str, course: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        row = Q.plan_course(q, st["program_code"], course)
        question, paras = pick(self.rng, self.IN_PLAN, course=course)
        discrete = {"program": st["program_code"], "course": course, "in_plan": row is not None,
                    "category": row["category"] if row else None, "is_required": row["is_required"] if row else None,
                    "suggested_term_number": row["suggested_term_number"] if row else None}
        if row is None:
            ref = f"{course} is not part of the {st['program_code']} degree plan; it could only count as a free elective."
        elif row["is_required"]:
            ref = f"Yes, {course} is a required {row['category'].replace('_', ' ')} course for {st['program_code']}, suggested for semester {row['suggested_term_number']}."
        else:
            ref = f"{course} is one of the {row['category'].replace('_', ' ')} options for {st['program_code']}; it is not required."
        return self.case("course_in_plan", "degree", st, as_of, q, question, paras, {"course": course}, {"plan_row": row}, ref, discrete)

    PLAN_TERM = ["Which courses does my degree plan suggest for semester {n}?", "What should I take in my {nth} semester according to the plan?",
                 "What's on the four-year plan for term {n} of my program?", "What does the {nth}-semester plan look like for my degree?"]

    def plan_term(self, uid: str, n: int, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        rows = [r for r in Q.plan(q, st["program_code"]) if r["suggested_term_number"] == n]
        question, paras = pick(self.rng, self.PLAN_TERM, n=n, nth=ORDINAL[n])
        discrete = {"program": st["program_code"], "term_number": n, "courses": [r["course_code"] for r in rows]}
        ref = (f"Semester {n} of the {st['program_code']} plan: {fmt_list(r['course_code'] for r in rows)} ({num(sum(r['credit_hours'] for r in rows))} credits)." if rows
               else f"The {st['program_code']} plan lists nothing for semester {n}.")
        return self.case("plan_term", "degree", st, as_of, q, question, paras, {"term_number": n}, {"courses": rows}, ref, discrete)

    PROGRAM = ["What program am I in?", "What degree am I working toward?", "When am I expected to graduate?", "What's my status with the registrar right now?",
               "Which department is my major in, and when did I start?"]

    def my_program(self, uid: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        admit = Q.term_name(q, st["admit_term_code"])
        expected = Q.term_name(q, st["expected_graduation_term_code"])
        question, paras = pick(self.rng, self.PROGRAM)
        discrete = {"program": st["program_code"], "name": st["program_name"], "degree": st["degree"], "department": st["department_name"], "status": st["status"],
                    "admit_term": admit, "expected_graduation_term": expected}
        ref = (f"You are in the {st['program_name']} ({st['program_code']}, {st['department_name']}), status {st['status'].replace('_', ' ')}, admitted {admit}, "
               f"expected to graduate {expected or 'n/a'}.")
        return self.case("my_program", "degree", st, as_of, q, question, paras, {}, {"student": dict(st)}, ref, discrete)

    # ------------------------------------------------------------------ own record (enrollment and transfer credit, 2026-11-02)
    SCHEDULE = ["What's my schedule {term}?", "Which classes am I taking {term}?", "What am I enrolled in {term}?", "Show me my timetable {term}.",
                "What classes am I signed up for {term}?", "List my sections {term} with their times and rooms.", "What's my schedule?",
                "Which classes am I taking right now?", "What am I registered for {term}?"]
    SCHEDULE_PAST = ["What was my schedule {term}?", "What was my timetable {term}?", "Which sections was I in {term}, with their times?",
                     "Show me the schedule I had {term}."]
    SCHEDULE_DAY = ["What do I have on {day}s?", "Do I have any classes on {day}?", "What's my {day} schedule {term}?", "Which of my classes meet on {day}s {term}?",
                    "What time are my classes on {day}?"]

    def my_schedule(self, uid: str, term_code: str, as_of: datetime = DEFAULT_AS_OF, day: str | None = None) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        rows = [x for x in Q.student_term_sections(q, uid, term_code) if x["status"] != "withdrawn"]
        if day:
            name = DAY_NAMES[day]
            meetings = sorted(({"crn": x["crn"], "course": x["course_code"], "start": x["start_time"], "end": x["end_time"], "room": x["room"]}
                               for x in rows if day in x["days"]), key=lambda m: m["start"])
            templates = self.SCHEDULE_DAY if term_code == current["code"] else [t for t in self.SCHEDULE_DAY if "{term}" in t]
            question, paras = pick(self.rng, templates, day=name, **slots)
            discrete = {"term": term["name"], "day": name, "meetings": meetings, "has_classes": bool(meetings)}
            ref = (f"On {name}s in {term['name']}: " + "; ".join(f"{m['course']} (CRN {m['crn']}) {fmt_time(m['start'])}-{fmt_time(m['end'])} in {m['room']}" for m in meetings) + "."
                   if meetings else f"No classes on {name}s in {term['name']}.")
            slots = {**slots, "day": day}
        else:
            templates = (self.SCHEDULE if term_code == current["code"] else self.SCHEDULE_PAST if term["sequence"] < current["sequence"]
                         else [t for t in self.SCHEDULE if "{term}" in t])
            question, paras = pick(self.rng, templates, **slots)
            discrete = {"term": term["name"], "sections": [{"crn": x["crn"], "course": x["course_code"], "days": x["days"], "start": x["start_time"], "end": x["end_time"], "room": x["room"]}
                                                           for x in rows], "credits": num(sum(x["credit_hours"] for x in rows))}
            ref = (f"{term['name']}: " + "; ".join(f"{x['course_code']} CRN {x['crn']}, {fmt_meeting(x['days'], x['start_time'], x['end_time'], x['room'])}" for x in rows) + "."
                   if rows else f"No sections on record for {term['name']}.")
        return self.case("my_schedule", "record", st, as_of, q, question, paras, slots, {"sections": rows}, ref, discrete)

    CAN_REGISTER = ["Can I register for {course} {term}?", "Am I eligible to take {course} {term}?", "Do I meet the requirements to take {course} {term}?",
                    "Is there anything stopping me from adding {course} {term}?", "Can I get into {course} {term}?", "Would I be allowed to enroll in {course} {term}?",
                    "Can I take {course} {term}?"]
    CAN_REGISTER_CRN = ["Can I register for CRN {crn} {term}?", "Can I add CRN {crn} {term}?", "Is there room for me in CRN {crn} {term}?", "Am I able to get into CRN {crn} {term}?",
                        "Can I register for CRN {crn}?", "Is there room for me in CRN {crn}?"]

    def eligibility(self, q: QueryLog, st: dict, course: str, term: dict, as_of: datetime, crn: str | None = None) -> dict:
        """The registration-rules check (same rules as registrar/agent/programs.py: status, window, offered, prerequisites, not passed with
        C or better, not enrolled, a section with seats that fits the schedule)."""
        points = Q.grade_points(q)
        rec, transfer = Q.student_record(q, st["university_id"]), Q.transfer_credits(q, st["university_id"])
        best = Q.best_points(rec)
        transferred = {t["course_code"] for t in transfer}
        in_progress = {x["course_code"] for x in rec if x["status"] == "enrolled" and x["sequence"] < term["sequence"]}
        mine = [x for x in rec if x["term_code"] == term["code"] and x["status"] != "withdrawn"]
        today = as_of.date()
        window = "open" if term["registration_opens"] <= today <= term["add_deadline"] else "not_open" if today < term["registration_opens"] else "closed"
        lectures = [l for l in Q.lectures_of_course(q, course, term["code"]) if not l["is_cancelled"] and (crn is None or l["crn"] == crn)]
        met, missing, via = Q.prerequisite_status(Q.prerequisites(q, course), best, transferred, in_progress, points, waived=st["degree"] == "MS")
        completed = course in transferred or best.get(course, -1.0) >= 2.0
        enrolled = [x["crn"] for x in mine if x["course_code"] == course]
        seats = Q.seats_by_crn(q, term["code"], course) if lectures else {}
        busy = [(x["days"], x["start_time"], x["end_time"]) for x in mine if x["course_code"] != course]

        def clash(l):
            return any(set(l["days"]) & set(d) and l["start_time"] < e and s_ < l["end_time"] for d, s_, e in busy)
        sections = [{"crn": l["crn"], "seats_left": max(0, l["capacity"] - seats.get(l["crn"], 0)), "clash": clash(l)} for l in lectures]
        reasons = []
        if st["status"] != "active":
            reasons.append("status_not_active")
        if window != "open":
            reasons.append("registration_not_open" if window == "not_open" else "registration_closed")
        if not lectures:
            reasons.append("not_offered")
        if not met:
            reasons.append("prerequisites_not_met")
        if completed:
            reasons.append("already_completed")
        if enrolled:
            reasons.append("already_enrolled")
        if lectures and not any(x["seats_left"] > 0 for x in sections):
            reasons.append("no_seats")
        elif lectures and not any(x["seats_left"] > 0 and not x["clash"] for x in sections):
            reasons.append("time_clash")
        return {"eligible": not reasons, "reasons": reasons, "sections": sections, "missing": missing, "window": window, "in_progress": via}

    def can_register(self, uid: str, course: str, term_code: str, as_of: datetime = DEFAULT_AS_OF, crn: str | None = None) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        e = self.eligibility(q, st, course, term, as_of, crn)
        if crn:
            templates = self.CAN_REGISTER_CRN if term_code == current["code"] else [t for t in self.CAN_REGISTER_CRN if "{term}" in t]
            question, paras = pick(self.rng, templates, crn=crn, **slots)
            slots = {"crn": crn, "course": course, **slots}
        else:
            question, paras = pick(self.rng, self.CAN_REGISTER, course=course, **slots)
            slots = {"course": course, **slots}
        discrete = {"course": course, "term": term["name"], "eligible": e["eligible"], "reasons": e["reasons"]}
        if crn:
            discrete["crn"] = crn
        ref = (f"Yes: registration for {term['name']} is open, prerequisites met, seats left." if e["eligible"]
               else f"No: " + ", ".join(r.replace("_", " ") for r in e["reasons"]) + ".")
        return self.case("can_register", "record", st, as_of, q, question, paras, slots, {"eligibility": e}, ref, discrete)

    TRANSCRIPT = ["Give me my transcript.", "Can I see my transcript?", "What courses have I taken so far, with grades?", "Show me my academic record.",
                  "What's on my transcript?", "List everything I've taken here and the grades I got."]
    TRANSCRIPT_TERM = ["What did I take {term}?", "Which courses did I complete {term}, and what grades did I get?", "What are my grades for {term_name}?",
                       "Show me my {term_name} grades.", "What classes did I have {term}?"]
    TRANSCRIPT_COURSE = ["What grade did I get in {course}?", "Have I taken {course}?", "Did I pass {course}?", "Is {course} on my transcript?",
                         "When did I take {course}, and what did I get?"]

    def my_transcript(self, uid: str, as_of: datetime = DEFAULT_AS_OF, term_code: str | None = None, course: str | None = None) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q, as_of)
        rec = [x for x in Q.student_record(q, uid) if x["sequence"] <= current["sequence"]]
        transfer = Q.transfer_credits(q, uid)
        points = Q.grade_points(q)
        if course:
            attempts = [{"term": x["term_name"], "grade": x["grade"]} for x in rec if x["course_code"] == course]
            tr = any(t["course_code"] == course for t in transfer)
            best = Q.best_points([x for x in rec if x["course_code"] == course]).get(course)
            letter = next((l for l, p in points.items() if p is not None and best is not None and abs(p - best) < 1e-9), None)
            question, paras = pick(self.rng, self.TRANSCRIPT_COURSE, course=course)
            discrete = {"course": course, "taken": bool(attempts) or tr, "attempts": attempts, "best_grade": letter}
            ref = (f"{course}: " + "; ".join(f"{a['term']} {a['grade'] or 'in progress'}" for a in attempts) + ("; transfer credit" if tr else "") + "."
                   if attempts or tr else f"{course} is not on the record.")
            return self.case("my_transcript", "record", st, as_of, q, question, paras, {"course": course}, {"attempts": attempts, "transfer": tr}, ref, discrete)
        if term_code:
            term, current, slots = self.term_slots(q, term_code, as_of)
            rows = [x for x in rec if x["term_code"] == term_code]
            gpa, _ = Q.gpa_of(rows)
            question, paras = pick(self.rng, self.TRANSCRIPT_TERM, **slots)
            discrete = {"term": term["name"], "courses": [{"course": x["course_code"], "grade": x["grade"]} for x in rows], "term_gpa": gpa}
            ref = (f"{term['name']}: " + ", ".join(f"{x['course_code']} {x['grade'] or 'in progress'}" for x in rows) + (f"; term GPA {gpa:.2f}." if gpa is not None else ".")
                   if rows else f"Nothing on record for {term['name']}.")
            return self.case("my_transcript", "record", st, as_of, q, question, paras, slots, {"rows": rows}, ref, discrete)
        by_term: dict[str, dict] = {}
        for x in rec:
            by_term.setdefault(x["term_code"], {"term": x["term_name"], "courses": []})["courses"].append({"course": x["course_code"], "grade": x["grade"]})
        gpa, _ = Q.gpa_of(rec)
        question, paras = pick(self.rng, self.TRANSCRIPT)
        discrete = {"terms": list(by_term.values()), "credits_earned": num(Q.credits_earned(rec, transfer)), "gpa": gpa}
        ref = ("Transcript: " + " ".join(f"{t['term']}: " + ", ".join(f"{c['course']} {c['grade'] or 'in progress'}" for c in t["courses"]) + "." for t in by_term.values())
               + (f" Transfer credit: {fmt_list(t['course_code'] for t in transfer)}." if transfer else "") + f" Credits earned {discrete['credits_earned']}"
               + (f", GPA {gpa:.2f}." if gpa is not None else "."))
        return self.case("my_transcript", "record", st, as_of, q, question, paras, {}, {"rows": rec, "transfer": transfer}, ref, discrete)

    GPA = ["What's my GPA?", "What is my grade point average?", "How is my GPA looking?", "Can you tell me my cumulative GPA?", "What GPA do I have right now?"]
    GPA_TERM = ["What was my GPA {term}?", "What's my {term_name} GPA?", "How did I do {term}, GPA-wise?", "What grade point average did I get {term}?"]

    def my_gpa(self, uid: str, as_of: datetime = DEFAULT_AS_OF, term_code: str | None = None) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q, as_of)
        rec = [x for x in Q.student_record(q, uid) if x["sequence"] <= current["sequence"]]
        transfer = Q.transfer_credits(q, uid)
        gpa, graded = Q.gpa_of(rec)
        discrete = {"gpa": gpa, "graded_credits": num(graded), "credits_earned": num(Q.credits_earned(rec, transfer))}
        slots: dict = {}
        if term_code:
            term, current, slots = self.term_slots(q, term_code, as_of)
            tg, tc = Q.gpa_of([x for x in rec if x["term_code"] == term_code])
            discrete.update({"term": term["name"], "term_gpa": tg})
            question, paras = pick(self.rng, self.GPA_TERM, **slots)
            ref = f"{term['name']} GPA {tg:.2f}; cumulative {gpa:.2f}." if tg is not None else f"No graded credits in {term['name']}; cumulative GPA " + (f"{gpa:.2f}." if gpa is not None else "none.")
        else:
            question, paras = pick(self.rng, self.GPA)
            ref = f"Cumulative GPA {gpa:.2f} over {num(graded)} graded credits; {discrete['credits_earned']} credits earned." if gpa is not None else "No graded credits yet."
        return self.case("my_gpa", "record", st, as_of, q, question, paras, slots, {"rows": rec, "transfer": transfer}, ref, discrete)

    PROGRESS = ["What do I still need to graduate?", "How many credits have I earned so far?", "Which required courses have I not passed yet?",
                "Am I on track to finish my degree?", "How far along am I in my program?", "What's left on my degree audit?", "How many credits do I have left?"]

    def degree_progress(self, uid: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q, as_of)
        rec = [x for x in Q.student_record(q, uid) if x["sequence"] <= current["sequence"]]
        transfer = Q.transfer_credits(q, uid)
        plan = Q.plan(q, st["program_code"])
        mins = Q.category_minimums(q, st["program_code"])
        earned = {x["course_code"]: float(x["credit_hours"]) for x in rec if x["points"] is not None and float(x["points"]) > 0}
        for t in transfer:
            earned.setdefault(t["course_code"], float(t["credit_hours"]))
        cat_of = {x["course_code"]: x["category"] for x in plan}
        remaining = [x["course_code"] for x in plan if x["is_required"] and x["course_code"] not in earned]
        cats = {cat: sum(cr for c, cr in earned.items() if cat_of.get(c) == cat) for cat in mins}
        total = st["total_credits_required"]
        gpa, _ = Q.gpa_of(rec)
        done = sum(earned.values())
        complete = not remaining and done >= total and all(cats[c] >= mins[c] for c in mins) and gpa is not None and gpa >= float(st["min_gpa"])
        question, paras = pick(self.rng, self.PROGRESS)
        discrete = {"program": st["program_code"], "credits_earned": num(done), "credits_remaining": num(max(0, total - done)), "required_remaining": remaining, "complete": complete}
        ref = (f"{st['program_code']}: {num(done)} of {total} credits earned; required courses still to pass: {fmt_list(remaining) or 'none'}; "
               + " ".join(f"{c.replace('_', ' ')} {num(v)}/{mins[c]}" for c, v in cats.items()) + (f"; GPA {gpa:.2f}." if gpa is not None else "."))
        return self.case("degree_progress", "record", st, as_of, q, question, paras, {}, {"earned": earned, "remaining": remaining, "categories": cats, "gpa": gpa}, ref, discrete)

    # ------------------------------------------------------------------ calendar
    REGISTER = ["When does registration open for {term_name}?", "When can I register for {term}?", "Is registration open for {term_name} right now?",
                "Can I register for {term} yet?"]
    REGISTER_NEXT = ["When can I register for next semester?", "Is registration open for next term yet?", "When does registration for the next semester open?"]

    def register_when(self, uid: str, as_of: datetime = DEFAULT_AS_OF, term_code: str | None = None) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q, as_of)
        if term_code is None:   # "next semester": the term after the current one in session, the coming (current) term during a break
            in_session = current["start_date"] <= as_of.date() <= current["end_date"]
            term = Q.term_by_sequence(q, current["sequence"] + 1) if in_session else current
            slots = {"term": "next semester", "term_name": term["name"], "term_code": term["code"]}
            question, paras = pick(self.rng, self.REGISTER_NEXT)
        else:
            term, current, slots = self.term_slots(q, term_code, as_of)
            question, paras = pick(self.rng, self.REGISTER, **slots)
        is_open = term["registration_opens"] <= as_of.date() <= term["add_deadline"]
        discrete = {"term": term["name"], "registration_opens": term["registration_opens"], "add_deadline": term["add_deadline"], "is_open": is_open}
        ref = (f"Registration for {term['name']} opens {fmt_date(term['registration_opens'])} and adds close {fmt_date(term['add_deadline'])}; "
               + ("it is open now." if is_open else "it is not open at the moment."))
        return self.case("register_when", "calendar", st, as_of, q, question, paras, slots, {"term": dict(term)}, ref, discrete)

    DATES = {
        "classes_begin": ["When does {term_name} start?", "What's the first day of classes {term}?", "When do classes begin {term}?"],
        "classes_end": ["When does {term_name} end?", "What's the last day of the semester {term}?", "When is the end of classes {term}?"],
        "add_deadline": ["What's the last day to add a class {term}?", "Can I still add a class {term}?", "When is the add deadline {term}?"],
        "drop_deadline": ["When is the last day to drop without a W {term}?", "Can I still drop a class without a W {term}?", "What's the drop deadline {term}?"],
        "withdraw_deadline": ["What's the withdrawal deadline {term}?", "Is it too late to withdraw from a class {term}?", "When is the last day to withdraw with a W {term}?"],
        "grades_due": ["When are grades due {term}?", "When will my {term_name} grades be in?", "What's the grades-due date {term}?"],
    }

    def term_dates(self, uid: str, term_code: str, event: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        d = term[EVENTS[event]]
        question, paras = pick(self.rng, self.DATES[event], **slots)
        discrete = {"term": term["name"], "event": event, "date": d, "has_passed": as_of.date() > d}
        ref = f"{term['name']} {event.replace('_', ' ')}: {fmt_date(d)}" + (" (already passed)." if as_of.date() > d else " (still ahead).")
        return self.case("term_dates", "calendar", st, as_of, q, question, paras, {**slots, "event": event}, {"term": dict(term)}, ref, discrete)

    CURRENT_TERM = ["What semester is it right now?", "Which term are we in?", "What's the current term, and what comes next?", "What term comes after this one?"]

    def current_term(self, uid: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q, as_of)
        nxt = Q.term_by_sequence(q, current["sequence"] + 1)
        prev = Q.term_by_sequence(q, current["sequence"] - 1)
        question, paras = pick(self.rng, self.CURRENT_TERM)
        in_session = current["start_date"] <= as_of.date() <= current["end_date"]
        discrete = {"term": current["name"], "next_term": nxt["name"], "previous_term": prev["name"], "in_session": in_session}
        ref = (f"The current term is {current['name']}" + ("" if in_session else f" (classes start {fmt_date(current['start_date'])})")
               + f"; the next term is {nxt['name']} and the previous one was {prev['name']}.")
        return self.case("current_term", "calendar", st, as_of, q, question, paras, {}, {"current": dict(current)}, ref, discrete)
