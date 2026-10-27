"""Professor-persona test cases: teaching schedule, courses and rosters, statistics on their own sections, access control.

Every builder returns a case with a discrete `answer` (checked by a program), the SQL that was run, and a short prose
reference. Rules for each answer are documented in data/testset/README.md.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import datetime

from . import professor_queries as PQ
from . import student_queries as Q
from .common import (DAY_NAMES, GRADE_ORDER, WEEK, QueryLog, with_allowed, fmt_credits, fmt_date, fmt_list, fmt_meeting, fmt_time, gpa,
                     num)
from .student import (CURRENT, DEFAULT_AS_OF, UTC, course_code, describe_section, evaluate_add, pick, section_block,
                      strip_private, term_phrase)

PASS_GRADES = {"A", "A-", "B+", "B", "B-", "C+", "C", "C-", "S"}
D_GRADES = {"D+", "D", "D-"}
HEADCOUNT_STATUSES = ("completed", "withdrawn", "registered")  # not dropped, not waitlisted
ROSTER_VISIBLE = ("university_id", "name", "email", "classification", "major")


def prof_name(pr: dict) -> str:
    return f"{pr['preferred_first_name'] or pr['legal_first_name']} {pr['legal_last_name']}"


def student_name(r: dict) -> str:
    return f"{r['preferred_first_name'] or r['legal_first_name']} {r['legal_last_name']}"


def pct(n: int, d: int) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def room_of(m: dict) -> str | None:
    return f"{m['building']} {m['room_number']}" if m.get("building") else None


def sec_summary(s: dict) -> dict:
    return {"crn": s["crn"], "course": s["course"], "section_number": s["section_number"], "instruction_mode": s["instruction_mode"],
            "meetings": [{"days": m["days"], "start": m["start_time"], "end": m["end_time"], "room": room_of(m)} for m in s["_raw_meetings"]]}


def templates_for(tmpls: list[str], crn: str | None = None, course: str | None = None, **flags) -> list[str]:
    """Keep the templates that match the scope: CRN questions name a CRN, course questions a course, others neither.
    Extra flags (e.g. compare=True) require/forbid templates containing that placeholder."""
    out = []
    for t in tmpls:
        if crn and "{crn}" not in t:
            continue
        if course and not crn and ("{course}" not in t or "{crn}" in t):
            continue
        if not crn and not course and ("{crn}" in t or "{course}" in t):
            continue
        ok = True
        for k, v in flags.items():
            if (("{" + k + "}") in t) != bool(v):
                ok = False
        if ok:
            out.append(t)
    return out


def is_past(term: dict, current: dict) -> bool:
    return term["sequence"] < current["sequence"]


def counted_statuses(term: dict, current: dict) -> tuple[str, ...]:
    return ("completed", "withdrawn") if is_past(term, current) else ("registered",)


class ProfBuilder:
    def __init__(self, conn, rng: random.Random):
        self.conn = conn
        self.rng = rng

    def case(self, intent: str, category: str, pr: dict, as_of: datetime, q: QueryLog, question: str, paraphrases: list[str],
             slots: dict, answer: dict, reference: str, must_not_mention: list[str] | None = None, facts: dict | None = None) -> dict:
        out = {
            "id": None, "persona": "professor", "category": category, "intent": intent,
            "as_of": as_of, "as_of_is_default": as_of == DEFAULT_AS_OF,
            "professor": {"instructor_id": pr["instructor_id"], "university_id": pr["university_id"], "name": prof_name(pr),
                          "email": pr["email"], "department": pr["department"], "rank": pr["rank"]},
            "question": question, "paraphrases": paraphrases, "slots": slots,
            "answer": with_allowed(strip_private(answer)), "sql": q.entries, "expected_facts": strip_private(facts if facts is not None else answer),
            "reference_answer": reference,
        }
        if must_not_mention:
            out["must_not_mention"] = must_not_mention
        return out

    def start(self, uid: str):
        q = QueryLog(self.conn)
        return q, PQ.instructor_by_uid(q, uid)

    def sections(self, q: QueryLog, pr: dict, term: dict, with_seats: bool = False) -> list[dict]:
        return section_block(q, PQ.taught_sections(q, pr["instructor_id"], term["id"]), with_seats=with_seats)

    def pick_sections(self, secs: list[dict], crn: str | None, course: str | None) -> list[dict]:
        if crn:
            return [s for s in secs if s["crn"] == crn]
        if course:
            return [s for s in secs if s["course"] == course]
        return secs

    # ------------------------------------------------------------------ schedule
    TEACH_CURRENT = ["What am I teaching this semester?", "Can you pull up my teaching schedule {term}?",
                     "Which sections am I assigned to {term}, and when do they meet?", "What classes do I have {term}?",
                     "Show me my sections and rooms {term}.", "What's on my teaching schedule right now?"]
    TEACH_TERM = ["What did I teach {term}?", "What am I scheduled to teach {term}?", "Which courses did I have {term}?",
                  "Am I teaching anything {term}, and what?", "Remind me what sections I had {term}.", "List my sections {term}."]

    def teach(self, uid: str, term_code: str, as_of: datetime, mode: str) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.sections(q, pr, term)
        tp = term_phrase(self.rng, term, current)
        slots = {"term": tp, "term_name": term["name"], "term_code": term_code}
        question, paras = pick(self.rng, self.TEACH_CURRENT if mode == "current" else self.TEACH_TERM, 3, **slots)
        answer = {"term": term["name"], "sections": [sec_summary(s) for s in secs]}
        ref = (f"You teach {len(secs)} section(s) in {term['name']}:\n" + "\n".join("- " + describe_section(s, with_instructor=False) for s in secs)
               if secs else f"You have no sections in {term['name']}.")
        return self.case("teach_current" if mode == "current" else "teach_term", "schedule", pr, as_of, q, question, paras, slots, answer, ref)

    TEACH_WEEK = ["What does my teaching week look like?", "Lay out my class times day by day {term}.",
                  "Which days of the week do I teach {term}?", "Give me my weekly teaching timetable.", "When do I teach each day this week?"]
    TEACH_DAY = ["What do I teach on {day}s?", "Do I have any classes on {day}?", "When is my first class on {day}, and where?",
                 "What time am I done teaching on {day}s?", "What's my {day} teaching schedule {term}?"]

    def teach_week(self, uid: str, term_code: str, as_of: datetime, day: str | None = None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.sections(q, pr, term)
        tp = term_phrase(self.rng, term, current)
        grid: dict[str, list[dict]] = {d: [] for d in WEEK}
        online = []
        for s in secs:
            if not s["_raw_meetings"]:
                online.append(s["crn"])
            for m in s["_raw_meetings"]:
                for d in m["days"]:
                    grid[d].append({"start": m["start_time"], "end": m["end_time"], "crn": s["crn"], "course": s["course"], "room": room_of(m)})
        for d in grid:
            grid[d].sort(key=lambda x: (x["start"], x["crn"]))
        if day is None:
            slots = {"term": tp, "term_name": term["name"], "term_code": term_code}
            question, paras = pick(self.rng, self.TEACH_WEEK, 3, **slots)
            answer = {"term": term["name"], "by_day": {DAY_NAMES[d]: grid[d] for d in WEEK if grid[d]},
                      "teaching_days": [DAY_NAMES[d] for d in WEEK if grid[d]], "online_no_meeting": online}
            ref = f"Teaching week, {term['name']}:\n" + "\n".join(
                f"{DAY_NAMES[d]}: " + "; ".join(f"{fmt_time(x['start'])}-{fmt_time(x['end'])} {x['course']} (CRN {x['crn']}){' in ' + x['room'] if x['room'] else ''}" for x in grid[d])
                for d in WEEK if grid[d]) + (f"\nOnline, no set meeting: {', '.join(online)}" if online else "")
            return self.case("teach_week", "schedule", pr, as_of, q, question, paras, slots, answer, ref)
        slots = {"day": DAY_NAMES[day], "term": tp, "term_name": term["name"], "term_code": term_code}
        question, paras = pick(self.rng, self.TEACH_DAY, 3, **slots)
        ms = grid[day]
        answer = {"term": term["name"], "day": DAY_NAMES[day], "meetings": ms, "has_classes": bool(ms),
                  "first_start": ms[0]["start"] if ms else None, "last_end": max(x["end"] for x in ms) if ms else None}
        ref = (f"On {DAY_NAMES[day]}s you teach " + "; ".join(f"{x['course']} {fmt_time(x['start'])}-{fmt_time(x['end'])}{' in ' + x['room'] if x['room'] else ''}" for x in ms) + "."
               if ms else f"You have no class meetings on {DAY_NAMES[day]}s in {term['name']}.")
        return self.case("teach_day", "schedule", pr, as_of, q, question, paras, slots, answer, ref)

    SECTION_MEETING = ["Where does my {course} class meet {term}?", "Which room is CRN {crn} in?", "What time does my {course} section start?",
                       "Is my {course} section online or in person {term}?", "When and where does CRN {crn} meet?"]

    def section_meeting(self, uid: str, term_code: str, as_of: datetime, crn: str | None, course: str | None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.pick_sections(self.sections(q, pr, term), crn, course)
        tp = term_phrase(self.rng, term, current)
        slots = {"crn": secs[0]["crn"], "course": secs[0]["course"], "term": tp, "term_name": term["name"], "term_code": term_code}
        question, paras = pick(self.rng, self.SECTION_MEETING, 3, **slots)
        answer = {"sections": [{"crn": s["crn"], "course": s["course"], "instruction_mode": s["instruction_mode"],
                                "meetings": [{"days": m["days"], "start": m["start_time"], "end": m["end_time"], "building": m["building"], "room": m["room_number"]} for m in s["_raw_meetings"]]} for s in secs]}
        ref = "\n".join(describe_section(s, with_instructor=False) for s in secs)
        return self.case("section_meeting", "schedule", pr, as_of, q, question, paras, slots, answer, ref)

    TERM_EVENTS = {
        "classes_begin": ["When does {term_name} begin?", "What's the first day of classes {term}?", "When do classes start {term}?"],
        "add_deadline": ["What's the last day a student can add my class {term}?", "When is the add deadline {term}?", "Until when can students add my sections {term}?"],
        "drop_deadline": ["Can students still drop my class without a W?", "When is the last day to drop without a W {term}?", "What's the drop deadline {term}?"],
        "census": ["When is the census date {term}?", "What day is census {term}?", "When does enrollment get counted for census {term}?"],
        "withdraw_deadline": ["What's the last day my students can withdraw {term}?", "Can my students still withdraw with a W {term}?", "When is the withdrawal deadline {term}?"],
        "finals": ["When is finals week {term}?", "What are the final exam dates {term}?", "When do finals run {term}?"],
        "grades_due": ["When are grades due {term}?", "What's the deadline for me to submit final grades {term}?", "By when do I need to post grades {term}?"],
        "commencement": ["When is commencement {term}?", "What's the commencement date {term}?", "What day is graduation {term}?"],
        "holiday": ["When is {holiday} {term}?", "What are the dates of {holiday} {term}?", "When does {holiday} start and end?"],
    }

    def term_dates(self, uid: str, term_code: str, as_of: datetime, event: str) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        tp = term_phrase(self.rng, term, current)
        slots = {"term": tp, "term_name": term["name"], "term_code": term_code, "event": event}
        end = None
        label = event
        if event in ("finals", "commencement") or event.startswith("holiday:"):
            events = PQ.calendar_events(q, term["id"])
            if event.startswith("holiday:"):
                name = event.split(":", 1)[1]
                ev = next(e for e in events if e["event_type"] == "holiday" and e["name"] == name)
                slots["holiday"] = name.replace(" (no classes)", "")
                tmpl = self.TERM_EVENTS["holiday"]
            else:
                ev = next(e for e in events if e["event_type"] == event)
                tmpl = self.TERM_EVENTS[event]
            d, end = ev["event_date"], ev["end_date"]
            label = ev["name"]
        else:
            col = {"classes_begin": "start_date", "add_deadline": "add_deadline", "drop_deadline": "drop_deadline", "census": "census_date",
                   "withdraw_deadline": "withdraw_deadline", "grades_due": "grades_due"}[event]
            d = term[col]
            tmpl = self.TERM_EVENTS[event]
        question, paras = pick(self.rng, tmpl, 3, **slots)
        has_passed = as_of.date() > (end or d)
        label = {"classes_begin": "First day of classes", "add_deadline": "Add deadline", "drop_deadline": "Last day to drop without a W", "census": "Census date",
                 "withdraw_deadline": "Withdrawal deadline", "grades_due": "Grades due"}.get(event, label)
        answer = {"term": term["name"], "event": event, "date": d, "end_date": end, "has_passed": has_passed}
        ref = f"{label} for {term['name']}: {fmt_date(d)}" + (f" to {fmt_date(end)}" if end else "") + (". That has already passed." if has_passed else ". That is still ahead.")
        return self.case("term_dates", "schedule", pr, as_of, q, question, paras, slots, answer, ref)

    TEACH_LOAD = ["How many sections am I teaching {term}?", "How many credit hours am I teaching {term}?",
                  "How many students do I have in total {term}?", "What's my teaching load {term}: sections, credits, students?"]

    def teach_load(self, uid: str, term_code: str, as_of: datetime) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.sections(q, pr, term)
        enr = PQ.section_enrollments(q, [s["_section_id"] for s in secs])
        statuses = counted_statuses(term, current)
        students = sum(1 for e in enr if e["status"] in statuses)
        tp = term_phrase(self.rng, term, current)
        slots = {"term": tp, "term_name": term["name"], "term_code": term_code}
        question, paras = pick(self.rng, self.TEACH_LOAD, 3, **slots)
        answer = {"term": term["name"], "sections": len(secs), "credits": sum(s["credits"] for s in secs), "students_registered": students}
        ref = f"In {term['name']} you teach {len(secs)} section(s), {fmt_credits(answer['credits'])} credit hours, with {students} students."
        return self.case("teach_load", "schedule", pr, as_of, q, question, paras, slots, answer, ref)

    # ------------------------------------------------------------------ courses
    ENROLL_CRN = ["How many students are enrolled in CRN {crn}?", "Is my CRN {crn} section full?", "How many seats are left in CRN {crn}?",
                  "What's the headcount in my {course} section (CRN {crn})?"]
    ENROLL_COURSE = ["How many people are registered for my {course} section {term}?", "Is my {course} section full {term}?",
                     "How many seats are left in my {course} class {term}?"]
    ENROLL_ALL = ["How many students are in each of my sections {term}?", "What are the enrollment numbers for all my sections {term}?",
                  "How many seats are left in my sections {term}?", "Which of my sections {term} are full?"]

    def enrollment_count(self, uid: str, term_code: str, as_of: datetime, crn: str | None, course: str | None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.pick_sections(self.sections(q, pr, term, with_seats=True), crn, course)
        tp = term_phrase(self.rng, term, current)
        slots = {"term": tp, "term_name": term["name"], "term_code": term_code, "crn": secs[0]["crn"], "course": secs[0]["course"]}
        tmpl = self.ENROLL_CRN if crn else self.ENROLL_COURSE if course else self.ENROLL_ALL
        question, paras = pick(self.rng, tmpl, 3, **slots)
        if not crn and not course:
            slots = {k: slots[k] for k in ("term", "term_name", "term_code")}
        elif crn:
            slots.pop("course")
        else:
            slots.pop("crn")
        answer = {"sections": {s["crn"]: {"course": s["course"], "registered": s["registered"], "capacity": s["capacity"], "seats_left": s["seats_left"],
                                          "is_full": s["seats_left"] <= 0, "waitlisted": s["waitlisted"], "waitlist_capacity": s["waitlist_capacity"]} for s in secs}}
        ref = "\n".join(describe_section(s, with_seats=True, with_instructor=False) for s in secs)
        return self.case("enrollment_count", "courses", pr, as_of, q, question, paras, slots, answer, ref)

    ROSTER = ["Who is on my roster for CRN {crn}?", "Can you give me the class list for my {course} section {term}?",
              "List the students registered in my {course} class {term}.", "Who is enrolled in CRN {crn}?", "Show me the roster for my {course} section {term}."]
    ROSTER_PAST = ["Who was in my {course} section {term}?", "Can you pull the class list for CRN {crn} from {term_name}?", "Who took {course} with me {term}?"]
    WAITLIST = ["Which students are on the waitlist for CRN {crn}, in order?", "Who is waiting to get into my {course} section {term}?",
                "Is anyone waitlisted for CRN {crn}, and in what order?"]

    def roster(self, uid: str, term_code: str, as_of: datetime, crn: str, waitlist: bool = False) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        sec = self.pick_sections(self.sections(q, pr, term), crn, None)[0]
        tp = term_phrase(self.rng, term, current)
        slots = {"crn": crn, "course": sec["course"], "term": tp, "term_name": term["name"], "term_code": term_code, "status": "waitlisted" if waitlist else "registered"}
        if waitlist:
            wl = PQ.waitlist(q, sec["_section_id"])
            question, paras = pick(self.rng, self.WAITLIST, 3, **slots)
            answer = {"crn": crn, "term": term["name"], "count": len(wl), "students": [{"university_id": w["university_id"], "name": student_name(w), "position": w["position"]} for w in wl]}
            ref = (f"{len(wl)} student(s) on the waitlist for CRN {crn}: " + ", ".join(f"#{w['position']} {w['university_id']}" for w in wl)) if wl else f"No one is on the waitlist for CRN {crn}."
            return self.case("roster_waitlist", "courses", pr, as_of, q, question, paras, slots, answer, ref)
        enr = PQ.section_enrollments(q, [sec["_section_id"]])
        statuses = counted_statuses(term, current)
        rows = [e for e in enr if e["status"] in statuses]
        question, paras = pick(self.rng, self.ROSTER_PAST if is_past(term, current) else self.ROSTER, 3, **slots)
        answer = {"crn": crn, "term": term["name"], "count": len(rows), "students": [{"university_id": e["university_id"], "name": student_name(e), "status": e["status"]} for e in rows]}
        ref = f"{len(rows)} students in CRN {crn} ({sec['course']}, {term['name']}): " + ", ".join(f"{student_name(e)} ({e['university_id']}{', ' + e['status'] if e['status'] != 'registered' else ''})" for e in rows)
        return self.case("roster", "courses", pr, as_of, q, question, paras, slots, answer, ref)

    IN_SECTION = ["Is {uid} in my class {term}?", "Which of my sections is student {uid} enrolled in {term}?",
                  "Is {uid} still enrolled in CRN {crn}, or did they drop?", "Did {name} register for my {course} section {term}?"]

    def student_in_section(self, uid: str, term_code: str, as_of: datetime, target_uid: str, crn: str | None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.sections(q, pr, term)
        target = PQ.student_by_uid_public(q, target_uid)
        enr = [e for e in PQ.section_enrollments(q, [s["_section_id"] for s in secs]) if e["university_id"] == target_uid]
        by_id = {s["_section_id"]: s for s in secs}
        tp = term_phrase(self.rng, term, current)
        sec0 = by_id[enr[0]["section_id"]] if enr else (next((s for s in secs if s["crn"] == crn), secs[0]))
        slots = {"uid": target_uid, "name": student_name(target), "crn": crn or sec0["crn"], "course": sec0["course"], "term": tp, "term_name": term["name"], "term_code": term_code}
        question, paras = pick(self.rng, self.IN_SECTION, 3, **slots)
        found = [{"crn": by_id[e["section_id"]]["crn"], "course": by_id[e["section_id"]]["course"], "status": e["status"]} for e in enr]
        answer = {"university_id": target_uid, "found": bool(found), "sections": found}
        ref = (f"{student_name(target)} ({target_uid}) appears in " + fmt_list([f"CRN {f['crn']} {f['course']} ({f['status']})" for f in found]) + "."
               if found else f"{student_name(target)} ({target_uid}) is not in any of your {term['name']} sections.")
        return self.case("student_in_section", "courses", pr, as_of, q, question, paras, slots, answer, ref)

    DROPS = ["Who dropped my {course} class {term}?", "Which students left my {course} section {term}, and when?", "Has anyone withdrawn from my {course} class {term}?",
             "Has anyone withdrawn from CRN {crn}?", "Who dropped or withdrew from CRN {crn}, and when?", "Which students left CRN {crn} this term?",
             "How many students dropped or withdrew from my sections {term}, and who?", "Which students have left my classes {term}?", "Who has withdrawn from my sections {term}?"]
    DROPS_STUDENT = ["Did {uid} withdraw from my class, and on what date?", "Did {name} drop CRN {crn}? When?", "Is {uid} still in my {course} section, or did they drop or withdraw?"]

    def drops(self, uid: str, term_code: str, as_of: datetime, crn: str | None, course: str | None, target_uid: str | None = None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.pick_sections(self.sections(q, pr, term), crn, course)
        enr = PQ.section_enrollments(q, [s["_section_id"] for s in secs])
        by_id = {s["_section_id"]: s for s in secs}
        tp = term_phrase(self.rng, term, current)
        slots = {"term": tp, "term_name": term["name"], "term_code": term_code, "crn": secs[0]["crn"], "course": secs[0]["course"]}
        if target_uid:
            target = PQ.student_by_uid_public(q, target_uid)
            e = next((x for x in enr if x["university_id"] == target_uid), None)
            slots.update(uid=target_uid, name=student_name(target))
            question, paras = pick(self.rng, self.DROPS_STUDENT, 3, **slots)
            answer = {"university_id": target_uid, "status": e["status"] if e else None, "date": e["dropped_at"].date() if e and e["dropped_at"] else None}
            ref = (f"{student_name(target)} is {e['status']} in CRN {by_id[e['section_id']]['crn']}" + (f" as of {fmt_date(e['dropped_at'])}" if e["dropped_at"] else "") + "."
                   if e else f"{student_name(target)} has no enrollment in your {term['name']} sections.")
            return self.case("drops_withdrawals", "courses", pr, as_of, q, question, paras, slots, answer, ref)
        question, paras = pick(self.rng, templates_for(self.DROPS, crn, course), 3, **slots)
        if not crn and not course:
            slots = {k: slots[k] for k in ("term", "term_name", "term_code")}
        out = {s["crn"]: {"dropped": [], "withdrawn": []} for s in secs}
        for e in enr:
            if e["status"] in ("dropped", "withdrawn"):
                out[by_id[e["section_id"]]["crn"]][e["status"]].append({"university_id": e["university_id"], "name": student_name(e), "date": e["dropped_at"].date()})
        answer = {"sections": out, "total_dropped": sum(len(v["dropped"]) for v in out.values()), "total_withdrawn": sum(len(v["withdrawn"]) for v in out.values())}
        ref = "\n".join(f"CRN {c}: dropped {', '.join(d['university_id'] + ' (' + fmt_date(d['date']) + ')' for d in v['dropped']) or 'none'}; withdrawn {', '.join(d['university_id'] + ' (' + fmt_date(d['date']) + ')' for d in v['withdrawn']) or 'none'}" for c, v in out.items())
        return self.case("drops_withdrawals", "courses", pr, as_of, q, question, paras, slots, answer, ref)

    CATALOG = ["What are the prerequisites for {course}?", "How many credits is my {course} course?", "Is {course} a gen-ed course, and in which area?",
               "Is {course} lower or upper division?", "Does {course} have a corequisite?", "What does the catalog say about {course}: credits, level, prerequisites?"]

    def course_catalog(self, uid: str, as_of: datetime, course: tuple[str, str]) -> dict:
        q, pr = self.start(uid)
        cat = PQ.course_catalog(q, *course)
        rules = Q.prerequisites(q, cat["course_id"])
        groups: dict[int, list[dict]] = defaultdict(list)
        for r in rules:
            groups[r["group_number"]].append({"course": f"{r['subject']} {r['course_number']}", "type": r["prereq_type"], "min_grade": r["min_grade"]})
        slots = {"course": f"{course[0]} {course[1]}"}
        question, paras = pick(self.rng, self.CATALOG, 3, **slots)
        answer = {"course": slots["course"], "title": cat["title"], "credits_min": num(cat["credits_min"]), "credits_max": num(cat["credits_max"]),
                  "level": cat["level"], "is_gen_ed": cat["is_gen_ed"], "gen_ed_area": cat["gen_ed_area"],
                  "prerequisites": [{"group": g, "any_of": alts} for g, alts in sorted(groups.items())]}
        ref = (f"{slots['course']} {cat['title']}: {fmt_credits(cat['credits_min'])} credits, {cat['level'].replace('_', ' ')}, "
               + (f"gen-ed ({cat['gen_ed_area']})" if cat["is_gen_ed"] else "not gen-ed") + ". Prerequisites: "
               + ("; ".join(" or ".join(f"{a['course']} ({a['min_grade']}{', corequisite' if a['type'] == 'corequisite' else ''})" for a in alts) for alts in groups.values()) or "none") + ".")
        return self.case("course_catalog", "courses", pr, as_of, q, question, paras, slots, answer, ref)

    PREREQ_CHECK = ["Student {uid} wants to add my {course} section. Do they meet the prerequisites?",
                    "Can {uid} get into CRN {crn}, or do I need to sign an override?",
                    "Has {name} completed the prerequisite for {course}?",
                    "Is there room for {uid} in my {course} section {term}, and are they eligible?",
                    "Would adding {name} ({uid}) to CRN {crn} conflict with their schedule?"]
    SECTION_BLOCKERS = ("already_enrolled", "already_waitlisted", "already_enrolled_in_another_section", "prerequisite_not_met", "time_conflict",
                        "section_cancelled", "section_full")

    def prereq_check(self, uid: str, term_code: str, as_of: datetime, crn: str, target_uid: str) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        sec = self.pick_sections(self.sections(q, pr, term, with_seats=True), crn, None)[0]
        st = Q.student_by_uid(q, target_uid)
        ev = evaluate_add(q, st, term, sec, as_of)
        tp = term_phrase(self.rng, term, current)
        slots = {"uid": target_uid, "name": student_name(st), "crn": crn, "course": sec["course"], "term": tp, "term_name": term["name"], "term_code": term_code}
        question, paras = pick(self.rng, self.PREREQ_CHECK, 3, **slots)
        section_blockers = [b for b in ev["blockers"] if b in self.SECTION_BLOCKERS]
        override = [{"prerequisite_not_met": "prerequisite", "section_full": "capacity", "time_conflict": "time_conflict"}[b] for b in section_blockers
                    if b in ("prerequisite_not_met", "section_full", "time_conflict")]
        answer = {"crn": crn, "university_id": target_uid, "meets_prerequisites": ev["prerequisites"]["met"], "unmet": ev["prerequisites"]["unmet_codes"],
                  "already_in_section": ev["already_on_schedule"] is not None, "seats_left": sec["seats_left"],
                  "time_conflict": bool(ev["time_conflicts"]), "conflicting_crns": sorted({c["crn"] for c in ev["time_conflicts"]}),
                  "blockers": section_blockers, "override_needed": override,
                  "student_can_register_now": not [b for b in ev["blockers"] if b not in self.SECTION_BLOCKERS]}
        ref = (f"{student_name(st)} ({target_uid}) " + ("meets" if ev["prerequisites"]["met"] else "does not meet") + f" the prerequisites for {sec['course']}"
               + (": missing " + "; ".join(" or ".join(g) for g in ev["prerequisites"]["unmet_codes"]) if ev["prerequisites"]["unmet_codes"] else "")
               + f". CRN {crn} has {sec['seats_left']} seat(s) left" + ("; time conflict with " + ", ".join(answer["conflicting_crns"]) if answer["time_conflict"] else "")
               + (". Override needed: " + ", ".join(override) if override else ". No instructor override needed")
               + (". The student is clear to register now." if answer["student_can_register_now"] else ". The student also has a registration restriction on their side (hold, time ticket, or window) that they must resolve."))
        facts = {**ev, "section": sec}
        return self.case("student_prereq_check", "courses", pr, as_of, q, question, paras, slots, answer, ref, facts=facts)

    INCOMPLETES = ["Which of my students have an incomplete grade outstanding?", "Do I have any incompletes {term} that still need a grade?",
                   "Which incompletes in my sections have already passed their deadline?", "When does the incomplete for {uid} in my {term_name} class expire?",
                   "List the outstanding I grades in my sections and their deadlines."]

    def incompletes(self, uid: str, as_of: datetime, term_code: str | None = None, target_uid: str | None = None, only_expired: bool = False) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        secs = PQ.taught_sections_all(q, pr["instructor_id"])
        if term_code:
            secs = [s for s in secs if s["term_code"] == term_code]
        by_id = {s["section_id"]: s for s in secs}
        enr = PQ.section_enrollments(q, list(by_id))
        rows = [e for e in enr if e["grade"] == "I" and not e["is_final"]]
        if target_uid:
            rows = [e for e in rows if e["university_id"] == target_uid]
        items = [{"university_id": e["university_id"], "crn": by_id[e["section_id"]]["crn"], "course": course_code(by_id[e["section_id"]]),
                  "term": by_id[e["section_id"]]["term_name"], "deadline": e["incomplete_deadline"], "expired": as_of.date() > e["incomplete_deadline"]} for e in rows]
        if only_expired:
            items = [i for i in items if i["expired"]]
        term = Q.term_by_code(q, term_code) if term_code else None
        slots = {"only_expired": only_expired}
        if term:
            slots.update(term=term_phrase(self.rng, term, current), term_name=term["name"], term_code=term_code)
        if target_uid:
            slots["uid"] = target_uid
        tmpl = ([self.INCOMPLETES[3]] if target_uid else [self.INCOMPLETES[2]] if only_expired else [self.INCOMPLETES[1]] if term_code else [self.INCOMPLETES[0], self.INCOMPLETES[4]])
        question, paras = pick(self.rng, tmpl + [t for t in self.INCOMPLETES if t not in tmpl and "{uid}" not in t and ("{term" not in t or term)], 3, **slots)
        answer = {"incompletes": items, "count": len(items)}
        ref = ("Outstanding incompletes: " + "; ".join(f"{i['university_id']} in {i['course']} (CRN {i['crn']}, {i['term']}), deadline {fmt_date(i['deadline'])}{' (expired)' if i['expired'] else ''}" for i in items)
               if items else "You have no outstanding incomplete grades" + (" matching that" if (target_uid or only_expired or term_code) else "") + ".")
        return self.case("incompletes", "courses", pr, as_of, q, question, paras, slots, answer, ref)

    GRADE_STATUS = ["Did I submit grades for CRN {crn} {term}?", "Is grading complete for CRN {crn}?", "When did I post grades for CRN {crn}?",
                    "When did I post grades for my {course} section {term}?", "Are my {course} grades from {term_name} all in?", "Did I get my {course} grades in on time {term}?",
                    "Are any of my {term_name} students missing a grade?", "Were all grades for my {term_name} sections posted on time?", "Is grading complete for my sections {term}?"]

    def grade_status(self, uid: str, term_code: str, as_of: datetime, crn: str | None, course: str | None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.pick_sections(self.sections(q, pr, term), crn, course)
        enr = PQ.section_enrollments(q, [s["_section_id"] for s in secs])
        by_id = {s["_section_id"]: s for s in secs}
        tp = term_phrase(self.rng, term, current)
        slots = {"term": tp, "term_name": term["name"], "term_code": term_code, "crn": secs[0]["crn"], "course": secs[0]["course"]}
        question, paras = pick(self.rng, templates_for(self.GRADE_STATUS, crn, course), 3, **slots)
        if crn:
            slots.pop("course")
        elif course:
            slots.pop("crn")
        else:
            slots = {k: slots[k] for k in ("term", "term_name", "term_code")}
        out = {}
        for s in secs:
            rows = [e for e in enr if e["section_id"] == s["_section_id"] and e["status"] in ("completed", "withdrawn")]
            graded = [e for e in rows if e["grade"]]
            last = max((e["posted_at"] for e in graded), default=None)
            out[s["crn"]] = {"expected": len(rows), "graded": len(graded), "missing": [e["university_id"] for e in rows if not e["grade"]],
                             "last_posted": last.date() if last else None, "grades_due": term["grades_due"], "on_time": (last.date() <= term["grades_due"]) if last else None}
        if not is_past(term, current):  # current term: completed rows do not exist yet; expected = registered + withdrawn
            for s in secs:
                rows = [e for e in enr if e["section_id"] == s["_section_id"] and e["status"] in ("registered", "withdrawn")]
                graded = [e for e in rows if e["grade"]]
                out[s["crn"]].update(expected=len(rows), graded=len(graded), missing=[e["university_id"] for e in rows if not e["grade"]])
        answer = {"sections": out, "all_graded": all(v["graded"] >= v["expected"] for v in out.values())}
        ref = "\n".join(f"CRN {c}: {v['graded']}/{v['expected']} grades posted" + (f", last posted {fmt_date(v['last_posted'])}" if v["last_posted"] else "") + f", due {fmt_date(v['grades_due'])}"
                        + (" (on time)" if v["on_time"] else " (late)" if v["on_time"] is False else "") for c, v in out.items())
        return self.case("grade_status", "courses", pr, as_of, q, question, paras, slots, answer, ref)

    GRADE_CHANGE = ["What happened to the grade change I requested for {uid}?", "Has the grade change for {uid} been applied yet?", "Is the grade change for {uid} still pending?",
                    "Is my grade change request for CRN {crn} approved yet?", "What's the status of the grade change I submitted for CRN {crn}?", "Did the grade change for CRN {crn} go through?",
                    "Which grade changes have I requested, and what is their status?", "Do I have any grade change requests still pending?", "List the grade changes I've submitted and whether they were applied."]

    def grade_change_status(self, uid: str, as_of: datetime, target_uid: str | None, crn: str | None) -> dict:
        q, pr = self.start(uid)
        rows = PQ.grade_changes_requested(q, pr["person_id"])
        if target_uid:
            rows = [r for r in rows if r["university_id"] == target_uid]
        if crn:
            rows = [r for r in rows if r["crn"] == crn]
        slots = {k: v for k, v in {"uid": target_uid, "crn": crn}.items() if v}
        if rows:
            slots.setdefault("course", f"{rows[0]['subject']} {rows[0]['course_number']}")
        question, paras = pick(self.rng, templates_for(self.GRADE_CHANGE, crn, None, uid=bool(target_uid)), 3, **slots)
        answer = {"requests": [{"university_id": r["university_id"], "crn": r["crn"], "course": f"{r['subject']} {r['course_number']}", "term": r["term_name"],
                                "old_grade": r["old_grade"], "new_grade": r["new_grade"], "status": "applied" if r["applied_at"] else "pending",
                                "applied_at": r["applied_at"].date() if r["applied_at"] else None} for r in rows], "count": len(rows)}
        ref = ("; ".join(f"{r['university_id']} {r['subject']} {r['course_number']} ({r['term_name']}): {r['old_grade']} to {r['new_grade']}, " + ("applied " + fmt_date(r["applied_at"]) if r["applied_at"] else "pending") for r in rows)
               if rows else "You have no grade change requests on file matching that.")
        return self.case("grade_change_status", "courses", pr, as_of, q, question, paras, slots, answer, ref)

    # ------------------------------------------------------------------ statistics
    def _scope_sections(self, q: QueryLog, pr: dict, crn: str | None, course: str | None, term_code: str | None) -> list[dict]:
        secs = PQ.taught_sections_all(q, pr["instructor_id"])
        if term_code:
            secs = [s for s in secs if s["term_code"] == term_code]
        if crn:
            secs = [s for s in secs if s["crn"] == crn]
        if course:
            secs = [s for s in secs if course_code(s) == course]
        return secs

    def _scope_slots(self, q, crn, course, term_code, current):
        slots = {}
        if crn:
            slots["crn"] = crn
        if course:
            slots["course"] = course
        if term_code:
            term = Q.term_by_code(q, term_code)
            slots.update(term=term_phrase(self.rng, term, current), term_name=term["name"], term_code=term_code)
        else:
            slots["term"] = self.rng.choice(["across all terms", "over all the terms I've taught it", "overall"])
        return slots

    GRADE_DIST = ["How did grades break down in CRN {crn}?", "What was the grade distribution in CRN {crn}?", "What was the average grade in CRN {crn}?",
                  "What was the grade distribution in my {course} section {term}?", "What was the average grade in my {course} class {term}?", "How did grades break down {term} in {course}?",
                  "What's the grade distribution for everything I taught {term}?", "How many A's did I give {term}?", "How did my grades break down overall {term}?"]

    def grade_distribution(self, uid: str, as_of: datetime, crn: str | None, course: str | None, term_code: str | None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        secs = self._scope_sections(q, pr, crn, course, term_code)
        enr = PQ.section_enrollments(q, [s["section_id"] for s in secs])
        slots = self._scope_slots(q, crn, course, term_code, current)
        if crn:
            slots["course"] = course_code(next(s for s in secs if s["crn"] == crn))
        question, paras = pick(self.rng, templates_for(self.GRADE_DIST, crn, course), 3, **slots)
        graded = [e for e in enr if e["grade"]]
        counts = Counter(e["grade"] for e in graded)
        gpa_rows = [e for e in graded if e["counts_in_gpa"]]
        gpa_credits = sum(num(e["credits"]) for e in gpa_rows)
        mean = round(sum(float(e["quality_points"]) * float(e["credits"]) for e in gpa_rows) / gpa_credits, 3) if gpa_credits else None
        n_graded = sum(1 for e in graded if e["grade"] != "I")
        answer = {"scope": {"crn": crn, "course": slots.get("course"), "term": slots.get("term_name") or "all"},
                  "available": n_graded > 0, "graded": n_graded, "counts": dict(sorted(counts.items(), key=lambda kv: (GRADE_ORDER + ["W", "I", "S", "U"]).index(kv[0]) if kv[0] in GRADE_ORDER + ["W", "I", "S", "U"] else 99)),
                  "gpa_credits": gpa_credits, "mean_gpa": mean}
        ref = (f"{n_graded} grades: " + ", ".join(f"{k} {v}" for k, v in answer["counts"].items()) + f". Mean GPA {gpa(mean)}."
               if n_graded else "No grades have been posted for that scope yet.")
        return self.case("grade_distribution", "statistics", pr, as_of, q, question, paras, slots, answer, ref)

    DFW = ["What was the pass rate in CRN {crn}?", "What's the DFW rate for CRN {crn}?", "How many students failed CRN {crn}?",
           "What's my DFW rate for {course} {term}?", "How many students failed my {course} class {term}?", "What was the pass rate in my {course} sections {term}?",
           "What percentage of my students withdrew or got a D or F {term}?", "How many D's, F's and W's did I give {term}?", "What's my overall DFW rate {term}?"]

    def dfw_rate(self, uid: str, as_of: datetime, crn: str | None, course: str | None, term_code: str | None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        secs = self._scope_sections(q, pr, crn, course, term_code)
        enr = PQ.section_enrollments(q, [s["section_id"] for s in secs])
        slots = self._scope_slots(q, crn, course, term_code, current)
        if crn:
            slots["course"] = course_code(next(s for s in secs if s["crn"] == crn))
        question, paras = pick(self.rng, templates_for(self.DFW, crn, course), 3, **slots)
        rows = [e for e in enr if e["grade"] and e["grade"] != "I"]
        d = sum(1 for e in rows if e["grade"] in D_GRADES)
        f = sum(1 for e in rows if e["grade"] == "F")
        w = sum(1 for e in rows if e["grade"] == "W")
        p = sum(1 for e in rows if e["grade"] in PASS_GRADES)
        answer = {"scope": {"crn": crn, "course": slots.get("course"), "term": slots.get("term_name") or "all"}, "total": len(rows), "d": d, "f": f, "w": w,
                  "dfw_rate": pct(d + f + w, len(rows)), "pass_rate": pct(p, len(rows))}
        ref = f"Of {len(rows)} graded students: {d} D, {f} F, {w} W. DFW rate {answer['dfw_rate']}%, pass rate {answer['pass_rate']}%." if rows else "No grades posted for that scope."
        return self.case("dfw_rate", "statistics", pr, as_of, q, question, paras, slots, answer, ref)

    TREND = ["How many students did I have in {course} each semester?", "Which term had the most students in my {course} class?", "How has enrollment in my {course} course changed term by term?",
             "Did my {course} headcount increase from {from_term} to {to_term}?", "How did {course} enrollment change between {from_term} and {to_term}?", "Did I have more {course} students in {to_term} than in {from_term}?",
             "How many students were in my sections term by term?", "Which term did I have the most students overall?", "How has my total enrollment changed over the terms?"]

    def enrollment_trend(self, uid: str, as_of: datetime, course: str | None, compare: tuple[str, str] | None = None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        secs = [s for s in self._scope_sections(q, pr, None, course, None) if s["sequence"] <= current["sequence"]]
        enr = PQ.section_enrollments(q, [s["section_id"] for s in secs])
        by_sec = Counter(e["section_id"] for e in enr if e["status"] in HEADCOUNT_STATUSES)
        terms: dict[str, dict] = {}
        for s in secs:
            t = terms.setdefault(s["term_code"], {"term": s["term_name"], "sections": 0, "headcount": 0, "_seq": s["sequence"]})
            t["sections"] += 1
            t["headcount"] += by_sec.get(s["section_id"], 0)
        by_term = sorted(terms.values(), key=lambda t: t["_seq"])
        peak = max((t["headcount"] for t in by_term), default=0)
        slots = {"course": course} if course else {}
        change = None
        if compare:
            a, b = terms[compare[0]], terms[compare[1]]
            change = {"from": a["term"], "to": b["term"], "delta": b["headcount"] - a["headcount"], "increased": b["headcount"] > a["headcount"]}
            slots.update(from_term=a["term"], to_term=b["term"])
        question, paras = pick(self.rng, templates_for(self.TREND, None, course, from_term=bool(compare)), 3, **slots)
        answer = {"course": course or "all", "by_term": [{k: v for k, v in t.items() if not k.startswith("_")} for t in by_term],
                  "peak_terms": [t["term"] for t in by_term if t["headcount"] == peak], "change": change}
        ref = "; ".join(f"{t['term']}: {t['headcount']} students in {t['sections']} section(s)" for t in by_term) + f". Peak: {', '.join(answer['peak_terms'])}." + (f" {change['from']} to {change['to']}: {change['delta']:+d}." if change else "")
        return self.case("enrollment_trend", "statistics", pr, as_of, q, question, paras, slots, answer, ref)

    FILL = ["How full are my sections {term}?", "What's my overall fill rate {term}?", "Which of my sections has the most empty seats {term}?", "Are any of my sections already full {term}?"]

    def fill_rate(self, uid: str, term_code: str, as_of: datetime) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.sections(q, pr, term, with_seats=True)
        tp = term_phrase(self.rng, term, current)
        slots = {"term": tp, "term_name": term["name"], "term_code": term_code}
        question, paras = pick(self.rng, self.FILL, 3, **slots)
        cap = sum(s["capacity"] for s in secs)
        reg = sum(s["registered"] for s in secs)
        most_empty = max((s["seats_left"] for s in secs), default=0)
        answer = {"term": term["name"], "sections": {s["crn"]: {"registered": s["registered"], "capacity": s["capacity"], "fill_rate": pct(s["registered"], s["capacity"])} for s in secs},
                  "overall_fill_rate": pct(reg, cap), "most_empty": [s["crn"] for s in secs if s["seats_left"] == most_empty], "full": [s["crn"] for s in secs if s["seats_left"] <= 0]}
        ref = "; ".join(f"CRN {s['crn']} {s['registered']}/{s['capacity']} ({pct(s['registered'], s['capacity'])}%)" for s in secs) + f". Overall {answer['overall_fill_rate']}%."
        return self.case("fill_rate", "statistics", pr, as_of, q, question, paras, slots, answer, ref)

    WITHDRAW = ["What's the withdrawal rate in CRN {crn} so far?", "How many students have withdrawn from CRN {crn}?", "How many W's does CRN {crn} have {term}?",
                "Did more people withdraw from my sections {term} than {other_term}?", "How do my withdrawals {term} compare with {other_term}?", "Were there more W's in my classes {term} or {other_term}?",
                "How many students have withdrawn from my classes {term}?", "How many W's are there in my sections {term}?", "What's my withdrawal rate {term}?"]

    def withdrawal_stats(self, uid: str, term_code: str, as_of: datetime, crn: str | None, compare_term: str | None) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.pick_sections(self.sections(q, pr, term), crn, None)
        enr = PQ.section_enrollments(q, [s["_section_id"] for s in secs])
        by_id = {s["_section_id"]: s for s in secs}
        tp = term_phrase(self.rng, term, current)
        slots = {"term": tp, "term_name": term["name"], "term_code": term_code}
        if crn:
            slots["crn"] = crn
        out = {}
        for s in secs:
            rows = [e for e in enr if e["section_id"] == s["_section_id"] and e["status"] in HEADCOUNT_STATUSES]
            wd = sum(1 for e in rows if e["status"] == "withdrawn")
            out[s["crn"]] = {"withdrawn": wd, "started": len(rows), "rate": pct(wd, len(rows))}
        total_w = sum(v["withdrawn"] for v in out.values())
        total_s = sum(v["started"] for v in out.values())
        comparison = None
        if compare_term:
            other = Q.term_by_code(q, compare_term)
            osecs = self.sections(q, pr, other)
            oenr = PQ.section_enrollments(q, [s["_section_id"] for s in osecs])
            ow = sum(1 for e in oenr if e["status"] == "withdrawn")
            comparison = {"term": other["name"], "total_withdrawn": ow, "more_than_comparison": total_w > ow}
            slots.update(other_term=term_phrase(self.rng, other, current), other_term_code=compare_term)
        question, paras = pick(self.rng, templates_for(self.WITHDRAW, crn, None, other_term=bool(compare_term)), 3, **slots)
        answer = {"term": term["name"], "by_section": out, "total_withdrawn": total_w, "rate": pct(total_w, total_s), "comparison": comparison}
        ref = f"{total_w} withdrawal(s) of {total_s} students ({answer['rate']}%) in {term['name']}." + (f" {comparison['term']}: {comparison['total_withdrawn']}." if comparison else "")
        return self.case("withdrawal_stats", "statistics", pr, as_of, q, question, paras, slots, answer, ref)

    COMPOSITION = {
        "classification": ["How many freshmen, sophomores, juniors and seniors are in CRN {crn}?", "What's the class-standing breakdown of CRN {crn}?", "What year are the students in CRN {crn}?",
                           "What's the breakdown of my {course} section by class standing?", "What year are the students in my {course} class {term}?", "How many of each class standing are in my {course} section {term}?",
                           "What's the class-standing breakdown of my students {term}?", "How many of my students {term} are in each year: freshman through senior?", "What years are my students in {term}, and how many of each?"],
        "major": ["Which majors are represented in CRN {crn}, and how many of each?", "What are the majors of the students in CRN {crn}?", "How many students from each major are in CRN {crn}?",
                  "What majors are my {course} students {term}?", "Which majors are in my {course} section {term}, and how many of each?", "What's the major breakdown of my {course} class {term}?",
                  "How many students in my sections {term} are from each major?", "What's the major breakdown across all my classes {term}?", "Which majors are my students {term}, and how many of each?"],
        "college": ["How many of my CRN {crn} students are in each college?", "Which colleges are the students in CRN {crn} from?", "What's the college breakdown of CRN {crn}?",
                    "What's the college breakdown of my {course} section {term}?", "Which colleges are my {course} students from {term}?", "How many of my {course} students {term} come from each college?",
                    "Which colleges are my students from {term}?", "How many of my students {term} come from each college?", "What's the college breakdown across my sections {term}?"],
        "first_term": ["How many first-term students are in CRN {crn}?", "How many students in CRN {crn} are in their first semester here?", "How many of the students in CRN {crn} just started this term?",
                       "How many students in my {course} section are in their first semester?", "How many of my {course} students {term} are new to the university?", "How many first-semester students are in my {course} class {term}?",
                       "How many of my students {term} are brand new to the university?", "How many first-semester students do I have across my sections {term}?", "How many of my students {term} started this term?"],
    }

    def class_composition(self, uid: str, term_code: str, as_of: datetime, crn: str | None, course: str | None, dimension: str) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        secs = self.pick_sections(self.sections(q, pr, term), crn, course)
        statuses = counted_statuses(term, current)
        rows = []
        for s in secs:
            rows += [r for r in PQ.roster_profiles(q, s["_section_id"], term["sequence"]) if r["status"] in statuses]
        tp = term_phrase(self.rng, term, current)
        slots = {"term": tp, "term_name": term["name"], "term_code": term_code, "dimension": dimension}
        if crn:
            slots.update(crn=crn, course=secs[0]["course"])
        elif course:
            slots["course"] = course
        question, paras = pick(self.rng, templates_for(self.COMPOSITION[dimension], crn, course), 3, **slots)
        if dimension == "classification":
            labels = [r["classification"] or "freshman" for r in rows]
        elif dimension == "major":
            labels = [r["program"] or "undeclared" for r in rows]
        elif dimension == "college":
            labels = [r["college"] or "undeclared" for r in rows]
        else:
            labels = ["first_term" if r["admit_term_id"] == term["id"] else "continuing" for r in rows]
        counts = dict(sorted(Counter(labels).items()))
        answer = {"scope": {"crn": crn, "course": course or (secs[0]["course"] if crn else None), "term": term["name"]}, "dimension": dimension, "counts": counts, "total": len(rows)}
        ref = f"{len(rows)} students by {dimension.replace('_', ' ')}: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + "."
        return self.case("class_composition", "statistics", pr, as_of, q, question, paras, slots, answer, ref)

    TAUGHT = ["How many students have I taught in total?", "How many distinct students have taken a class with me, and over how many terms?",
              "How many sections have I taught since I started?", "What's my lifetime teaching count: students, sections, terms?"]

    def students_taught(self, uid: str, as_of: datetime) -> dict:
        q, pr = self.start(uid)
        current = Q.current_term(q)
        secs = [s for s in PQ.taught_sections_all(q, pr["instructor_id"]) if s["sequence"] <= current["sequence"]]
        enr = PQ.section_enrollments(q, [s["section_id"] for s in secs])
        students = {e["university_id"] for e in enr if e["status"] in HEADCOUNT_STATUSES}
        terms = sorted({(s["sequence"], s["term_name"]) for s in secs})
        question, paras = pick(self.rng, self.TAUGHT, 3)
        answer = {"distinct_students": len(students), "sections": len(secs), "terms": len(terms), "first_term": terms[0][1] if terms else None, "last_term": terms[-1][1] if terms else None}
        ref = f"You have taught {len(students)} distinct students in {len(secs)} sections over {len(terms)} terms ({answer['first_term']} to {answer['last_term']})."
        return self.case("students_taught", "statistics", pr, as_of, q, question, paras, {}, answer, ref)

    # ------------------------------------------------------------------ access control
    def access(self, uid: str, as_of: datetime, scenario: str, question: str, paraphrases: list[str], slots: dict, answer: dict, reference: str,
               must_not_mention: list[str] | None, q: QueryLog, pr: dict) -> dict:
        intent = "access_denied" if answer["allowed"] is False and "own_answer" not in answer else "access_partial" if answer["allowed"] is False else "access_allowed"
        return self.case(intent, "access_control", pr, as_of, q, question, paraphrases, {"scenario": scenario, **slots}, answer, reference, must_not_mention)
