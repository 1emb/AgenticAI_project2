"""Enrollment and advising: the two tables the 12-table schema left out (README, Next steps 2).

enrollment: one row per student, term and course. `crn` names the section when the term has lecture rows (Fall 2024
on); it is null for earlier terms, whose sections are not in `lecture` (adding them would change the professor test
set's teaching history). Seats taken = rows with status 'enrolled' per (term_code, crn).

advisor_assignment: the instructor who advises each student.
"""
from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .enums import db_enum

import enum


class EnrollmentStatus(str, enum.Enum):
    ENROLLED = "enrolled"
    DROPPED = "dropped"  # before the drop deadline, no W, not on the transcript
    WITHDRAWN = "withdrawn"  # after the drop deadline, grade W


class Enrollment(Base):
    __tablename__ = "enrollment"
    __table_args__ = (
        ForeignKeyConstraint(["term_code", "crn"], ["lecture.term_code", "lecture.crn"]),
        CheckConstraint("status <> 'withdrawn' OR grade = 'W'", name="withdrawn_has_w"),
        CheckConstraint("status <> 'dropped' OR grade IS NULL", name="dropped_has_no_grade"),
    )

    student_university_id: Mapped[str] = mapped_column(ForeignKey("student.university_id"), primary_key=True)
    term_code: Mapped[str] = mapped_column(ForeignKey("academic_term.code"), primary_key=True)
    course_code: Mapped[str] = mapped_column(ForeignKey("course.code"), primary_key=True)
    crn: Mapped[str | None] = mapped_column(String(5))  # null before lecture data starts (Fall 2024)
    status: Mapped[EnrollmentStatus] = mapped_column(db_enum(EnrollmentStatus, "enrollment_status"))
    grade: Mapped[str | None] = mapped_column(ForeignKey("grade_scale.letter"))  # null = not posted yet


class AdvisorAssignment(Base):
    __tablename__ = "advisor_assignment"

    student_university_id: Mapped[str] = mapped_column(ForeignKey("student.university_id"), primary_key=True)
    advisor_university_id: Mapped[str] = mapped_column(ForeignKey("instructor.university_id"), index=True)
