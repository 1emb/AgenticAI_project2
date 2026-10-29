"""Academic structure: departments, degree programs, terms."""
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import TermType, db_enum


class Department(Base):
    __tablename__ = "department"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)  # CS, ENG
    name: Mapped[str] = mapped_column(String(120))

    programs: Mapped[list["Program"]] = relationship(back_populates="department")


class Program(Base):
    """A degree program, e.g. BS in Computer Science. Its required courses live in degree_requirement,
    the credits it needs per category in program_category_requirement."""

    __tablename__ = "program"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)  # BSCS, BSENG
    department_code: Mapped[str] = mapped_column(ForeignKey("department.code"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    degree: Mapped[str] = mapped_column(String(10))  # BS, MS
    total_credits_required: Mapped[int] = mapped_column(Integer)
    min_gpa: Mapped[float] = mapped_column(Numeric(3, 2), default=2.0, server_default="2.00")

    department: Mapped[Department] = relationship(back_populates="programs")
    requirements: Mapped[list["DegreeRequirement"]] = relationship(back_populates="program")
    category_requirements: Mapped[list["ProgramCategoryRequirement"]] = relationship(back_populates="program")


class AcademicTerm(Base):
    """The current term is not stored: derive it from the clock against start_date and end_date."""

    __tablename__ = "academic_term"

    code: Mapped[str] = mapped_column(String(6), primary_key=True)  # 202680 = Fall 2026, 202710 = Spring 2027
    name: Mapped[str] = mapped_column(String(30))
    term_type: Mapped[TermType] = mapped_column(db_enum(TermType, "term_type"))
    academic_year: Mapped[int] = mapped_column(Integer)  # 2026 for 2026-27
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    registration_opens: Mapped[date] = mapped_column(Date)
    add_deadline: Mapped[date] = mapped_column(Date)
    drop_deadline: Mapped[date] = mapped_column(Date)  # drop without W
    withdraw_deadline: Mapped[date] = mapped_column(Date)  # W grade deadline
    grades_due: Mapped[date] = mapped_column(Date)
    sequence: Mapped[int] = mapped_column(Integer, unique=True)  # ordinal for "next term" math


from .catalog import DegreeRequirement, ProgramCategoryRequirement  # noqa: E402
