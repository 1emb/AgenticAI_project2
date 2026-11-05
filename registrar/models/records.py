"""Student records: which student sits in which lecture with what grade, and credit accepted from another institution."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import EnrollmentStatus, db_enum


class Enrollment(Base):
    """One student in one lecture. The grade is null while the course is in progress or registered for a coming term,
    W when the student withdrew, and a letter grade or I once graded; `status` says which of the three it is."""

    __tablename__ = "enrollment"
    __table_args__ = (
        ForeignKeyConstraint(["term_code", "crn"], ["lecture.term_code", "lecture.crn"]),
        CheckConstraint("(status = 'enrolled' AND grade IS NULL) OR (status = 'withdrawn' AND grade = 'W') "
                        "OR (status = 'completed' AND grade IS NOT NULL AND grade <> 'W')", name="status_grade"),
    )

    term_code: Mapped[str] = mapped_column(String(6), primary_key=True)
    crn: Mapped[str] = mapped_column(String(5), primary_key=True)
    student_university_id: Mapped[str] = mapped_column(ForeignKey("student.university_id"), primary_key=True, index=True)
    status: Mapped[EnrollmentStatus] = mapped_column(db_enum(EnrollmentStatus, "enrollment_status"))
    grade: Mapped[str | None] = mapped_column(ForeignKey("grade_scale.letter"))

    lecture: Mapped["Lecture"] = relationship()
    student: Mapped["Student"] = relationship()


class TransferCredit(Base):
    """A course accepted from another institution for a transfer student: it earns credit and satisfies prerequisites,
    but carries no grade and is outside the GPA."""

    __tablename__ = "transfer_credit"

    student_university_id: Mapped[str] = mapped_column(ForeignKey("student.university_id"), primary_key=True)
    course_code: Mapped[str] = mapped_column(ForeignKey("course.code"), primary_key=True)  # the course here it was accepted as
    credit_hours: Mapped[float] = mapped_column(Numeric(3, 1))
    accepted_term_code: Mapped[str] = mapped_column(ForeignKey("academic_term.code"))  # the term the credit was posted

    student: Mapped["Student"] = relationship()
    course: Mapped["Course"] = relationship()


class LectureStaff(Base):
    """Who works on a section, and as what (2026-11-05). Every section has its instructor of record here with role `instructor`
    (the same person as lecture.instructor_university_id); teaching assistants are added with role `ta`."""

    __tablename__ = "lecture_staff"
    __table_args__ = (
        ForeignKeyConstraint(["term_code", "crn"], ["lecture.term_code", "lecture.crn"]),
        CheckConstraint("role IN ('instructor', 'ta')", name="role"),
    )

    term_code: Mapped[str] = mapped_column(String(6), primary_key=True)
    crn: Mapped[str] = mapped_column(String(5), primary_key=True)
    university_id: Mapped[str] = mapped_column(ForeignKey("instructor.university_id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(12))

    lecture: Mapped["Lecture"] = relationship()
    instructor: Mapped["Instructor"] = relationship()


class GradeSubmission(Base):
    """A section whose final grades were submitted, by whom and when (2026-11-05). No row: not submitted yet (every Fall 2026
    and Spring 2027 section), or nothing to grade (no students). Grades are due by academic_term.grades_due."""

    __tablename__ = "grade_submission"
    __table_args__ = (ForeignKeyConstraint(["term_code", "crn"], ["lecture.term_code", "lecture.crn"]),)

    term_code: Mapped[str] = mapped_column(String(6), primary_key=True)
    crn: Mapped[str] = mapped_column(String(5), primary_key=True)
    submitted_by: Mapped[str] = mapped_column(ForeignKey("instructor.university_id"), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    lecture: Mapped["Lecture"] = relationship()


from .catalog import Course, Lecture  # noqa: E402
from .people import Instructor, Student  # noqa: E402
