"""Student records: which student sits in which lecture with what grade, and credit accepted from another institution."""
from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Numeric, String
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


from .catalog import Course, Lecture  # noqa: E402
from .people import Student  # noqa: E402
