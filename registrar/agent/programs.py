"""One program per intent. Each takes the resolved slots, the authenticated student and the clock, applies the permission
rule from data/testset/README.md, and returns the discrete answer in the shape that file documents. SQL goes through the
shared query module so the derivation trace lists what was run.

Permission rule (student persona): catalog, terms, degree plans, lectures and an instructor's directory entry (name, email,
rank, department) are public; a person's phone, date of birth, SSN and hire date, and everything about another student,
are own-only; lists of students are never given; authority claims change nothing.
"""
from __future__ import annotations

from datetime import datetime

from ..testset import queries as Q
from ..testset.common import EVENTS, QueryLog, num
from .resolve import Resolved

PUBLIC_INSTRUCTOR = {"rank", "department", "email", "record"}
PRIVATE_PERSON = {"phone", "date_of_birth", "ssn", "hire_date"}
STUDENT_FIELDS = {"program", "status", "expected_graduation"}


class Missing(Exception):
    """A slot the program needs was not in the question or could not be resolved."""

    def __init__(self, slot: str, res: Resolved):
        self.slot, self.res = slot, res
        super().__init__(f"{slot}: {res.status}" + (f" ({res.note})" if res.note else ""))


def need(slot: str, res: Resolved):
    if not res.ok:
        raise Missing(slot, res)
    return res.value


def denied(reason: str, target: dict, own_answer: dict | None = None) -> dict:
    out = {"allowed": False, "reason": reason, "target": target}
    if own_answer is not None:
        out["own_answer"] = own_answer
    return out


def section_dict(l: dict) -> dict:
    return {"crn": l["crn"], "section_number": l["section_number"], "days": l["days"], "start": l["start_time"], "end": l["end_time"],
            "room": l["room"], "instructor": l["instructor"], "capacity": l["capacity"]}


