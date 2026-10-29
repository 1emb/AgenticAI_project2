"""People: one person row per human, keyed by university id, with student and instructor profiles."""
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import EntryType, Residency, StudentStatus, db_enum


class Person(Base):
    __tablename__ = "person"
    __table_args__ = (CheckConstraint("sex IN ('M', 'F', 'X')", name="sex"),)

    university_id: Mapped[str] = mapped_column(String(9), primary_key=True)  # e.g. 800123456
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80), index=True)
    date_of_birth: Mapped[date] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(1))  # M, F, X
    ssn: Mapped[str] = mapped_column(String(11), unique=True)  # synthetic data; stored raw as 123-45-6789
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(120), unique=True)

    student: Mapped["Student | None"] = relationship(back_populates="person", uselist=False)
    instructor: Mapped["Instructor | None"] = relationship(back_populates="person", uselist=False)


class Student(Base):
    """Undergraduate or graduate is not stored: it follows from program.degree (BS or MS)."""

    __tablename__ = "student"

    university_id: Mapped[str] = mapped_column(ForeignKey("person.university_id"), primary_key=True)
    program_code: Mapped[str] = mapped_column(ForeignKey("program.code"), index=True)
    status: Mapped[StudentStatus] = mapped_column(db_enum(StudentStatus, "student_status"), index=True)
    entry_type: Mapped[EntryType] = mapped_column(db_enum(EntryType, "entry_type"))
    residency: Mapped[Residency] = mapped_column(db_enum(Residency, "residency"))
    admit_term_code: Mapped[str] = mapped_column(ForeignKey("academic_term.code"))
    expected_graduation_term_code: Mapped[str | None] = mapped_column(ForeignKey("academic_term.code"))

    person: Mapped[Person] = relationship(back_populates="student")
    program: Mapped["Program"] = relationship()


class Instructor(Base):
    __tablename__ = "instructor"

    university_id: Mapped[str] = mapped_column(ForeignKey("person.university_id"), primary_key=True)
    department_code: Mapped[str] = mapped_column(ForeignKey("department.code"), index=True)
    rank: Mapped[str] = mapped_column(String(40))  # professor, associate, assistant, lecturer, adjunct, ta
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    hire_date: Mapped[date | None] = mapped_column(Date)

    person: Mapped[Person] = relationship(back_populates="instructor")
    department: Mapped["Department"] = relationship()
    lectures: Mapped[list["Lecture"]] = relationship(back_populates="instructor")


from .academic import Department, Program  # noqa: E402  (resolve forward references)
from .catalog import Lecture  # noqa: E402
