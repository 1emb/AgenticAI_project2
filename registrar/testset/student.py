"""Student-persona test cases: registration, schedule, and transcript questions.

Each case records the question (plus paraphrases), the simulated clock (`as_of`), the authenticated student, the SQL that
was run, the facts a correct answer must contain, and one reference English answer. Facts are computed here, in Python,
from the SQL results; the SQL list is what an agent would need to run, in order.
"""
from __future__ import annotations

import random
import re
from collections import defaultdict
from datetime import datetime, timezone

from . import student_queries as Q
from .common import (DAY_NAMES, GRADE_ORDER, WEEK, QueryLog, with_allowed, article, cap_first, fmt_credits, fmt_date, fmt_dt, fmt_list, fmt_meeting, fmt_time, gpa,
                     grade_meets, num)

UTC = timezone.utc
SNAPSHOT = datetime(2026, 10, 19, 16, 0, tzinfo=UTC)          # the seed data is consistent as of this moment
DEFAULT_AS_OF = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)     # the clock assumed when a question names no time
AS_OF_APPT_PENDING = datetime(2026, 11, 10, 18, 0, tzinfo=UTC)  # Spring 2027 open, later time tickets not yet begun
AS_OF_LATE = datetime(2026, 12, 3, 15, 30, tzinfo=UTC)
CURRENT = "202680"
FUTURE = "202710"


# ----------------------------------------------------------------------------- helpers
def course_code(r: dict) -> str:
    return f"{r['subject']} {r['course_number']}"


def person_name(st: dict) -> str:
    return f"{st['preferred_first_name'] or st['legal_first_name']} {st['legal_last_name']}"


def term_phrase(rng: random.Random, term: dict, current: dict) -> str:
    """How a student might refer to the term, as a phrase that follows a verb or noun ("... in Fall 2024?", "... this semester?")."""
    opts = [f"in {term['name']}", f"for {term['name']}"]
    if term["code"] == current["code"]:
        opts += ["this semester", f"this {term['term_type']}", "this term"]
    elif term["sequence"] == current["sequence"] + 1:
        opts += ["next semester", f"in the {term['term_type']}", "next term"]
    elif term["sequence"] == current["sequence"] - 1 or (term["sequence"] == current["sequence"] - 2 and term["term_type"] == "spring"):
        opts += ["last semester", f"last {term['term_type']}"]
    return rng.choice(opts)


def pick(rng: random.Random, templates: list[str], n: int, **slots) -> tuple[str, list[str]]:
    chosen = rng.sample(templates, k=min(n, len(templates)))
    # term phrases may carry their own preposition ("in Fall 2025"); drop the second of two adjacent ones ("enrolled in in Fall 2025")
    rendered = [re.sub(r"\b(in|for|during) (?:in|for|during)\b", r"\1", t.format(**slots)) for t in chosen]
    return rendered[0], rendered[1:]


def section_block(q: QueryLog, rows: list[dict], with_seats: bool = True) -> list[dict]:
    """Attach meetings, instructors, and seat counts to section rows (from any of the section queries)."""
    ids = [r["section_id"] for r in rows]
    mts = defaultdict(list)
    for m in Q.meetings(q, ids):
        mts[m["section_id"]].append(m)
    ins = defaultdict(list)
    for i in Q.instructors(q, ids):
        ins[i["section_id"]].append(i)
    seats = Q.seat_counts(q, ids) if with_seats else {}
    out = []
    for r in rows:
        s = seats.get(r["section_id"], {})
        d = {
            "crn": r["crn"], "course": course_code(r), "title": r["title"], "section_number": r["section_number"],
            "credits": num(r["credits"]), "instruction_mode": r["instruction_mode"],
            "section_status": r.get("section_status", r.get("status")),
            "capacity": s.get("capacity"), "registered": s.get("registered"),
            "seats_left": (s["capacity"] - s["registered"]) if s else None,
            "waitlist_capacity": s.get("waitlist_capacity"), "waitlisted": s.get("waitlisted"),
            "meetings": [{"days": m["days"], "start": m["start_time"], "end": m["end_time"], "type": m["meeting_type"],
                          "building": m["building"], "building_name": m["building_name"], "room": m["room_number"]}
                         for m in mts[r["section_id"]]],
            "instructors": [{"name": f"{i['legal_first_name']} {i['legal_last_name']}", "role": i["role"]} for i in ins[r["section_id"]]],
            "_section_id": r["section_id"], "_course_id": r["course_id"], "_raw_meetings": mts[r["section_id"]],
        }
        if "enrollment_id" in r:  # came from term_schedule: carry the student's enrollment status
            d["enrollment_status"] = r["status"]
            d["grading_basis"] = r["grading_basis"]
            d["registered_at"] = r["registered_at"]
            d["dropped_at"] = r["dropped_at"]
        out.append(d)
    return out


def describe_section(s: dict, with_seats=False, with_instructor=True) -> str:
    parts = [f"CRN {s['crn']} {s['course']} {s['section_number']} ({s['title']}, {fmt_credits(s['credits'])} cr)"]
    if s["meetings"]:
        parts.append("; ".join(fmt_meeting(m) for m in s["_raw_meetings"]))
    else:
        parts.append("online, no set meeting time" if s["instruction_mode"] == "online" else "no meeting time listed")
    prim = [i["name"] for i in s["instructors"] if i["role"] == "primary"]
    if prim and with_instructor:
        parts.append(f"with {prim[0]}")
    if with_seats and s["capacity"] is not None:
        parts.append(f"{s['seats_left']} of {s['capacity']} seats open" if s["seats_left"] > 0
                     else f"full ({s['registered']}/{s['capacity']}), {s['waitlisted']} of {s['waitlist_capacity']} waitlist spots taken")
    return ", ".join(parts)


def action_label(t: str) -> str:
    return "dean's list" if t == "deans_list" else t.replace("_", " ")


def strip_private(obj):
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_private(v) for v in obj]
    return obj


def best_grade(a: str | None, b: str | None) -> str | None:
    """None means credit without a letter grade (transfer/test), which satisfies any minimum."""
    if a is None or b is None:
        return None
    rank = lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else (GRADE_ORDER.index("C") if g == "S" else 99)
    return a if rank(a) <= rank(b) else b


def overlaps(a: dict, b: dict) -> bool:
    return bool(set(a["days"]) & set(b["days"])) and a["start_time"] < b["end_time"] and b["start_time"] < a["end_time"]


