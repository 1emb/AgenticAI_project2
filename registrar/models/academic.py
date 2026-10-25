"""Academic structure: colleges, departments, programs, requirements, terms, calendar."""
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import ProgramType, RequirementType, TermType, db_enum


class College(Base):
    __tablename__ = "college"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    dean_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))

    departments: Mapped[list["Department"]] = relationship(back_populates="college")


class Department(Base):
    __tablename__ = "department"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id"), index=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    chair_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))

    college: Mapped[College] = relationship(back_populates="departments")
    programs: Mapped[list["Program"]] = relationship(back_populates="department")


class Program(Base):
    __tablename__ = "program"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    degree_type: Mapped[str | None] = mapped_column(String(10))  # BA, BS, BBA, BSN, BSEE ... null for minors
    program_type: Mapped[ProgramType] = mapped_column(db_enum(ProgramType, "program_type"))
    total_credits_required: Mapped[int] = mapped_column(Integer)
    min_gpa: Mapped[float] = mapped_column(Numeric(3, 2), default=2.0)
    upper_division_credits_required: Mapped[int] = mapped_column(Integer, default=0)
    residency_credits_required: Mapped[int] = mapped_column(Integer, default=30)
    cip_code: Mapped[str | None] = mapped_column(String(10))  # federal classification, IPEDS
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    department: Mapped[Department] = relationship(back_populates="programs")
    requirements: Mapped[list["ProgramRequirement"]] = relationship(back_populates="program")


class ProgramRequirement(Base):
    """One block of a degree plan for a given catalog year, e.g. 'Core' or 'Gen Ed: Communication'."""

    __tablename__ = "program_requirement"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("program.id"), index=True)
    catalog_term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"))
    name: Mapped[str] = mapped_column(String(120))
    requirement_type: Mapped[RequirementType] = mapped_column(db_enum(RequirementType, "requirement_type"))
    min_credits: Mapped[int] = mapped_column(Integer, default=0)
    min_courses: Mapped[int] = mapped_column(Integer, default=0)
    min_grade: Mapped[str | None] = mapped_column(String(2))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)

    program: Mapped[Program] = relationship(back_populates="requirements")
    courses: Mapped[list["ProgramRequirementCourse"]] = relationship(back_populates="requirement")


class ProgramRequirementCourse(Base):
    """Courses that can satisfy a requirement block."""

    __tablename__ = "program_requirement_course"
    __table_args__ = (UniqueConstraint("requirement_id", "course_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("program_requirement.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)  # False = one of several options

    requirement: Mapped[ProgramRequirement] = relationship(back_populates="courses")


class AcademicTerm(Base):
    __tablename__ = "academic_term"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(6), unique=True)  # e.g. 202680 = Fall 2026
    name: Mapped[str] = mapped_column(String(30))
    term_type: Mapped[TermType] = mapped_column(db_enum(TermType, "term_type"))
    academic_year: Mapped[int] = mapped_column(Integer)  # 2026 for 2026-27
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    registration_opens: Mapped[date] = mapped_column(Date)
    add_deadline: Mapped[date] = mapped_column(Date)
    drop_deadline: Mapped[date] = mapped_column(Date)  # drop without W
    census_date: Mapped[date] = mapped_column(Date)
    withdraw_deadline: Mapped[date] = mapped_column(Date)  # W grade deadline
    grades_due: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    sequence: Mapped[int] = mapped_column(Integer, unique=True)  # ordinal for "next term" math


class AcademicCalendarEvent(Base):
    __tablename__ = "academic_calendar_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(40))  # holiday, deadline, commencement, finals
    event_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
