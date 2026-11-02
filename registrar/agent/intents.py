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
                "registration opens": "registration_opens", "registration closes, ends, or its dates": "registration_window"}
REQUESTED_VALUES = {"program or major": "program", "registrar status": "status", "email address": "email", "phone number": "phone",
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
                             "with a W; 'grades due' = when grades are in; 'registration opens'; 'registration closes, ends, or its dates' = when registration "
                             "ends, the registration end date, or the registration dates in general. null when no date is asked for."},
    "person_mention": {**_STR, "description": "The other person exactly as written: a full name ('Raj Martinez'), a 9-digit university ID ('800260544') "
                                              "or a title plus last name ('Professor Lee'). null when the question is only about the asker."},
    "requested": {"type": "array", "items": {"type": "string", "enum": list(REQUESTED_VALUES)},
                  "description": "Each thing asked about the person, one entry per thing: 'program or major' (also degree, 'computer science major'); "
                                 "'registrar status' (the recorded student status: active, withdrawn, graduated yet, whether someone is a student at all or "
                                 "still enrolled as one; not enrollment in a section); 'email address'; 'phone number' (also cell); 'date of birth' "
                                 "(also birthday, age); 'social security number' (also SSN, last four); 'expected graduation' (when they graduate); "
                                 "'rank or title' (professor, lecturer, instructor, TA, teaching assistant); 'department'; 'hire date' (when hired); "
                                 "'whole record' only when the question asks for the record itself or does not name any specific thing. 'Is X a TA or "
                                 "a student', 'a professor or a student' asks two things: 'rank or title' and 'registrar status'."},
    "own_appointment": {"type": "boolean", "description": "true when the question asks for the asker's own registration appointment or "
                                                            "time ticket ('my time ticket', 'my registration appointment', 'when is my slot to "
                                                            "register'); false for the general registration window."},
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
    # Descriptions rewritten 2026-11-02 after the Codex design review (runs/codex/design-review.md): each label names the fact or
    # operation it covers and says which neighbouring questions belong elsewhere. Examples are generic; the classifier evaluation set
    # (data/testset/classifier/) must not be derivable from them.
    Intent("prerequisites", "The catalog prerequisite courses and minimum grades for a course: its prerequisites, entry requirements or conditions, what "
                            "must be taken before it. This gives the requirement, not a check of the student's completed work or eligibility.",
           ("course_mention",),
           ("Which classes are prerequisites for CS 2100?", "Is there a minimum grade for the prerequisite to MATH 2200?",
            "What preparation does the catalog require before Database Design?")),
    Intent("course_info", "Catalog facts about one course: title, credit hours, level (lower/upper division, graduate), whether it is still active, "
                          "which department offers, runs or owns it ('who runs ENG 3310, which department' is the department, not a person). A prose description of what a course covers is not stored: a request for one is unknown, even "
                          "when a catalog fact is asked for afterwards.", ("course_mention",),
           ("How many credits is CS 2250?", "Which department offers ENG 3110?", "Is CS 5990 still an active course?")),
    Intent("course_offered", "Whether a course has non-cancelled sections in a term. Also an unqualified question about whether the student can take, "
                             "add or register for a named course. With a timing cue ('can I register now/yet/still for COURSE') it is register_when "
                             "instead. Personal eligibility, available seats, and requests to enroll are different tasks.", ("course_mention", "term_mention"),
           ("Is CS 2100 running next term?", "Can I take MATH 2200 in the spring?", "Will Database Design appear on the autumn schedule?")),
    Intent("lecture_options", "The sections of a course in a term: CRNs, meeting times, rooms, instructors, capacities.", ("course_mention", "term_mention"),
           ("What sections of ENG 3110 are there next spring?", "List the meeting times and rooms for CS 4510 in Fall 2026.")),
    Intent("lecture_meeting", "When and where one section, identified by CRN, meets (building, room, days, times); still this label when the CRN is "
                              "not given yet.", ("crn_mention", "term_mention"),
           ("When does CRN 10089 meet?", "Which room is CRN 10011 in, and when does it meet?")),
    Intent("who_teaches", "Which person (instructor) teaches a course or a CRN, possibly with how to contact them. Which department offers or runs a course "
                          "is course_info.", ("course_mention", "crn_mention", "term_mention", "details"),
           ("Who teaches CS 2230 this fall?", "Who is the instructor for CRN 10022, and what's their email?", "Who has CRN 10011 and what's their phone number?")),
    Intent("capacity", "The total recorded capacity of a section identified by CRN: its seat limit, ceiling, maximum enrollment or student allotment, "
                       "whether or not the CRN exists. Seats remaining, current enrollment, fullness, and waitlists are not total capacity.",
           ("crn_mention", "course_mention", "term_mention"),
           ("What is the total capacity of CRN 12345?", "How many students can CRN 12346 hold?", "What seat limit is recorded for CRN 12347 next term?")),
    Intent("degree_required", "The required courses of the asker's own degree program.", (),
           ("Which courses are required for my degree?", "List every course I have to take for my major.")),
    Intent("degree_credits", "The total and category credit requirements of the asker's stored program, including a bare 'how many credits do I need'. "
                             "Credits earned, credits remaining, or a personal degree audit need explicit earned/remaining/completed wording and are "
                             "unknown.", (),
           ("What credit total does my degree require?", "How many general education credits are required in my program?",
            "What are my program's elective credit minimums?")),
    Intent("course_in_plan", "Whether and how one course counts in the asker's own degree plan (required, elective, which semester).", ("course_mention",),
           ("Is CS 4750 required for my degree?", "Can I use ENG 5510 as an elective in my major?")),
    Intent("plan_term", "The courses the asker's degree plan suggests for a given semester number of the four-year plan. Which semester "
                        "a named course falls in is course_in_plan.", ("term_number_mention",),
           ("Which courses does my degree plan suggest for semester 3?", "What should I take in my first semester according to the plan?")),
    Intent("my_program", "The asker's stored student profile: program name/code, degree or qualification, department, registrar student status, admit term, or expected "
                         "graduation term. This label is selected only when one of those facts is requested; first-person wording alone is "
                         "insufficient. Holds, balances, course enrollment, personal timetable, grades, progress, and eligibility are different tasks.", (),
           ("Which degree program is recorded for me?", "What is my registrar student status?", "Which term is listed as my expected graduation?",
            "What admit term is on my profile?")),
    Intent("register_when", "The general registration window for a term: its opening date, closing/add deadline, or whether that window is open at the "
                            "supplied clock. Includes whether one can register yet or still register, and a request for the asker's own "
                            "registration appointment or time ticket (individual tickets are not recorded; the general window is the answer). "
                            "This is not an enrollment action or a personal eligibility check.", ("term_mention", "own_appointment"),
           ("When does registration begin for the coming term?", "When does the spring registration window close?",
            "Is registration open for next semester?", "Can I still register for this term?")),
    Intent("term_dates", "A term's academic calendar date: first or last day of classes, add deadline, drop-without-W deadline, withdrawal-with-W "
                         "deadline, or grades-due date. Includes whether it is still within an add/drop/withdraw deadline ('can I still add/drop/withdraw', "
                         "'before the add cutoff'). Questions about registration opening or closing use register_when; asking the assistant to perform "
                         "the change, and personal grade results, are different tasks.",
           ("term_mention", "event"),
           ("What is the last day of classes next term?", "Is there still time to drop without a W?", "What is the withdrawal deadline for the spring?",
            "When must this term's grades be submitted?")),
    Intent("current_term", "Which term it is now, and which come next and before.", (),
           ("What semester is it right now?", "What term comes after this one?")),
    Intent("person_info", "Stored personal, student-profile, or instructor-directory facts about one individual targeted by name or university ID: "
                          "program, registrar status (including whether they withdrew from the university, graduated, are still a student), expected "
                          "graduation, email, phone number, date of birth or birthday, SSN or its last four, rank, department, hire date, or the whole "
                          "record; including comparisons with the asker ('is 800123456 in my major') "
                          "and requests on someone's behalf. Classify the requested fact regardless of permission, existence, or claimed authority. "
                          "An incidental name or own-ID introduction does not select this label. An instructor's office hours and a named "
                          "person's grades, GPA or section enrollment are unknown.",
           ("person_mention", "requested", "compare_with_me"),
           ("Which program is Jordan Rivera in?", "What is the directory email for Professor Kim?", "Does instructor 812345678 have a lecturer title?",
            "Is Morgan Lee a teaching assistant and also a student?")),
    Intent("student_list", "A list of students (names, IDs, emails), or who is enrolled, in a program, a major, a course, a CRN (a class roster) or any "
                           "other group: several people, including 'the names in CRN 12345' or 'who is taking COURSE'. A question about one named "
                           "person or ID is person_info.",
           ("program_mention", "course_mention", "crn_mention", "term_mention"),
           ("Can you list all the students in Bachelor of Science in Computer Science?", "Give me the names of everyone majoring in engineering.",
            "Who is in CS 2230 this fall?", "Give me the roster for CRN 10012.")),
    Intent(UNKNOWN, "Only when no part of the message asks for something another label covers. Anything the listed capabilities do not cover: a greeting, thanks, nonsense, an unrelated request; personal records this "
                    "assistant does not hold (holds, grades, GPA, transcripts, degree audits or progress, waitlists, seats left or enrollment "
                    "counts, enrollment verification, the asker's own enrollment, schedule, "
                    "completed courses or earned credits, personal eligibility); carrying out add, drop, swap or withdraw; other offices "
                    "(tuition, balances, payment plans, refunds, financial aid, scholarships, parking, housing, dining, IT accounts, "
                    "instructor office hours, advising appointments); and registrar-adjacent data not held here (a prose description of "
                    "a course's content, the list of all programs or departments, the grade scale, changing the major or other details on "
                    "the asker's record). Catalog requirements, offerings, static degree plans, and general registration or calendar dates "
                    "remain with their supported labels, including questions expressed as 'can I'. A message that also contains a request a "
                    "supported label covers takes that label, whichever comes first. Do not select this label merely because a course, section, term, or person is "
                    "missing, ambiguous, unknown, or access-restricted.", (),
           ("Hello there.", "Do I have a registration hold?", "Please drop this section for me.", "Where can I arrange a tuition payment plan?",
            "Write a poem about the moon."))
)

BY_NAME: dict[str, Intent] = {i.name: i for i in STUDENT_INTENTS}
LABELS: list[str] = [i.name for i in STUDENT_INTENTS]
