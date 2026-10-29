"""Professor-persona test cases: teaching schedule, catalog and department schedule, teaching history, calendar.

Every builder returns a case with a discrete `answer` (checked by a program), the SQL that was run, and a short prose
reference. Answer shapes are documented in data/testset/README.md.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime

from . import queries as Q
from .common import (DAY_NAMES, DEFAULT_AS_OF, EVENTS, WEEK, QueryLog, fmt_date, fmt_groups, fmt_list, fmt_meeting, fmt_time, num, pick,
                     term_phrase, with_allowed)
from .student import person_name


def sec_summary(l: dict) -> dict:
    return {"crn": l["crn"], "course": l["course_code"], "section_number": l["section_number"], "days": l["days"], "start": l["start_time"],
            "end": l["end_time"], "room": l["room"]}


def describe(l: dict) -> str:
    return f"{l['course_code']} {l['section_number']} (CRN {l['crn']}), {fmt_meeting(l['days'], l['start_time'], l['end_time'], l['room'])}"


class ProfBuilder:
    def __init__(self, conn, rng: random.Random):
        self.conn = conn
        self.rng = rng
        self.counter = defaultdict(int)

    def case(self, intent: str, category: str, pr: dict, as_of: datetime, q: QueryLog, question: str, paraphrases: list[str],
             slots: dict, facts: dict, answer: str, discrete: dict, must_not_mention: list[str] | None = None) -> dict:
        out = {
            "id": None,
            "persona": "professor",
            "category": category,
            "intent": intent,
            "as_of": as_of,
            "as_of_is_default": as_of == DEFAULT_AS_OF,
            "professor": {"university_id": pr["university_id"], "name": person_name(pr), "email": pr["email"], "department": pr["department_code"],
                          "rank": pr["rank"]},
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
        return q, Q.instructor_by_uid(q, uid)

    def term_slots(self, q: QueryLog, term_code: str, as_of: datetime) -> tuple[dict, dict, dict]:
        current = Q.current_term(q, as_of)
        term = current if term_code == current["code"] else Q.term_by_code(q, term_code)
        phrase, name = term_phrase(self.rng, term, current)
        return term, current, {"term": phrase, "term_name": name, "term_code": term["code"]}

    def my_lectures(self, q: QueryLog, uid: str, term_code: str) -> list[dict]:
        return [l for l in Q.instructor_lectures(q, uid, term_code) if not l["is_cancelled"]]

    # ------------------------------------------------------------------ schedule
    TEACH_CURRENT = ["What am I teaching this semester?", "Can you pull up my teaching schedule for {term_name}?",
                     "Which sections am I assigned to this term, and when do they meet?", "Show me my sections and rooms for this semester."]
    TEACH_PAST = ["What did I teach {term}?", "Remind me what sections I had {term}.", "Which sections did I have {term}?", "List my sections {term}."]
    TEACH_FUTURE = ["What am I scheduled to teach {term}?", "Am I teaching anything {term}, and what?", "List my sections {term}.", "What's on my schedule {term}?"]

    def teach(self, uid: str, term_code: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        lectures = self.my_lectures(q, uid, term_code)
        intent = "teach_current" if term_code == current["code"] else "teach_term"
        templates = self.TEACH_CURRENT if intent == "teach_current" else self.TEACH_PAST if term["sequence"] < current["sequence"] else self.TEACH_FUTURE
        question, paras = pick(self.rng, templates, **slots)
        discrete = {"term": term["name"], "sections": [sec_summary(l) for l in lectures]}
        ref = (f"In {term['name']} you teach " + "; ".join(describe(l) for l in lectures) + "." if lectures else f"You have no sections in {term['name']}.")
        return self.case(intent, "schedule", pr, as_of, q, question, paras, slots, {"lectures": lectures}, ref, discrete)

    WEEK_T = ["What does my teaching week look like {term}?", "Lay out my class times day by day {term}.", "Which days of the week do I teach {term}?"]

    def teach_week(self, uid: str, term_code: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        lectures = self.my_lectures(q, uid, term_code)
        by_day: dict[str, list[dict]] = {}
        for d in WEEK:
            todays = sorted((l for l in lectures if d in l["days"]), key=lambda l: l["start_time"])
            if todays:
                by_day[DAY_NAMES[d]] = [{"start": l["start_time"], "end": l["end_time"], "crn": l["crn"], "course": l["course_code"], "room": l["room"]} for l in todays]
        question, paras = pick(self.rng, self.WEEK_T, **slots)
        discrete = {"term": term["name"], "by_day": by_day, "teaching_days": list(by_day)}
        ref = (f"{term['name']}: " + "; ".join(f"{day}: " + ", ".join(f"{m['course']} {fmt_time(m['start'])}-{fmt_time(m['end'])} in {m['room']}" for m in ms)
                                              for day, ms in by_day.items()) + "." if by_day else f"You teach nothing in {term['name']}.")
        return self.case("teach_week", "schedule", pr, as_of, q, question, paras, slots, {"lectures": lectures}, ref, discrete)

    DAY_T = ["What do I teach on {day}s?", "Do I have any classes on {day} {term}?", "When is my first class on {day}, and where?", "What time am I done teaching on {day}s {term}?"]

    def teach_day(self, uid: str, term_code: str, day: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        lectures = sorted((l for l in self.my_lectures(q, uid, term_code) if day in l["days"]), key=lambda l: l["start_time"])
        day_name = DAY_NAMES[day]
        question, paras = pick(self.rng, self.DAY_T, day=day_name, **slots)
        meetings = [{"start": l["start_time"], "end": l["end_time"], "crn": l["crn"], "course": l["course_code"], "room": l["room"]} for l in lectures]
        discrete = {"term": term["name"], "day": day_name, "meetings": meetings, "has_classes": bool(meetings),
                    "first_start": meetings[0]["start"] if meetings else None, "last_end": meetings[-1]["end"] if meetings else None}
        ref = (f"{day_name}s in {term['name']}: " + ", ".join(f"{m['course']} {fmt_time(m['start'])}-{fmt_time(m['end'])} in {m['room']}" for m in meetings) + "."
               if meetings else f"You have no classes on {day_name}s in {term['name']}.")
        return self.case("teach_day", "schedule", pr, as_of, q, question, paras, {**slots, "day": day_name}, {"lectures": lectures}, ref, discrete)

    MEETING_CRN = ["Which room is CRN {crn} in?", "When and where does CRN {crn} meet?", "What time does my section CRN {crn} start?"]
    MEETING_COURSE = ["Where does my {course} class meet {term}?", "What time does my {course} section start {term}?", "What are the meeting times for my {course} section(s) {term}?"]

    def section_meeting(self, uid: str, term_code: str, crn: str | None = None, course: str | None = None, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        mine = self.my_lectures(q, uid, term_code)
        lectures = [l for l in mine if (l["crn"] == crn if crn else l["course_code"] == course)]
        if crn:
            slots.update(crn=crn, course=lectures[0]["course_code"])
            question, paras = pick(self.rng, self.MEETING_CRN, **slots)
        else:
            slots.update(course=course)
            question, paras = pick(self.rng, self.MEETING_COURSE, **slots)
        discrete = {"sections": [{"crn": l["crn"], "course": l["course_code"], "days": l["days"], "start": l["start_time"], "end": l["end_time"], "room": l["room"]} for l in lectures]}
        ref = "; ".join(describe(l) for l in lectures) + "."
        return self.case("section_meeting", "schedule", pr, as_of, q, question, paras, slots, {"lectures": lectures}, ref, discrete)

    LOAD_T = ["How many sections am I teaching {term}?", "How many credit hours am I teaching {term}?", "What's my teaching load {term}: sections and credits?",
              "How many classes do I have {term}?"]

    def teach_load(self, uid: str, term_code: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        lectures = self.my_lectures(q, uid, term_code)
        question, paras = pick(self.rng, self.LOAD_T, **slots)
        discrete = {"term": term["name"], "sections": len(lectures), "credits": num(sum(l["credit_hours"] for l in lectures))}
        ref = f"In {term['name']} you teach {len(lectures)} section(s) for {discrete['credits']} credit hours."
        return self.case("teach_load", "schedule", pr, as_of, q, question, paras, slots, {"lectures": lectures}, ref, discrete)

    DATES = {
        "classes_begin": ["When does {term_name} start?", "What's the first day of classes {term}?", "When do classes begin {term}?"],
        "classes_end": ["When does {term_name} end?", "What's the last day of classes {term}?", "When is the semester over {term}?"],
        "add_deadline": ["When is the add deadline {term}?", "Can students still add my class {term}?", "What's the last day students can add a class {term}?"],
        "drop_deadline": ["Can students still drop my class without a W {term}?", "What's the drop deadline {term}?", "When is the last day to drop without a W {term}?"],
        "withdraw_deadline": ["What's the last day my students can withdraw {term}?", "When is the withdrawal deadline {term}?", "Is it too late for a student to withdraw {term}?"],
        "grades_due": ["When are grades due {term}?", "What's the deadline for submitting grades {term}?", "By when do I have to post grades {term}?"],
        "registration_opens": ["When does registration open {term}?", "When can students start registering {term}?", "What's the registration start date {term}?"],
    }

    def term_dates(self, uid: str, term_code: str, event: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        d = term[EVENTS[event]]
        question, paras = pick(self.rng, self.DATES[event], **slots)
        discrete = {"term": term["name"], "event": event, "date": d, "has_passed": as_of.date() > d}
        ref = f"{term['name']} {event.replace('_', ' ')}: {fmt_date(d)}" + (" (already passed)." if as_of.date() > d else " (still ahead).")
        return self.case("term_dates", "schedule", pr, as_of, q, question, paras, {**slots, "event": event}, {"term": dict(term)}, ref, discrete)

    # ------------------------------------------------------------------ courses
    CATALOG = ["What are the prerequisites for {course}?", "How many credits is {course}, and is it still active?",
               "Give me the catalog entry for {course}: title, credits, level, prerequisites.", "What level is {course}, and what does it require?"]

    def course_catalog(self, uid: str, course: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        c = Q.course(q, course)
        groups = Q.prerequisites(q, course)
        question, paras = pick(self.rng, self.CATALOG, course=course)
        discrete = {"course": course, "title": c["title"], "credit_hours": num(c["credit_hours"]), "level": c["level"], "is_active": c["is_active"],
                    "prerequisites": [[{"course": m["course"], "min_grade": m["min_grade"]} for m in g] for g in groups]}
        ref = (f"{course} ({c['title']}) is a {num(c['credit_hours'])}-credit {c['level'].replace('_', ' ')} course"
               + (", no longer active" if not c["is_active"] else "") + ("; it has no prerequisites." if not groups else f"; it requires {fmt_groups(groups)}."))
        return self.case("course_catalog", "courses", pr, as_of, q, question, paras, {"course": course}, {"course": dict(c), "groups": groups}, ref, discrete)

    CAP_CRN = ["What's the capacity of CRN {crn}?", "What's the cap on my {course} section, CRN {crn}?", "How many seats does CRN {crn} have?"]
    CAP_ALL = ["How many seats do each of my sections have {term}?", "What are the capacities of my sections {term}?", "List the seat caps for everything I teach {term}."]

    def my_capacity(self, uid: str, term_code: str, crn: str | None = None, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        lectures = [l for l in self.my_lectures(q, uid, term_code) if crn is None or l["crn"] == crn]
        if crn:
            slots.update(crn=crn, course=lectures[0]["course_code"])
            question, paras = pick(self.rng, self.CAP_CRN, **slots)
        else:
            question, paras = pick(self.rng, self.CAP_ALL, **slots)
        discrete = {"term": term["name"], "sections": {l["crn"]: {"course": l["course_code"], "capacity": l["capacity"]} for l in lectures}}
        ref = "; ".join(f"CRN {l['crn']} ({l['course_code']}): {l['capacity']} seats" for l in lectures) + "."
        return self.case("my_capacity", "courses", pr, as_of, q, question, paras, slots, {"lectures": lectures}, ref, discrete)

    OFFERED = ["Is {course} on the schedule {term}?", "Is {course} being offered {term}, and who has it?", "Will there be a section of {course} {term}?",
               "Does anyone teach {course} {term}?"]

    def course_offered(self, uid: str, course: str, term_code: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        lectures = [l for l in Q.lectures_of_course(q, course, term_code) if not l["is_cancelled"]]
        question, paras = pick(self.rng, self.OFFERED, course=course, **slots)
        discrete = {"course": course, "term": term["name"], "offered": bool(lectures), "sections": [{"crn": l["crn"], "instructor": l["instructor"]} for l in lectures]}
        ref = (f"Yes: {course} in {term['name']} is " + "; ".join(f"CRN {l['crn']} with {l['instructor']}" for l in lectures) + "." if lectures
               else f"No, {course} is not on the {term['name']} schedule.")
        return self.case("course_offered", "courses", pr, as_of, q, question, paras, {"course": course, **slots}, {"lectures": lectures}, ref, discrete)

    DEPT = ["Which courses is my department offering {term}?", "What's the {dept_name} course lineup {term}?", "List the courses my department has on the schedule {term}.",
            "What is {dept_name} teaching {term}?"]

    def dept_offerings(self, uid: str, term_code: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        rows = Q.department_courses(q, pr["department_code"], term_code)
        question, paras = pick(self.rng, self.DEPT, dept_name=pr["department_name"], **slots)
        discrete = {"department": pr["department_code"], "term": term["name"], "courses": [r["course_code"] for r in rows]}
        ref = f"{pr['department_name']} offers {len(rows)} courses in {term['name']}: {fmt_list(r['course_code'] for r in rows)}."
        return self.case("dept_offerings", "courses", pr, as_of, q, question, paras, slots, {"courses": rows}, ref, discrete)

    WHO = ["Who is teaching {course} {term}?", "Which of my colleagues has {course} {term}?", "Who's covering {course} {term}?", "Who has the {course} sections {term}?"]

    def who_teaches(self, uid: str, course: str, term_code: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        term, current, slots = self.term_slots(q, term_code, as_of)
        lectures = [l for l in Q.lectures_of_course(q, course, term_code) if not l["is_cancelled"]]
        question, paras = pick(self.rng, self.WHO, course=course, **slots)
        discrete = {"course": course, "term": term["name"], "instructors": [{"crn": l["crn"], "instructor": l["instructor"]} for l in lectures]}
        ref = ("; ".join(f"CRN {l['crn']}: {l['instructor']}" for l in lectures) + "." if lectures else f"Nobody: {course} is not offered in {term['name']}.")
        return self.case("who_teaches", "courses", pr, as_of, q, question, paras, {"course": course, **slots}, {"lectures": lectures}, ref, discrete)

    HISTORY = ["When did I last teach {course}?", "Which terms have I taught {course}?", "Have I taught {course} before, and when?", "How many times have I taught {course}?"]

    def taught_history(self, uid: str, course: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q, as_of)
        rows = [r for r in Q.instructor_terms_for_course(q, uid, course) if r["sequence"] <= current["sequence"]]
        question, paras = pick(self.rng, self.HISTORY, course=course)
        discrete = {"course": course, "terms": [r["name"] for r in rows], "times": len(rows), "last_term": rows[-1]["name"] if rows else None}
        ref = (f"You have taught {course} {len(rows)} time(s): {fmt_list(r['name'] for r in rows)}; most recently {rows[-1]['name']}." if rows
               else f"You have not taught {course} so far.")
        return self.case("taught_history", "courses", pr, as_of, q, question, paras, {"course": course}, {"terms": rows}, ref, discrete)

    # ------------------------------------------------------------------ statistics
    LOAD_HISTORY = ["How many sections have I taught each term?", "What has my teaching load been term by term?", "Give me my section counts per semester so far."]

    def load_history(self, uid: str, as_of: datetime = DEFAULT_AS_OF) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q, as_of)
        rows = Q.instructor_load_by_term(q, uid, current["sequence"])
        question, paras = pick(self.rng, self.LOAD_HISTORY)
        discrete = {"by_term": {r["name"]: r["sections"] for r in rows}, "total_sections": sum(r["sections"] for r in rows), "terms": len(rows)}
        ref = "; ".join(f"{r['name']}: {r['sections']}" for r in rows) + f". {discrete['total_sections']} sections over {len(rows)} terms."
        return self.case("load_history", "statistics", pr, as_of, q, question, paras, {}, {"by_term": rows}, ref, discrete)