# ----------------------------------------------------------------------------- add-eligibility evaluator
def evaluate_add(q: QueryLog, st: dict, term: dict, sec: dict, as_of: datetime) -> dict:
    """Everything the registrar checks before adding one section to a student's schedule."""
    blockers: list[str] = []
    if st["status"] != "active":
        blockers.append("student_not_active")

    as_of_date = as_of.date()
    window = {"registration_opens": term["registration_opens"], "add_deadline": term["add_deadline"],
              "in_window": term["registration_opens"] <= as_of_date <= term["add_deadline"]}
    if as_of_date < term["registration_opens"]:
        blockers.append("registration_not_open")
    elif as_of_date > term["add_deadline"]:
        blockers.append("add_deadline_passed")

    appt = Q.appointment(q, st["student_id"], term["id"])
    appt_facts = None
    if appt:
        appt_facts = {"begins_at": appt["begins_at"], "ends_at": appt["ends_at"], "priority_group": appt["priority_group"],
                      "started": appt["begins_at"] <= as_of}
        if not appt_facts["started"] and "registration_not_open" not in blockers:
            blockers.append("appointment_not_started")

    holds = [h for h in Q.active_holds(q, st["student_id"]) if h["blocks_registration"]]
    if holds:
        blockers.append("registration_hold")

    sched = section_block(q, Q.term_schedule(q, st["student_id"], term["id"]))
    on_schedule = [s for s in sched if s["enrollment_status"] in ("registered", "waitlisted")]
    already = next((s for s in on_schedule if s["_section_id"] == sec["_section_id"]), None)
    same_course = next((s for s in on_schedule if s["_course_id"] == sec["_course_id"] and s["_section_id"] != sec["_section_id"]), None)
    if already:
        blockers.append("already_enrolled" if already["enrollment_status"] == "registered" else "already_waitlisted")
    elif same_course:
        blockers.append("already_enrolled_in_another_section")

    # prerequisites: groups are AND, rows within a group are OR
    rules = Q.prerequisites(q, sec["_course_id"])
    passed: dict[int, str | None] = {}
    if rules:
        for r in Q.completed_courses(q, st["student_id"]):
            passed[r["course_id"]] = best_grade(passed.get(r["course_id"], "F"), r["grade"])
        for r in Q.transfer_credits(q, st["student_id"]):
            if r["course_id"]:
                passed[r["course_id"]] = None
        for r in Q.test_credits(q, st["student_id"]):
            if r["course_id"]:
                passed[r["course_id"]] = None
    registered_courses = {s["_course_id"] for s in on_schedule if s["enrollment_status"] == "registered"}
    groups: dict[int, list[dict]] = defaultdict(list)
    for r in rules:
        groups[r["group_number"]].append(r)
    prereq_facts = {"rules": [], "unmet": [], "unmet_codes": [], "met": True}
    for gnum, alts in sorted(groups.items()):
        desc = []
        satisfied = False
        for a in alts:
            label = f"{a['subject']} {a['course_number']} ({a['min_grade']} or better{', may be taken concurrently' if a['prereq_type'] == 'corequisite' else ''})"
            desc.append(label)
            cid = a["required_course_id"]
            if cid in passed and grade_meets(passed[cid], a["min_grade"]):
                satisfied = True
            elif a["prereq_type"] == "corequisite" and cid in registered_courses:
                satisfied = True
        codes = [f"{a['subject']} {a['course_number']}" for a in alts]
        prereq_facts["rules"].append({"group": gnum, "any_of": desc, "any_of_codes": codes, "satisfied": satisfied})
        if not satisfied:
            prereq_facts["unmet"].append(" or ".join(desc))
            prereq_facts.setdefault("unmet_codes", []).append(codes)
    if prereq_facts["unmet"]:
        prereq_facts["met"] = False
        blockers.append("prerequisite_not_met")

    conflicts = []
    for s in on_schedule:
        if s["enrollment_status"] != "registered":
            continue
        for m1 in sec["_raw_meetings"]:
            for m2 in s["_raw_meetings"]:
                if overlaps(m1, m2):
                    conflicts.append({"crn": s["crn"], "course": s["course"], "meeting": fmt_meeting(m2)})
    if conflicts:
        blockers.append("time_conflict")

    if sec["section_status"] == "cancelled":
        blockers.append("section_cancelled")
    elif sec["seats_left"] is not None and sec["seats_left"] <= 0:
        blockers.append("section_full")

    can_add = not blockers
    can_waitlist = (blockers == ["section_full"] and sec["waitlisted"] < sec["waitlist_capacity"])
    return {
        "student_status": st["status"],
        "registration_window": window,
        "appointment": appt_facts,
        "holds_blocking_registration": [{"type": h["hold_type"], "office": h["placed_by_office"], "reason": h["reason"]} for h in holds],
        "already_on_schedule": ({"crn": already["crn"], "status": already["enrollment_status"]} if already else
                                {"crn": same_course["crn"], "status": same_course["enrollment_status"], "note": "another section of the same course"} if same_course else None),
        "prerequisites": prereq_facts,
        "time_conflicts": conflicts,
        "blockers": blockers,
        "can_add": can_add,
        "can_waitlist": can_waitlist,
        "_schedule": on_schedule,
    }


def explain_blockers(ev: dict, term: dict, sec: dict, as_of: datetime) -> list[str]:
    out = []
    for b in ev["blockers"]:
        if b == "student_not_active":
            out.append(f"your student status is '{ev['student_status']}', so you are not eligible to register until you are readmitted")
        elif b == "registration_not_open":
            a = ev["appointment"]
            out.append(f"registration for {term['name']} does not open until {fmt_date(term['registration_opens'])}"
                       + (f", and your registration appointment begins {fmt_dt(a['begins_at'])}" if a else ""))
        elif b == "add_deadline_passed":
            out.append(f"the add deadline for {term['name']} was {fmt_date(term['add_deadline'])}; adding now requires a late-add petition approved by the department")
        elif b == "appointment_not_started":
            out.append(f"your registration appointment for {term['name']} does not begin until {fmt_dt(ev['appointment']['begins_at'])}")
        elif b == "registration_hold":
            hs = fmt_list([f"{article(h['type'])} hold from {h['office'].replace('_', ' ')} ({h['reason']})" for h in ev["holds_blocking_registration"]])
            out.append(f"you have {hs} that blocks registration; it must be released by that office first")
        elif b in ("already_enrolled", "already_waitlisted"):
            out.append(f"you are already {'registered in' if b == 'already_enrolled' else 'waitlisted for'} CRN {sec['crn']}")
        elif b == "already_enrolled_in_another_section":
            out.append(f"you are already in CRN {ev['already_on_schedule']['crn']}, another section of {sec['course']}; you would need to drop it first")
        elif b == "prerequisite_not_met":
            out.append("you have not met the prerequisite: " + fmt_list([f"need {u}" for u in ev["prerequisites"]["unmet"]]))
        elif b == "time_conflict":
            out.append("it conflicts with " + fmt_list([f"{c['course']} (CRN {c['crn']}, {c['meeting']})" for c in ev["time_conflicts"]]))
        elif b == "section_cancelled":
            out.append("the section has been cancelled")
        elif b == "section_full":
            out.append(f"the section is full ({sec['registered']}/{sec['capacity']})"
                       + (f"; the waitlist has {sec['waitlist_capacity'] - sec['waitlisted']} spot(s) left" if sec["waitlisted"] < sec["waitlist_capacity"] else "; the waitlist is also full"))
    return out


