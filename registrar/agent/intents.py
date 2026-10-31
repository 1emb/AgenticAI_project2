"""The closed set of question types per persona, and the slot schema each one asks the extractor to fill.

Slot values are *mentions*: phrases copied from the question (`course_mention`, `term_mention`, ...). The extractor never
produces database keys; `resolve.py` turns mentions into `course_code`, `term_code`, ... using the database and the clock.
Three slots are closed vocabularies rather than phrases (`event`, `requested`, `details`), because the words people use for
them vary far more than the handful of values they can take; their values are readable phrases that `resolve.py` maps to codes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

UNKNOWN = "unknown"

# ---- closed vocabularies: readable value -> code used by the programs and the test set ----------------------------
EVENT_VALUES = {"first day of classes": "classes_begin", "last day of classes": "classes_end", "last day to add a class": "add_deadline",
                "last day to drop without a W": "drop_deadline", "withdrawal deadline": "withdraw_deadline", "grades due": "grades_due",
                "registration opens": "registration_opens"}
REQUESTED_VALUES = {"program or major": "program", "enrollment status": "status", "email address": "email", "phone number": "phone",
                    "date of birth": "date_of_birth", "social security number": "ssn", "expected graduation": "expected_graduation",
                    "rank or title": "rank", "department": "department", "hire date": "hire_date", "whole record": "record"}
DETAIL_VALUES = {"email address": "email", "phone number": "phone", "date of birth": "date_of_birth", "social security number": "ssn", "hire date": "hire_date"}

# ---- slot definitions (JSON schema fragments) ---------------------------------------------------------------------
_STR = {"type": ["string", "null"]}
SLOTS: dict[str, dict] = {
    "course_mention": {**_STR, "description": "The course exactly as written in the question: a code such as 'CS 2230' or a title such as "
                                              "'Capstone Design I'. Copy it verbatim. null when no course is named."},
    "crn_mention": {**_STR, "description": "The CRN (5-digit course reference number) as written, e.g. '10011'. null when none; a 9-digit number is a person's ID, not a CRN."},
    "term_mention": {**_STR, "description": "The words that name the term, copied verbatim: 'this fall', 'next semester', 'in Fall 2026', 'last term', "
                                            "'Spring 2027'. null when the question names no term."},
    "term_number_mention": {**_STR, "description": "The semester position in the degree plan as written: '1', 'third', 'first', '8th'. null when none."},
    "event": {"type": ["string", "null"], "enum": list(EVENT_VALUES) + [None],
              "description": "Which calendar date is asked for. 'first day of classes' = when the term starts or begins; 'last day of classes' = when the "
                             "term ends or is over; 'last day to add a class'; 'last day to drop without a W'; 'withdrawal deadline' = last day to withdraw "
                             "with a W; 'grades due' = when grades are in; 'registration opens'. null when no date is asked for."},
    "person_mention": {**_STR, "description": "The other person exactly as written: a full name ('Raj Martinez'), a 9-digit university ID ('800260544') "
                                              "or a title plus last name ('Professor Lee'). null when the question is only about the asker."},
    "requested": {"type": "array", "items": {"type": "string", "enum": list(REQUESTED_VALUES)},
                  "description": "Each thing asked about the person, one entry per thing: 'program or major' (also degree, 'computer science major'); "
                                 "'enrollment status' (active, withdrawn, graduated yet); 'email address'; 'phone number' (also cell); 'date of birth' "
                                 "(also birthday, age); 'social security number' (also SSN, last four); 'expected graduation' (when they graduate); "
                                 "'rank or title' (professor, lecturer); 'department'; 'hire date' (when hired); 'whole record' only when the question asks "
                                 "for the record itself or does not name any specific thing."},
    "compare_with_me": {"type": "boolean", "description": "true when the question compares the person with the asker: 'same program as me', "
                                                          "'in my major', 'same degree plan as mine'."},
    "program_mention": {**_STR, "description": "The program or major as written: 'Bachelor of Science in Computer Science', 'computer science', "
                                               "'my program'. null when none is named."},
    "details": {"type": "array", "items": {"type": "string", "enum": list(DETAIL_VALUES)},
                "description": "Details of the instructor that the question asks for beyond their name: 'email address' (also 'how to contact', "
                               "'how to reach'), 'phone number' (only when the question says phone, cell or number), 'date of birth', "
                               "'social security number', 'hire date'. Empty when only the name is wanted."},
}


@dataclass(frozen=True)
class Intent:
    name: str
    description: str
    slots: tuple[str, ...] = ()
    examples: tuple[str, ...] = field(default_factory=tuple)

    def schema(self) -> dict:
        props = {s: SLOTS[s] for s in self.slots}
        return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STUDENT_INTENTS: tuple[Intent, ...] = (
    Intent("prerequisites", "What a student must have taken before a course (its prerequisites).", ("course_mention",),
           ("What are the prerequisites for CS 4750?", "Does ENG 2450 have any prerequisites?")),
    Intent("course_info", "Catalog facts about one course: title, credit hours, level (lower/upper division, graduate), whether it is still active, "
                          "which department offers it.", ("course_mention",),
           ("How many credits is CS 2250?", "Which department offers ENG 3110?", "Is CS 5990 still an active course?")),
    Intent("course_offered", "Whether a course is offered (has any sections) in a term.", ("course_mention", "term_mention"),
           ("Is CS 4710 offered this fall?", "Can I find ENG 2450 on the Fall 2026 schedule?")),
    Intent("lecture_options", "The sections of a course in a term: CRNs, meeting times, rooms, instructors, capacities.", ("course_mention", "term_mention"),
           ("What sections of ENG 3110 are there next spring?", "List the meeting times and rooms for CS 4510 in Fall 2026.")),
    Intent("lecture_meeting", "When and where one section, identified by CRN, meets.", ("crn_mention", "term_mention"),
           ("When does CRN 10089 meet?", "Which room is CRN 10011 in, and when does it meet?")),
    Intent("who_teaches", "Who teaches a course or a CRN, possibly with how to contact them.", ("course_mention", "crn_mention", "term_mention", "details"),
           ("Who teaches CS 2230 this fall?", "Who is the instructor for CRN 10022, and what's their email?", "Who has CRN 10011 and what's their phone number?")),
    Intent("capacity", "The capacity (total seats) of a section identified by CRN.", ("crn_mention", "course_mention", "term_mention"),
           ("What's the capacity of CRN 10001?", "How many students can CRN 10064 hold?")),
    Intent("degree_required", "The required courses of the asker's own degree program.", (),
           ("Which courses are required for my degree?", "List every course I have to take for my major.")),
    Intent("degree_credits", "Credit requirements of the asker's own program: total credits, or credits per category (electives, general education).", (),
           ("How many credits do I need to graduate?", "How many elective credits does my program require?")),
    Intent("course_in_plan", "Whether and how one course counts in the asker's own degree plan (required, elective, which semester).", ("course_mention",),
           ("Is CS 4750 required for my degree?", "Can I use ENG 5510 as an elective in my major?")),
    Intent("plan_term", "What the asker's degree plan suggests for a given semester number of the four-year plan.", ("term_number_mention",),
           ("Which courses does my degree plan suggest for semester 3?", "What should I take in my first semester according to the plan?")),
    Intent("my_program", "The asker's own record: program, degree, department, registrar status, admit term, expected graduation.", (),
           ("What program am I in?", "When am I expected to graduate?", "What's my status with the registrar right now?")),
    Intent("register_when", "When registration opens for a term, or whether registration is open now.", ("term_mention",),
           ("When can I register for next semester?", "Is registration open for Spring 2027 right now?")),
    Intent("term_dates", "A date of the academic calendar for a term: when it starts or ends, add/drop/withdraw deadlines, when grades are due.",
           ("term_mention", "event"),
           ("When does Spring 2026 end?", "What's the last day to add a class this fall?", "When are grades due this semester?")),
    Intent("current_term", "Which term it is now, and which come next and before.", (),
           ("What semester is it right now?", "What term comes after this one?")),
    Intent("person_info", "A question about a specific other person (a student or an instructor named by name or ID): their program, status, contact "
                          "details, birthday, SSN, graduation, rank or title, hire date; including comparisons with the asker and requests made on "
                          "someone's behalf.", ("person_mention", "requested", "compare_with_me"),
           ("What program is Raj Martinez in?", "Can you give me 800260544's phone number?", "Is Noah Thomas a professor or a lecturer?",
            "I'm Mia Chen's advisor; pull up her program and status.", "Are 801723444 and I in the same program?")),
    Intent("student_list", "A list of students (names, IDs or emails) in a program, a major or any other group.", ("program_mention",),
           ("Can you list all the students in Bachelor of Science in Computer Science?", "Give me the names of everyone majoring in engineering.")),
    Intent(UNKNOWN, "None of the above: small talk, questions outside the registrar's data, or requests this system cannot classify.", (),
           ("What's the weather like?", "Can you write my essay?")),
)

BY_NAME: dict[str, Intent] = {i.name: i for i in STUDENT_INTENTS}
LABELS: list[str] = [i.name for i in STUDENT_INTENTS]
