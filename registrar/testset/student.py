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
from .common import (DEFAULT_AS_OF, EVENTS, ORDINAL, QueryLog, fmt_date, fmt_groups, fmt_list, fmt_meeting, fmt_time, num, pick,
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
        phrase, name = term_phrase(self.rng, term, current)
        return term, current, {"term": phrase, "term_name": name, "term_code": term["code"]}

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
               "Which room is CRN {crn} in, and when does it meet?"]

    def lecture_meeting(self, uid: str, term_code: str, crn: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        l = Q.lecture(q, term_code, crn)
        question, paras = pick(self.rng, self.MEETING, crn=crn, **slots)
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

    CAPACITY = ["What's the capacity of CRN {crn}?", "How many seats does CRN {crn} have in total?", "How big is the {course} section CRN {crn} {term}?"]

    def capacity(self, uid: str, term_code: str, crn: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, st = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        l = Q.lecture(q, term_code, crn)
        question, paras = pick(self.rng, self.CAPACITY, crn=crn, course=l["course_code"], **slots)
        discrete = {"crn": crn, "course": l["course_code"], "term": term["name"], "capacity": l["capacity"]}
        ref = f"CRN {crn} ({l['course_code']}, {term['name']}) has a capacity of {l['capacity']} seats."
        return self.case("capacity", "catalog", st, as_of, q, question, paras, {"crn": crn, "course": l["course_code"], **slots}, {"lecture": l}, ref, discrete)

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

    # ------------------------------------------------------------------ calendar
    REGISTER = ["When does registration open for {term_name}?", "When can I register for {term}?", "Is registration open for {term_name} right now?",
                "Can I register for {term} yet?"]
    REGISTER_NEXT = ["When can I register for next semester?", "Is registration open for next term yet?", "When does registration for the next semester open?"]

    def register_when(self, uid: str, as_of: datetime = DEFAULT_AS_OF, term_code: str | None = None) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q, as_of)
        if term_code is None:
            term = Q.term_by_sequence(q, current["sequence"] + 1)
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