# ----------------------------------------------------------------------------- case builders
class Builder:
    def __init__(self, conn, rng: random.Random):
        self.conn = conn
        self.rng = rng
        self.counter = defaultdict(int)

    def case(self, intent: str, category: str, st: dict, as_of: datetime, q: QueryLog, question: str, paraphrases: list[str],
             slots: dict, facts: dict, answer: str, discrete: dict | None = None, must_not_mention: list[str] | None = None) -> dict:
        facts = strip_private(facts)
        out = {
            "id": None,
            "persona": "student",
            "category": category,
            "intent": intent,
            "as_of": as_of,
            "as_of_is_default": as_of == DEFAULT_AS_OF,
            "student": {"student_id": st["student_id"], "university_id": st["university_id"], "name": person_name(st),
                        "email": st["email"], "status": st["status"]},
            "question": question,
            "paraphrases": paraphrases,
            "slots": slots,
            "answer": with_allowed(discrete if discrete is not None else discrete_answer(intent, facts)),
            "sql": q.entries,
            "expected_facts": facts,
            "reference_answer": answer,
        }
        if must_not_mention:
            out["must_not_mention"] = must_not_mention
        return out

    def start(self, uid: str):
        q = QueryLog(self.conn)
        st = Q.student_by_uid(q, uid)
        return q, st

    # ---- registration: can I add ----
    CAN_ADD_CRN = [
        "Can I add CRN {crn} to my schedule?",
        "Is it possible for me to register for CRN {crn}?",
        "I want to add CRN {crn} {term}. Can I?",
        "Can you add CRN {crn} to my {term_name} schedule?",
        "Am I able to sign up for CRN {crn}?",
        "Would I be allowed to add {course} (CRN {crn}) {term}?",
    ]
    CAN_ADD_COURSE = [
        "Can I add {course} {term}?",
        "Am I eligible to register for {course} section {section_number} {term}?",
        "I'd like to take {course} ({title}) {term}. Can I add it?",
        "Can I still get into {course} {term}?",
        "Is there anything stopping me from adding {course} {term}?",
    ]

    def can_add(self, uid: str, term_code: str, crn: str, as_of: datetime, by_course: bool) -> dict:
        """By CRN: evaluate that section. By course: evaluate every section of the course in the term."""
        q, st = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        row = Q.section_by_crn(q, term["id"], crn)
        if by_course:
            rows = Q.sections_of_course(q, term["id"], row["subject"], row["course_number"])
        else:
            rows = [row]
        secs = section_block(q, rows)
        evals = [evaluate_add(q, st, term, sec, as_of) for sec in secs]
        tp = term_phrase(self.rng, term, current)
        sec0 = secs[0]
        slots = {"crn": crn, "term": tp, "term_name": term["name"], "course": sec0["course"], "section_number": row["section_number"],
                 "title": sec0["title"], "term_code": term_code}
        question, paras = pick(self.rng, self.CAN_ADD_COURSE if by_course else self.CAN_ADD_CRN, 3, **slots)
        if not by_course:
            del slots["section_number"]

        def yes_text(sec, ev):
            a = ev["appointment"]
            why = [f"registration for {term['name']} is open (add deadline {fmt_date(term['add_deadline'])})"]
            if a:
                why.append(f"your registration appointment began {fmt_dt(a['begins_at'])}")
            why.append("you have no holds blocking registration")
            if ev["prerequisites"]["rules"]:
                why.append("you have met the prerequisite(s)")
            if ev["_schedule"]:
                why.append(f"it does not conflict with anything on your {term['name']} schedule")
            return cap_first(fmt_list(why)) + "."

        addable = [(sec, ev) for sec, ev in zip(secs, evals) if ev["can_add"]]
        if addable:
            if by_course and len(secs) > 1:
                answer = (f"Yes. {sec0['course']} ({sec0['title']}) has {len(addable)} section(s) you can add in {term['name']}:\n"
                          + "\n".join("- " + describe_section(sec, with_seats=True) for sec, _ in addable) + "\n" + yes_text(*addable[0]))
                blocked = [(sec, ev) for sec, ev in zip(secs, evals) if not ev["can_add"]]
                if blocked:
                    answer += "\nNot available: " + "; ".join(f"CRN {sec['crn']} ({', '.join(explain_blockers(ev, term, sec, as_of))})" for sec, ev in blocked)
            else:
                sec, ev = addable[0]
                answer = f"Yes. {describe_section(sec, with_seats=True)}. {yes_text(sec, ev)} You can add it now."
        else:
            ev0 = evals[0]
            student_level = [b for b in ev0["blockers"] if b in ("student_not_active", "registration_not_open", "add_deadline_passed", "appointment_not_started", "registration_hold", "prerequisite_not_met")]
            if by_course and len(secs) > 1:
                shared = explain_blockers({**ev0, "blockers": student_level}, term, sec0, as_of)
                answer = f"No, you cannot add {sec0['course']} ({sec0['title']}) in {term['name']} right now"
                if shared:
                    answer += ": " + "; ".join(shared)
                answer += ".\nSections: " + "; ".join(
                    f"CRN {sec['crn']} {sec['section_number']} " + ("(" + ", ".join(explain_blockers({**ev, "blockers": [b for b in ev["blockers"] if b not in student_level]}, term, sec, as_of)) + ")" if [b for b in ev["blockers"] if b not in student_level] else "(otherwise open)")
                    for sec, ev in zip(secs, evals)) + "."
            else:
                reasons = explain_blockers(ev0, term, sec0, as_of)
                answer = f"No, you cannot add {sec0['course']} (CRN {sec0['crn']}, {term['name']}) right now: " + "; ".join(reasons) + "."
                if ev0["can_waitlist"]:
                    answer += f" You can join the waitlist (position {sec0['waitlisted'] + 1})."
            if "add_deadline_passed" in ev0["blockers"] and term["code"] == CURRENT:
                nxt = Q.term_by_offset(q, term["sequence"], 1)
                if as_of.date() < nxt["registration_opens"]:
                    answer += f" Registration for {nxt['name']} opens {fmt_date(nxt['registration_opens'])} if you want it next term."
                else:
                    answer += f" Registration for {nxt['name']} is open now if you want it next term."
        shared_keys = ("student_status", "registration_window", "appointment", "holds_blocking_registration", "prerequisites")
        facts = {"term": {"code": term["code"], "name": term["name"]}, "course": {"code": sec0["course"], "title": sec0["title"]},
                 **{k: evals[0][k] for k in shared_keys},
                 "sections": [{"section": sec, "already_on_schedule": ev["already_on_schedule"], "time_conflicts": ev["time_conflicts"],
                               "blockers": ev["blockers"], "can_add": ev["can_add"], "can_waitlist": ev["can_waitlist"]} for sec, ev in zip(secs, evals)],
                 "can_add_any": bool(addable)}
        if not by_course:
            facts["section"] = sec0
            facts["blockers"] = evals[0]["blockers"]
            facts["can_add"] = evals[0]["can_add"]
            facts["can_waitlist"] = evals[0]["can_waitlist"]
        return self.case("can_add", "registration", st, as_of, q, question, paras, slots, facts, answer)

    # ---- registration: when can I register ----
    WHEN_REGISTER = [
        "When can I register?",
        "When does registration open for me?",
        "When is my registration appointment?",
        "When's my time ticket?",
        "Has my registration window opened yet?",
        "When am I allowed to start signing up for classes?",
        "What day and time can I begin registering?",
    ]
    WHEN_REGISTER_TERM = [
        "When can I register {term}?",
        "When does registration open for me {term}?",
        "When is my registration appointment {term}?",
        "What time can I start registering {term}?",
        "When am I allowed to sign up for classes {term}?",
        "Until when can I still register {term}?",
    ]

    def register_when(self, uid: str, as_of: datetime, term_code: str | None = None) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q)
        if term_code:
            term = Q.term_by_code(q, term_code)
            tp = term_phrase(self.rng, term, current)
            slots = {"term": tp, "term_name": term["name"], "term_code": term_code}
            question, paras = pick(self.rng, self.WHEN_REGISTER_TERM, 3, **slots)
        else:
            term = Q.next_registrable_term(q, as_of.date())
            slots = {"term_code": term["code"], "term_resolution": "no term mentioned; next term whose add deadline has not passed"}
            question, paras = pick(self.rng, self.WHEN_REGISTER, 3)
        appt = Q.appointment(q, st["student_id"], term["id"])
        holds = [h for h in Q.active_holds(q, st["student_id"]) if h["blocks_registration"]]
        as_of_date = as_of.date()
        appt_facts = ({"begins_at": appt["begins_at"], "ends_at": appt["ends_at"], "priority_group": appt["priority_group"],
                       "started": appt["begins_at"] <= as_of} if appt else None)
        opens_dt = datetime(term["registration_opens"].year, term["registration_opens"].month, term["registration_opens"].day, tzinfo=UTC)
        earliest = max(opens_dt, appt["begins_at"]) if appt else opens_dt
        window_open = term["registration_opens"] <= as_of_date <= term["add_deadline"]
        eligible = st["status"] == "active" and not holds
        can_now = eligible and window_open and (appt is None or appt["begins_at"] <= as_of)
        facts = {
            "term": {"code": term["code"], "name": term["name"]},
            "student_status": st["status"],
            "registration_window": {"registration_opens": term["registration_opens"], "add_deadline": term["add_deadline"],
                                    "drop_deadline": term["drop_deadline"], "in_window": window_open},
            "appointment": appt_facts,
            "holds_blocking_registration": [{"type": h["hold_type"], "office": h["placed_by_office"], "reason": h["reason"]} for h in holds],
            "earliest_registration_at": earliest if eligible else None,
            "can_register_now": can_now,
            "window_closed": as_of_date > term["add_deadline"],
        }
        if st["status"] != "active":
            answer = (f"You are not currently eligible to register: your student status is '{st['status']}'. "
                      f"Registration for {term['name']} runs {fmt_date(term['registration_opens'])} to {fmt_date(term['add_deadline'])}; "
                      "you would need to be readmitted first.")
        else:
            if appt:
                when = (f"Your registration appointment for {term['name']} "
                        + (f"began {fmt_dt(appt['begins_at'])}" if appt_facts["started"] else f"begins {fmt_dt(appt['begins_at'])}")
                        + f" (priority group: {appt['priority_group']}). ")
            else:
                when = f"Registration for {term['name']} opens {fmt_date(term['registration_opens'])}; you do not have a time ticket on file yet. "
            when += f"You can add classes through the add deadline, {fmt_date(term['add_deadline'])}."
            if holds:
                when += (" However, you have " + fmt_list([f"{article(h['hold_type'])} hold from {h['placed_by_office'].replace('_', ' ')} ({h['reason']})" for h in holds])
                         + " that blocks registration; have it released before your appointment.")
            elif can_now:
                when += " You can register now."
            elif facts["window_closed"]:
                when += " That deadline has passed."
            answer = when
        return self.case("register_when", "registration", st, as_of, q, question, paras, slots, facts, answer)

    # ---- registration: seats left ----
    SEATS_CRN = [
        "How many seats are left in CRN {crn}?",
        "Is CRN {crn} full?",
        "Are there still open seats in CRN {crn} {term}?",
        "What's the enrollment count for CRN {crn}, and how much room is left?",
        "Does CRN {crn} have a waitlist, and how long is it?",
    ]
    SEATS_COURSE = [
        "How many seats are open in {course} {term}?",
        "Are there any open sections of {course} {term}?",
        "Is {course} full {term}, or can I still get in?",
        "Which sections of {course} still have room {term}?",
        "How full are the {course} sections {term}?",
    ]

    def seats(self, uid: str, term_code: str, crn: str | None, course: tuple[str, str] | None, as_of: datetime) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        tp = term_phrase(self.rng, term, current)
        if crn:
            secs = section_block(q, [Q.section_by_crn(q, term["id"], crn)])
            slots = {"crn": crn, "term": tp, "term_name": term["name"], "course": secs[0]["course"]}
            question, paras = pick(self.rng, self.SEATS_CRN, 3, **slots)
        else:
            secs = section_block(q, Q.sections_of_course(q, term["id"], *course))
            slots = {"course": f"{course[0]} {course[1]}", "term": tp, "term_name": term["name"]}
            question, paras = pick(self.rng, self.SEATS_COURSE, 3, **slots)
        slots["term_code"] = term_code
        lines = [describe_section(s, with_seats=True, with_instructor=False) for s in secs]
        open_secs = [s for s in secs if s["seats_left"] > 0]
        head = (f"{slots['course']} has {len(secs)} section(s) in {term['name']}; {len(open_secs)} with open seats." if not crn
                else (f"CRN {crn} has {secs[0]['seats_left']} of {secs[0]['capacity']} seats open." if open_secs
                      else f"CRN {crn} is full ({secs[0]['registered']}/{secs[0]['capacity']}); {secs[0]['waitlisted']} of {secs[0]['waitlist_capacity']} waitlist spots are taken."))
        answer = head + "\n" + "\n".join("- " + l for l in lines)
        facts = {"term": {"code": term["code"], "name": term["name"]}, "sections": secs,
                 "total_seats_left": sum(s["seats_left"] for s in secs)}
        return self.case("seats_left", "registration", st, as_of, q, question, paras, slots, facts, answer)

    # ---- registration: classes taken ----
    TAKEN_ALL = [
        "What classes have I taken so far?",
        "Can you list every course I've completed?",
        "Which courses have I already taken here?",
        "Show me all the classes I've finished, with grades.",
        "What have I taken up to now, and what am I in right now?",
    ]
    TAKEN_TERM = [
        "What classes did I take in {term}?",
        "Which courses was I enrolled in {term}?",
        "Can you tell me what I took {term}?",
        "What were my courses {term}?",
    ]
    TAKEN_COURSE = [
        "Have I taken {course} yet?",
        "Did I already complete {course}?",
        "Do I have credit for {course}?",
        "Have I already done {course} ({title})?",
    ]

    def classes_taken(self, uid: str, as_of: datetime, mode: str, term_code: str | None = None, course: tuple[str, str] | None = None) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q)
        if mode == "course":
            cat = Q.course_lookup(q, *course)
            attempts = Q.course_attempts(q, st["student_id"], *course)
            equiv = Q.course_equivalents(q, st["student_id"], *course)
            done = [a for a in attempts if a["status"] == "completed" and a["grade"] not in (None, "F", "W", "I")]
            in_progress = [a for a in attempts if a["status"] == "registered"]
            slots = {"course": f"{course[0]} {course[1]}", "title": cat["title"]}
            question, paras = pick(self.rng, self.TAKEN_COURSE, 3, **slots)
            facts = {"course": {"code": slots["course"], "title": cat["title"]},
                     "attempts": [{"term": a["term_name"], "status": a["status"], "grade": a["grade"], "credits": num(a["credits"])} for a in attempts],
                     "credit_from_transfer_or_test": [{"source": e["source"], "detail": e["detail"], "credits": num(e["credits"])} for e in equiv],
                     "has_credit": bool(done or equiv), "in_progress": bool(in_progress)}
            if done:
                answer = f"Yes. You completed {slots['course']} ({cat['title']}) in " + fmt_list([f"{a['term_name']} with a grade of {a['grade']}" for a in done]) + "."
            elif equiv:
                answer = f"Yes. You have credit for {slots['course']} ({cat['title']}) through " + fmt_list([f"{e['source']} credit ({e['detail']}, {fmt_credits(e['credits'])} cr)" for e in equiv]) + "."
            elif in_progress:
                answer = f"Not yet. You are currently registered for {slots['course']} ({cat['title']}) in {in_progress[0]['term_name']}; no grade has been posted."
            else:
                answer = f"No. There is no completed attempt, transfer credit, or test credit for {slots['course']} ({cat['title']}) on your record."
            other = [a for a in attempts if a not in done and a["status"] != "registered"]
            if other:
                answer += " Earlier attempts: " + fmt_list([f"{a['term_name']} ({a['status']}{', grade ' + a['grade'] if a['grade'] else ''})" for a in other]) + "."
            return self.case("taken_course", "registration", st, as_of, q, question, paras, slots, facts, answer)

        lines = Q.transcript_courses(q, st["student_id"])
        if mode == "term":
            term = Q.term_by_code(q, term_code)
            tp = term_phrase(self.rng, term, current)
            lines = [l for l in lines if l["term_code"] == term_code]
            slots = {"term": tp, "term_name": term["name"], "term_code": term_code}
            question, paras = pick(self.rng, self.TAKEN_TERM, 3, **slots)
            courses = [{"course": course_code(l), "title": l["title"], "credits": num(l["credits"]), "status": l["status"], "grade": l["grade"]} for l in lines]
            facts = {"term": {"code": term["code"], "name": term["name"]}, "courses": courses,
                     "credits_attempted": sum(c["credits"] for c in courses)}
            if not courses:
                answer = f"You were not enrolled in any courses in {term['name']}."
            else:
                answer = f"In {term['name']} you were enrolled in {len(courses)} course(s), {fmt_credits(facts['credits_attempted'])} credits:\n" + "\n".join(
                    f"- {c['course']} {c['title']} ({fmt_credits(c['credits'])} cr): " + (f"grade {c['grade']}" if c["grade"] else "in progress" if c["status"] == "registered" else c["status"]) for c in courses)
            return self.case("taken_term", "registration", st, as_of, q, question, paras, slots, facts, answer)

        transfer = Q.transfer_credits(q, st["student_id"])
        tests = Q.test_credits(q, st["student_id"])
        question, paras = pick(self.rng, self.TAKEN_ALL, 3)
        by_term = defaultdict(list)
        for l in lines:
            by_term[l["term_name"]].append(l)
        completed = [l for l in lines if l["status"] == "completed"]
        facts = {
            "completed": [{"term": l["term_name"], "course": course_code(l), "title": l["title"], "credits": num(l["credits"]), "grade": l["grade"]} for l in completed],
            "withdrawn": [{"term": l["term_name"], "course": course_code(l)} for l in lines if l["status"] == "withdrawn"],
            "in_progress": [{"term": l["term_name"], "course": course_code(l), "title": l["title"], "credits": num(l["credits"])} for l in lines if l["status"] == "registered"],
            "transfer_credit": [{"institution": t["institution"], "external_course": t["external_course_code"], "equivalent": course_code(t) if t["course_id"] else None, "credits": num(t["awarded_credits"])} for t in transfer],
            "test_credit": [{"test": f"{t['test_type']} {t['test_subject']}", "equivalent": course_code(t) if t["course_id"] else None, "credits": num(t["credits_awarded"])} for t in tests],
            "completed_count": len(completed),
            "completed_credits": sum(num(l["credits"]) for l in completed if l["earns_credit"]),
        }
        out = [f"You have completed {len(completed)} courses ({fmt_credits(facts['completed_credits'])} earned credits) at NMSU:"]
        for tname, ls in by_term.items():
            done = [l for l in ls if l["status"] != "registered"]
            if done:
                out.append(f"{tname}: " + "; ".join(f"{course_code(l)} {l['title']} ({l['grade'] or l['status']})" for l in done))
        if facts["in_progress"]:
            out.append("In progress now: " + "; ".join(f"{c['course']} {c['title']}" for c in facts["in_progress"]))
        if transfer:
            out.append("Transfer credit: " + "; ".join(f"{t['external_course_code']} from {t['institution']} = {course_code(t) if t['course_id'] else 'elective credit'} ({fmt_credits(t['awarded_credits'])} cr)" for t in transfer))
        if tests:
            out.append("Test credit: " + "; ".join(f"{t['test_type']} {t['test_subject']} = {course_code(t) if t['course_id'] else 'elective credit'} ({fmt_credits(t['credits_awarded'])} cr)" for t in tests))
        return self.case("taken_all", "registration", st, as_of, q, question, paras, {}, facts, "\n".join(out))

    # ---- schedule ----
    SCHED_CURRENT = [
        "What's my schedule {term}?",
        "What classes am I in right now?",
        "Can you show me my current class schedule?",
        "What am I registered for {term}?",
        "Which courses am I taking {term}, and when do they meet?",
        "Pull up my schedule for {term}.",
    ]
    SCHED_PREVIOUS = [
        "What was my schedule {term}?",
        "Can you show me the classes I had {term}?",
        "What did my {term_name} schedule look like?",
        "Which sections was I in {term}?",
        "Remind me what I was enrolled in {term}.",
    ]
    SCHED_WEEK = [
        "What does my week look like?",
        "Can you give me my weekly schedule?",
        "What's my class schedule day by day this week?",
        "When are my classes each day?",
        "Lay out my weekly timetable {term}.",
    ]
    SCHED_DAY = [
        "What do I have on {day}s?",
        "What classes do I have on {day}?",
        "Do I have anything on {day}?",
        "What's my {day} schedule?",
        "When is my first class on {day}?",
    ]

    def schedule(self, uid: str, term_code: str, as_of: datetime, mode: str, day: str | None = None) -> dict:
        q, st = self.start(uid)
        current = Q.current_term(q)
        term = Q.term_by_code(q, term_code)
        tp = term_phrase(self.rng, term, current)
        rows = Q.term_schedule(q, st["student_id"], term["id"])
        secs = section_block(q, rows, with_seats=False)
        keep = ("registered", "waitlisted") if term["sequence"] >= current["sequence"] else ("completed", "withdrawn", "registered")
        on = [s for s in secs if s["enrollment_status"] in keep]
        dropped = [s for s in secs if s["enrollment_status"] == "dropped"]
        reg = [s for s in on if s["enrollment_status"] != "waitlisted"]
        credits = sum(s["credits"] for s in reg)
        base_facts = {"term": {"code": term["code"], "name": term["name"], "is_current": term["is_current"]},
                      "sections": on, "dropped": [{"crn": s["crn"], "course": s["course"]} for s in dropped],
                      "credits": credits, "section_count": len(reg), "waitlisted_count": len(on) - len(reg)}
        if mode in ("current", "previous"):
            slots = {"term": tp, "term_name": term["name"], "term_code": term_code}
            question, paras = pick(self.rng, self.SCHED_CURRENT if mode == "current" else self.SCHED_PREVIOUS, 3, **slots)
            if not on:
                answer = f"You have no enrollments on record for {term['name']}."
                if st["status"] != "active":
                    answer += f" Your student status is '{st['status']}'."
            else:
                verb = "are registered for" if mode == "current" else "were enrolled in"
                wl = len(on) - len(reg)
                answer = f"You {verb} {len(reg)} course(s), {fmt_credits(credits)} credits, in {term['name']}" + (f" (plus {wl} waitlisted)" if wl else "") + ":\n" + "\n".join(
                    "- " + describe_section(s) + (f" [{s['enrollment_status']}]" if s["enrollment_status"] in ("waitlisted", "withdrawn") else "") for s in on)
                if dropped:
                    answer += "\nDropped: " + fmt_list([f"{s['course']} (CRN {s['crn']})" for s in dropped]) + "."
            return self.case("schedule_current" if mode == "current" else "schedule_previous", "schedule", st, as_of, q, question, paras, slots, base_facts, answer)

        # weekly / single day
        grid: dict[str, list[dict]] = {d: [] for d in WEEK}
        online = []
        for s in reg:
            if not s["_raw_meetings"]:
                online.append(s)
            for m in s["_raw_meetings"]:
                for d in m["days"]:
                    grid[d].append({"start": m["start_time"], "end": m["end_time"], "course": s["course"], "crn": s["crn"], "title": s["title"],
                                    "type": m["meeting_type"], "room": f"{m['building']} {m['room_number']}" if m["building"] else None})
        for d in grid:
            grid[d].sort(key=lambda x: x["start"])

        def day_line(d: str) -> str:
            if not grid[d]:
                return f"{DAY_NAMES[d]}: no classes"
            return f"{DAY_NAMES[d]}: " + "; ".join(f"{fmt_time(x['start'])}-{fmt_time(x['end'])} {x['course']}" + (f" {x['type']}" if x["type"] != "lecture" else "") + (f" in {x['room']}" if x["room"] else "") for x in grid[d])

        if mode == "week":
            slots = {"term": tp, "term_name": term["name"], "term_code": term_code}
            question, paras = pick(self.rng, self.SCHED_WEEK, 3, **slots)
            days = [d for d in WEEK if grid[d]] or ["M"]
            answer = f"Your weekly schedule for {term['name']}:\n" + "\n".join(day_line(d) for d in WEEK if d in "MTWRF" or grid[d])
            if online:
                answer += "\nOnline, no set meeting time: " + fmt_list([f"{s['course']} (CRN {s['crn']})" for s in online])
            facts = {**base_facts, "by_day": {DAY_NAMES[d]: grid[d] for d in WEEK if grid[d]}, "online_no_meeting": [{"crn": s["crn"], "course": s["course"]} for s in online]}
            return self.case("schedule_week", "schedule", st, as_of, q, question, paras, slots, facts, answer)

        slots = {"day": DAY_NAMES[day], "term": tp, "term_name": term["name"], "term_code": term_code}
        question, paras = pick(self.rng, self.SCHED_DAY, 3, **slots)
        if grid[day]:
            first = grid[day][0]
            answer = f"On {DAY_NAMES[day]}s in {term['name']} you have {len(grid[day])} class meeting(s). " + day_line(day).split(": ", 1)[1] + f". Your first class is {first['course']} at {fmt_time(first['start'])}."
        else:
            answer = f"You have no scheduled class meetings on {DAY_NAMES[day]}s in {term['name']}."
        if online:
            answer += " Your online course(s) " + fmt_list([s["course"] for s in online]) + " have no set meeting time."
        facts = {**base_facts, "day": DAY_NAMES[day], "meetings": grid[day], "first_class": grid[day][0] if grid[day] else None,
                 "online_no_meeting": [{"crn": s["crn"], "course": s["course"]} for s in online]}
        return self.case("schedule_day", "schedule", st, as_of, q, question, paras, slots, facts, answer)

    # ---- transcript ----
    TRANSCRIPT = [
        "Can I get a copy of my transcript?",
        "Show me my unofficial transcript.",
        "I need my transcript. Can you pull it up?",
        "What's on my transcript right now?",
        "Can you give me my full academic record, term by term?",
        "Please generate my current transcript.",
    ]
    GPA = [
        "What's my GPA?",
        "What is my cumulative GPA and how many credits have I earned?",
        "How many credits do I have, and what's my GPA?",
        "What was my GPA last term, and what is it overall?",
        "What's my academic standing and GPA?",
    ]

    def transcript(self, uid: str, as_of: datetime, mode: str) -> dict:
        q, st = self.start(uid)
        progs = Q.programs(q, st["student_id"])
        recs = Q.term_records(q, st["student_id"])
        last = recs[-1] if recs else None
        if mode == "gpa":
            question, paras = pick(self.rng, self.GPA, 3)
            facts = {"cumulative_gpa": num(last["cumulative_gpa"]) if last else None,
                     "cumulative_earned_credits": num(last["cumulative_earned"]) if last else 0,
                     "cumulative_attempted_credits": num(last["cumulative_attempted"]) if last else 0,
                     "last_term": {"name": last["term_name"], "term_gpa": num(last["term_gpa"]), "earned": num(last["earned_credits"])} if last else None,
                     "standing": last["standing"] if last else None, "classification": last["classification"] if last else None}
            if not last:
                answer = "No GPA has been computed yet: no term with posted grades is on your record."
            else:
                answer = (f"Your cumulative GPA is {gpa(last['cumulative_gpa'])} with {fmt_credits(last['cumulative_earned'])} earned credits "
                          f"({fmt_credits(last['cumulative_attempted'])} attempted). Your most recent graded term, {last['term_name']}, had a term GPA of "
                          f"{gpa(last['term_gpa'])} ({fmt_credits(last['earned_credits'])} credits earned). Standing: {last['standing'].replace('_', ' ')}; classification: {last['classification']}.")
            return self.case("gpa", "transcript", st, as_of, q, question, paras, {}, facts, answer)

        lines = Q.transcript_courses(q, st["student_id"])
        transfer = Q.transfer_credits(q, st["student_id"])
        tests = Q.test_credits(q, st["student_id"])
        degs = Q.degrees(q, st["student_id"])
        actions = Q.academic_actions(q, st["student_id"])
        holds = [h for h in Q.active_holds(q, st["student_id"]) if h["blocks_transcript"]]
        question, paras = pick(self.rng, self.TRANSCRIPT, 3)
        rec_by_term = {r["term_code"]: r for r in recs}
        terms: list[dict] = []
        by_term: dict[str, list[dict]] = defaultdict(list)
        for l in lines:
            by_term[l["term_code"]].append(l)
        for code, ls in by_term.items():
            r = rec_by_term.get(code)
            terms.append({"term": ls[0]["term_name"], "code": code,
                          "courses": [{"course": course_code(l), "title": l["title"], "credits": num(l["credits"]),
                                       "grade": l["grade"] or ("IP" if l["status"] == "registered" else None), "repeat": l["is_repeat"]} for l in ls],
                          "term_gpa": num(r["term_gpa"]) if r else None, "earned": num(r["earned_credits"]) if r else None,
                          "cumulative_gpa": num(r["cumulative_gpa"]) if r else None, "cumulative_earned": num(r["cumulative_earned"]) if r else None,
                          "standing": r["standing"] if r else None, "in_progress": r is None})
        facts = {
            "student": {"name": f"{st['legal_first_name']} {st['legal_last_name']}", "university_id": st["university_id"], "status": st["status"]},
            "programs": [{"code": p["code"], "name": p["name"], "degree": p["degree_type"], "type": p["program_type"], "primary": p["is_primary"], "status": p["status"]} for p in progs],
            "terms": terms,
            "transfer_credit": [{"institution": t["institution"], "external_course": t["external_course_code"], "equivalent": course_code(t) if t["course_id"] else None, "credits": num(t["awarded_credits"])} for t in transfer],
            "test_credit": [{"test": f"{t['test_type']} {t['test_subject']}", "score": t["score"], "equivalent": course_code(t) if t["course_id"] else None, "credits": num(t["credits_awarded"])} for t in tests],
            "degrees": [{"program": d["name"], "degree": d["degree_type"], "conferred": d["conferred_date"], "honors": d["honors"], "final_gpa": num(d["final_gpa"])} for d in degs],
            "academic_actions": [{"type": a["action_type"], "term": a["term_name"], "date": a["action_date"]} for a in actions],
            "cumulative_gpa": num(last["cumulative_gpa"]) if last else None,
            "cumulative_earned_credits": num(last["cumulative_earned"]) if last else 0,
            "holds_blocking_official_transcript": [{"type": h["hold_type"], "office": h["placed_by_office"], "reason": h["reason"]} for h in holds],
        }
        out = [f"Unofficial transcript for {facts['student']['name']} (ID {st['university_id']}), status {st['status']}."]
        if progs:
            out.append("Program(s): " + fmt_list([f"{p['name']} ({p['degree_type'] or p['program_type']}{', completed' if p['status'] == 'completed' else ''})" for p in progs]) + ".")
        for t in terms:
            out.append(f"{t['term']}: " + "; ".join(f"{c['course']} {c['title']} {fmt_credits(c['credits'])} cr {c['grade'] or ''}".strip() for c in t["courses"])
                       + (f" | term GPA {gpa(t['term_gpa'])}, cumulative GPA {gpa(t['cumulative_gpa'])}, {fmt_credits(t['cumulative_earned'])} credits earned" if not t["in_progress"] else " | in progress"))
        if transfer:
            out.append("Transfer credit: " + "; ".join(f"{t['external_course_code']} ({t['institution']}) = {course_code(t) if t['course_id'] else 'elective'} {fmt_credits(t['awarded_credits'])} cr" for t in transfer))
        if tests:
            out.append("Test credit: " + "; ".join(f"{t['test_type']} {t['test_subject']} = {course_code(t) if t['course_id'] else 'elective'} {fmt_credits(t['credits_awarded'])} cr" for t in tests))
        if actions:
            out.append("Academic actions: " + "; ".join(f"{action_label(a['action_type'])} ({a['term_name']})" for a in actions))
        if degs:
            out.append("Degree(s) awarded: " + "; ".join(f"{d['degree_type']} {d['name']}, conferred {fmt_date(d['conferred_date'])}" + (f", {d['honors'].replace('_', ' ')}" if d["honors"] != "none" else "") for d in degs))
        out.append(f"Cumulative GPA {gpa(last['cumulative_gpa'])}, {fmt_credits(last['cumulative_earned'])} credits earned." if last else "No graded terms yet.")
        if holds:
            out.append("Note: an official transcript cannot be issued while you have " + fmt_list([f"{article(h['hold_type'])} hold ({h['reason']})" for h in holds]) + ". This unofficial copy is for your own use.")
        else:
            out.append("An official transcript can be ordered for electronic delivery, mail, or pickup.")
        return self.case("transcript", "transcript", st, as_of, q, question, paras, {}, facts, "\n".join(out))


