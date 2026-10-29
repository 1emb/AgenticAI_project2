"""Catalog (what courses exist and what they need), degree plans (what a program requires, course by course
and credits by category),
and lectures (which instructor teaches which course in which term)."""
from datetime import time

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import CourseLevel, RequirementCategory, db_enum


class Course(Base):
    __tablename__ = "course"
    __table_args__ = (UniqueConstraint("subject", "number"),)

    code: Mapped[str] = mapped_column(String(10), primary_key=True)  # "CS 2210", subject + space + number
    subject: Mapped[str] = mapped_column(ForeignKey("department.code"))  # CS, ENG, MATH: the owning department
    number: Mapped[str] = mapped_column(String(5))  # 1110, 2210, 3315L
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    credit_hours: Mapped[float] = mapped_column(Numeric(3, 1))
    level: Mapped[CourseLevel] = mapped_column(db_enum(CourseLevel, "course_level"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    prerequisites: Mapped[list["CoursePrerequisite"]] = relationship(
        back_populates="course", foreign_keys="CoursePrerequisite.course_code"
    )


class CoursePrerequisite(Base):
    """Rows sharing a group_number are alternatives (OR); different groups are all required (AND)."""

    __tablename__ = "course_prerequisite"
    __table_args__ = (CheckConstraint("course_code <> required_course_code", name="not_self"),)

    course_code: Mapped[str] = mapped_column(ForeignKey("course.code"), primary_key=True)
    required_course_code: Mapped[str] = mapped_column(ForeignKey("course.code"), primary_key=True)
    min_grade: Mapped[str] = mapped_column(ForeignKey("grade_scale.letter"), default="C-", server_default="C-")
    group_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    course: Mapped[Course] = relationship(back_populates="prerequisites", foreign_keys=[course_code])
    required_course: Mapped[Course] = relationship(foreign_keys=[required_course_code])


class DegreeRequirement(Base):
    """One course in a program's degree plan: what a student must (or may) take to graduate."""

    __tablename__ = "degree_requirement"

    program_code: Mapped[str] = mapped_column(ForeignKey("program.code"), primary_key=True)
    course_code: Mapped[str] = mapped_column(ForeignKey("course.code"), primary_key=True)
    category: Mapped[RequirementCategory] = mapped_column(db_enum(RequirementCategory, "requirement_category"))
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))  # False = one of several options in its category
    suggested_term_number: Mapped[int | None] = mapped_column(Integer)  # 1..8 in the four-year plan

    program: Mapped["Program"] = relationship(back_populates="requirements")
    course: Mapped[Course] = relationship()


class ProgramCategoryRequirement(Base):
    """Credits a program needs from one category, e.g. BSCS needs 12 elective credits.
    Core needs no row: its credits are the sum of the required courses in degree_requirement."""

    __tablename__ = "program_category_requirement"

    program_code: Mapped[str] = mapped_column(ForeignKey("program.code"), primary_key=True)
    category: Mapped[RequirementCategory] = mapped_column(
        db_enum(RequirementCategory, "requirement_category"), primary_key=True
    )
    min_credits: Mapped[int] = mapped_column(Integer)

    program: Mapped["Program"] = relationship(back_populates="category_requirements")


class Lecture(Base):
    """A course offered in a term by one instructor, with its weekly meeting pattern.
    Seats taken and whether it is full are not stored; they come from enrollment."""

    __tablename__ = "lecture"

    term_code: Mapped[str] = mapped_column(ForeignKey("academic_term.code"), primary_key=True)
    crn: Mapped[str] = mapped_column(String(5), primary_key=True)  # course reference number, unique within a term
    course_code: Mapped[str] = mapped_column(ForeignKey("course.code"), index=True)
    section_number: Mapped[str] = mapped_column(String(4))  # M01, M02
    instructor_university_id: Mapped[str] = mapped_column(ForeignKey("instructor.university_id"), index=True)
    days: Mapped[str] = mapped_column(String(7))  # subset of MTWRFSU
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    room: Mapped[str | None] = mapped_column(String(30))  # "SH 118"
    capacity: Mapped[int] = mapped_column(Integer)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    course: Mapped[Course] = relationship()
    instructor: Mapped["Instructor"] = relationship(back_populates="lectures")


from .academic import Program  # noqa: E402
from .people import Instructor  # noqa: E402
