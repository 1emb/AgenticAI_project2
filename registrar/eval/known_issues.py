"""Test-set wordings no correct agent can pass, kept in one place for the tests and the evaluation scripts.
The evaluation reports them separately; tests/test_professor_tools.py checks each one still fails, so the list shrinks
when the generator is fixed."""
from __future__ import annotations

# (case id, wording), "*" for every wording of the case.
PROFESSOR_UNANSWERABLE: dict[tuple[str, str], str] = {
    ("prof-access_allowed-008", "*"):
        "prerequisites expected as [[codes]]; course_catalog cases with the same wording expect [[{course, min_grade}]]",
    ("prof-enrollment_count-005", "How many students are enrolled in CRN 10120?"):
        "bare CRN that is the user's own section this term, yet the answer is the Spring 2027 section",
    ("prof-enrollment_count-005", "How many seats are left in CRN 10120?"):
        "bare CRN that is the user's own section this term, yet the answer is the Spring 2027 section",
    ("prof-roster-003", "Which students are taking my ENGL 1120 class last spring?"):
        "the user had two ENGL 1120 sections that term; the answer names one",
    ("prof-withdrawals-002", "Who withdrew from my PSY 1110 section last term?"):
        "the user had three PSY 1110 sections that term; the answer names one",
    ("prof-withdrawals-004", "Who withdrew from my CS 1110 section in Spring 2026?"):
        "the user had two CS 1110 sections that term; the answer names one",
    ("prof-section_grades-002", "Show me the grades for my PHIL 2110 section last semester."):
        "the user had two PHIL 2110 sections that term; the answer names one",
}


def professor_unanswerable(case: dict, question: str, session=None) -> str | None:
    return PROFESSOR_UNANSWERABLE.get((case["id"], "*")) or PROFESSOR_UNANSWERABLE.get((case["id"], question))