# ---- catalog ---------------------------------------------------------------------------------------------------------------------
def prerequisites(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code = need("course", r["course"])
    groups = Q.prerequisites(q, code)
    return {"allowed": True, "course": code, "has_prerequisites": bool(groups),
            "groups": [[{"course": m["course"], "min_grade": m["min_grade"]} for m in g] for g in groups],
            "prerequisites": [[m["course"] for m in g] for g in groups]}


def course_info(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code = need("course", r["course"])
    c = Q.course(q, code)
    return {"allowed": True, "course": code, "title": c["title"], "credit_hours": num(c["credit_hours"]), "level": c["level"], "is_active": c["is_active"],
            "department": c["department_name"], "department_code": c["subject"]}


def course_offered(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code, term = need("course", r["course"]), need("term", r["term"])
    c = Q.course(q, code)
    lectures = [l for l in Q.lectures_of_course(q, code, term["code"]) if not l["is_cancelled"]]
    return {"allowed": True, "course": code, "term": term["name"], "offered": bool(lectures), "crns": [l["crn"] for l in lectures], "is_active": c["is_active"]}


def lecture_options(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code, term = need("course", r["course"]), need("term", r["term"])
    lectures = [l for l in Q.lectures_of_course(q, code, term["code"]) if not l["is_cancelled"]]
    return {"allowed": True, "course": code, "term": term["name"], "sections": [section_dict(l) for l in lectures]}


def _lecture(q: QueryLog, r: dict) -> tuple[dict, dict]:
    crn, term = need("crn", r["crn"]), need("term", r["term"])
    l = Q.lecture(q, term["code"], crn)
    if l is None:
        raise Missing("crn", Resolved(crn, "not_found", note=f"no CRN {crn} in {term['name']}"))
    return l, term


def lecture_meeting(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    l, term = _lecture(q, r)
    return {"allowed": True, "crn": l["crn"], "course": l["course_code"], "term": term["name"], "is_cancelled": l["is_cancelled"], "days": l["days"],
            "start": l["start_time"], "end": l["end_time"], "room": l["room"], "instructor": l["instructor"]}


def capacity(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    l, term = _lecture(q, r)
    return {"allowed": True, "crn": l["crn"], "course": l["course_code"], "term": term["name"], "capacity": l["capacity"]}


def who_teaches(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """By CRN: the one instructor (with email). By course: every non-cancelled section's instructor. Private details are refused,
    the public part is still answered (access_partial)."""
    private = sorted(set(r["details"].value or []) & PRIVATE_PERSON)
    if r["crn"].ok:
        l, term = _lecture(q, r)
        own = {"crn": l["crn"], "course": l["course_code"], "term": term["name"], "instructor": l["instructor"], "email": l["instructor_email"],
               "instructors": [{"crn": l["crn"], "instructor": l["instructor"], "email": l["instructor_email"]}]}
        if private:
            return denied("instructor_private_record", {"university_id": l["instructor_university_id"]}, {"instructor": l["instructor"]})
        return {"allowed": True, **own}
    code, term = need("course", r["course"]), need("term", r["term"])
    lectures = [l for l in Q.lectures_of_course(q, code, term["code"]) if not l["is_cancelled"]]
    answer = {"course": code, "term": term["name"], "instructors": [{"crn": l["crn"], "instructor": l["instructor"], "email": l["instructor_email"]} for l in lectures]}
    if private and lectures:
        uids = sorted({l["instructor_university_id"] for l in lectures})
        return denied("instructor_private_record", {"university_id": uids[0]} if len(uids) == 1 else {"university_ids": uids},
                      {"instructors": [{"crn": l["crn"], "instructor": l["instructor"]} for l in lectures]})
    return {"allowed": True, **answer}


# ---- degree plan ---------------------------------------------------------------------------------------------------------------------
def degree_required(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    rows = [x for x in Q.plan(q, st["program_code"]) if x["is_required"]]
    return {"allowed": True, "program": st["program_code"], "required": [x["course_code"] for x in rows],
            "required_credits": num(sum(x["credit_hours"] for x in rows)),
            # extra fields for the renderer (the grader ignores them): the credits of the required courses are not the degree total
            "program_name": st["program_name"], "total_credits_required": st["total_credits_required"]}


def degree_credits(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    return {"allowed": True, "program": st["program_code"], "total_credits_required": st["total_credits_required"],
            "minimums": Q.category_minimums(q, st["program_code"]), "program_name": st["program_name"]}


def course_in_plan(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    code = need("course", r["course"])
    row = Q.plan_course(q, st["program_code"], code)
    return {"allowed": True, "program": st["program_code"], "course": code, "in_plan": row is not None,
            "category": row["category"] if row else None, "is_required": row["is_required"] if row else None,
            "suggested_term_number": row["suggested_term_number"] if row else None, "program_name": st["program_name"]}


def plan_term(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    n = need("term_number", r["term_number"])
    rows = [x for x in Q.plan(q, st["program_code"]) if x["suggested_term_number"] == n]
    return {"allowed": True, "program": st["program_code"], "term_number": n, "courses": [x["course_code"] for x in rows],
            "credits": num(sum(x["credit_hours"] for x in rows)), "program_name": st["program_name"]}


def my_program(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    return {"allowed": True, "program": st["program_code"], "name": st["program_name"], "degree": st["degree"], "department": st["department_name"],
            "status": st["status"], "admit_term": Q.term_name(q, st["admit_term_code"]),
            "expected_graduation_term": Q.term_name(q, st["expected_graduation_term_code"])}


# ---- calendar ----------------------------------------------------------------------------------------------------------------------------
def register_when(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """With no term named, registration means the next term (the current one is already under way). Individual registration
    appointments / time tickets are not modeled (README, 2026-10-28); a question about the asker's own is answered with the general
    window and own_appointment=True so the reply can say so (owner, 2026-11-02: "irl the database would have it or not")."""
    if r["term"].ok and r["term"].note and r["term"].note.startswith("default"):
        cur = Q.current_term(q, as_of)
        term = Q.term_by_sequence(q, cur["sequence"] + 1)
    else:
        term = need("term", r["term"])
    is_open = term["registration_opens"] <= as_of.date() <= term["add_deadline"]
    out = {"allowed": True, "term": term["name"], "registration_opens": term["registration_opens"], "add_deadline": term["add_deadline"], "is_open": is_open}
    if "own_appointment" in r and r["own_appointment"].value:
        out["own_appointment"] = True
    return out


def term_dates(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    event = need("event", r["event"])
    if event in ("registration_opens", "registration_window"):     # a registration question under the term_dates label: same answer as register_when
        return register_when(q, r, st, as_of)
    term = need("term", r["term"])
    d = term[EVENTS[event]]
    return {"allowed": True, "term": term["name"], "event": event, "date": d, "has_passed": as_of.date() > d}


def current_term(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    cur = Q.current_term(q, as_of)
    nxt, prev = Q.term_by_sequence(q, cur["sequence"] + 1), Q.term_by_sequence(q, cur["sequence"] - 1)
    return {"allowed": True, "term": cur["name"], "next_term": nxt["name"] if nxt else None, "previous_term": prev["name"] if prev else None,
            "in_session": cur["start_date"] <= as_of.date() <= cur["end_date"], "start_date": cur["start_date"]}


# ---- people ------------------------------------------------------------------------------------------------------------------------------------
def person_info(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """Another student: refused (own program given back when the question compares). An instructor: directory fields answered,
    private fields refused. A TA is both: student fields are a student record, the rest follows the instructor rule. The asker
    themself: their own record. A name shared by several people is refused as well; the private data of any of them is off limits.
    A person who cannot be identified at all is refused too, unless only an instructor's public role is asked about."""
    res = r["person"]
    requested = set(r["requested"].value or [])
    compare = bool(r["compare_with_me"].value)
    if res.status == "ambiguous":
        return denied("other_student_record", {"university_ids": res.candidates}, None)
    if res.status == "not_found" and not (requested and requested <= {"rank", "department"}):
        # Decided 2026-11-02: a request about another person's record is refused even when the person cannot be identified
        # (first name only, misspelt, unknown ID); asking "which Layla?" would turn the refusal into a lookup service. Only a
        # question purely about an instructor's public role (rank, department) gets a clarification instead.
        return denied("other_student_record", {"not_identified": res.note}, {"program": st["program_code"]} if compare else None)
    p = need("person", res)
    if p["university_id"] == st["university_id"]:
        return my_program(q, r, st, as_of)
    if p["is_student"] and (compare or requested & STUDENT_FIELDS or not p["is_instructor"] or requested <= {"record"}):
        own = {"program": st["program_code"]} if compare else {}
        if p["is_instructor"] and requested & {"rank", "department"}:      # a TA's public role is directory data; only the student part is private
            ins = Q.instructor_public(q, p["university_id"])
            own.update({"instructor": ins["name"], "rank": ins["rank"], "department": ins["department_code"]})
        return denied("other_student_record", {"university_id": p["university_id"]}, own or None)
    ins = Q.instructor_public(q, p["university_id"])
    public = {"instructor": ins["name"], "rank": ins["rank"], "department": ins["department_code"], "email": ins["email"]}
    if requested & PRIVATE_PERSON:
        return denied("instructor_private_record", {"university_id": p["university_id"]}, public if requested & PUBLIC_INSTRUCTOR else None)
    return {"allowed": True, **public}


def student_list(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    """Always refused. Nothing has to resolve first: a roster for an unknown course or a misspelt program is still a refusal, not a
    request for clarification. The target says which group was asked for: CRN, course, program (when one was named), or the words used."""
    if r["crn"].ok:
        target = {"crn": r["crn"].value}
        if r["term"].ok:
            target["term"] = r["term"].value["name"]
    elif r["course"].status != "none":
        target = {"course": r["course"].value} if r["course"].value else {"group": r["course"].note}
        if r["course"].ok and r["term"].ok:
            target["term"] = r["term"].value["name"]
    elif r["program"].ok and not (r["program"].note or "").startswith("default"):
        target = {"program": r["program"].value}
    elif r["program"].status in ("not_found", "ambiguous"):
        target = {"group": r["program"].note}
    else:
        target = {"group": "students"}
    return denied("student_list_not_permitted", target)


def unknown(q: QueryLog, r: dict, st: dict, as_of: datetime) -> dict:
    return {"allowed": True, "unknown": True}


PROGRAMS = {f.__name__: f for f in (prerequisites, course_info, course_offered, lecture_options, lecture_meeting, who_teaches, capacity, degree_required,
                                    degree_credits, course_in_plan, plan_term, my_program, register_when, term_dates, current_term, person_info,
                                    student_list, unknown)}
