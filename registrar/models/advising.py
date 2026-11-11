"""Advising: the instructor who advises each student (from Duong's advising-agent branch, merged 2026-11-11)."""
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AdvisorAssignment(Base):
    __tablename__ = "advisor_assignment"

    student_university_id: Mapped[str] = mapped_column(ForeignKey("student.university_id"), primary_key=True)
    advisor_university_id: Mapped[str] = mapped_column(ForeignKey("instructor.university_id"), index=True)