# ----------------------------------------------------------------------------- discrete ground truth
def _mt(m: dict) -> dict:
    return {"start": m["start"], "end": m["end"], "course": m["course"], "room": m.get("room")}


def discrete_answer(intent: str, f: dict) -> dict:
    """The short, checkable answer a grader compares against. Derived from the full expected facts."""
    if intent == "can_add":
        secs = f["sections"]
        if len(secs) == 1:
            return {"can_add": secs[0]["can_add"], "blockers": secs[0]["blockers"], "can_waitlist": secs[0]["can_waitlist"]}
        return {"can_add": f["can_add_any"], "sections": {s["section"]["crn"]: {"can_add": s["can_add"], "blockers": s["blockers"]} for s in secs}}
    if intent == "register_when":
        return {"term": f["term"]["name"], "can_register_now": f["can_register_now"],
                "registration_begins_at": f["earliest_registration_at"], "add_deadline": f["registration_window"]["add_deadline"],
                "blocked_by": ([f["student_status"]] if f["student_status"] != "active" else []) + [h["type"] + "_hold" for h in f["holds_blocking_registration"]]}
    if intent == "seats_left":
        return {"sections": {s["crn"]: {"seats_left": s["seats_left"], "waitlisted": s["waitlisted"], "waitlist_capacity": s["waitlist_capacity"]} for s in f["sections"]}}
    if intent == "taken_all":
        return {"completed": [{"course": c["course"], "term": c["term"], "grade": c["grade"]} for c in f["completed"]],
                "withdrawn": [{"course": c["course"], "term": c["term"]} for c in f["withdrawn"]],
                "in_progress": [c["course"] for c in f["in_progress"]],
                "transfer_or_test_credit": [t["equivalent"] or "elective" for t in f["transfer_credit"] + f["test_credit"]]}
    if intent == "taken_term":
        return {"term": f["term"]["name"], "courses": [{"course": c["course"], "grade": c["grade"] or c["status"]} for c in f["courses"]]}
    if intent == "taken_course":
        return {"has_credit": f["has_credit"], "in_progress": f["in_progress"],
                "attempts": [{"term": a["term"], "grade": a["grade"] or a["status"]} for a in f["attempts"]],
                "transfer_or_test_credit": bool(f["credit_from_transfer_or_test"])}
    if intent in ("schedule_current", "schedule_previous"):
        return {"term": f["term"]["name"],
                "enrolled": [{"crn": s["crn"], "course": s["course"], "status": s["enrollment_status"]} for s in f["sections"]],
                "credits": f["credits"]}
    if intent == "schedule_week":
        return {"term": f["term"]["name"], "by_day": {d: [_mt(m) for m in ms] for d, ms in f["by_day"].items()},
                "online_no_meeting": [s["course"] for s in f["online_no_meeting"]]}
    if intent == "schedule_day":
        return {"term": f["term"]["name"], "day": f["day"], "meetings": [_mt(m) for m in f["meetings"]],
                "first_class": _mt(f["first_class"]) if f["first_class"] else None}
    if intent == "transcript":
        return {"terms": [{"term": t["term"], "courses": [{"course": c["course"], "grade": c["grade"]} for c in t["courses"]],
                           "term_gpa": t["term_gpa"], "cumulative_gpa": t["cumulative_gpa"]} for t in f["terms"]],
                "transfer_or_test_credit": [t["equivalent"] or "elective" for t in f["transfer_credit"] + f["test_credit"]],
                "degrees": [{"degree": d["degree"], "program": d["program"]} for d in f["degrees"]],
                "cumulative_gpa": f["cumulative_gpa"], "earned_credits": f["cumulative_earned_credits"],
                "official_transcript_blocked_by_hold": bool(f["holds_blocking_official_transcript"])}
    if intent == "gpa":
        return {"cumulative_gpa": f["cumulative_gpa"], "earned_credits": f["cumulative_earned_credits"],
                "last_term_gpa": f["last_term"]["term_gpa"] if f["last_term"] else None,
                "standing": f["standing"], "classification": f["classification"]}
    raise ValueError(intent)
