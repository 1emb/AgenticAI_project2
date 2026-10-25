"""People and identity: one person row per human, with role-specific profiles."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import (
    AddressType,
    EntryType,
    Residency,
    StudentLevel,
    StudentProgramStatus,
    StudentStatus,
    db_enum,
)


class Person(TimestampMixin, Base):
    __tablename__ = "person"

    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[str] = mapped_column(String(9), unique=True, index=True)  # e.g. 800123456
    legal_first_name: Mapped[str] = mapped_column(String(80))
    legal_middle_name: Mapped[str | None] = mapped_column(String(80))
    legal_last_name: Mapped[str] = mapped_column(String(80), index=True)
    preferred_first_name: Mapped[str | None] = mapped_column(String(80))
    pronouns: Mapped[str | None] = mapped_column(String(30))
    date_of_birth: Mapped[date] = mapped_column(Date)
    legal_sex: Mapped[str | None] = mapped_column(String(1))
    gender_identity: Mapped[str | None] = mapped_column(String(40))
    ssn_hash: Mapped[str | None] = mapped_column(String(64))  # never store raw SSN
    citizenship_country: Mapped[str] = mapped_column(String(2), default="US")
    ethnicity: Mapped[str | None] = mapped_column(String(40))
    race: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(120), unique=True)
    personal_email: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(30))
    is_deceased: Mapped[bool] = mapped_column(Boolean, default=False)

    student: Mapped["Student | None"] = relationship(back_populates="person", uselist=False)
    addresses: Mapped[list["Address"]] = relationship(back_populates="person")


class PersonNameHistory(Base):
    __tablename__ = "person_name_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    old_first_name: Mapped[str | None] = mapped_column(String(80))
    old_middle_name: Mapped[str | None] = mapped_column(String(80))
    old_last_name: Mapped[str | None] = mapped_column(String(80))
    new_first_name: Mapped[str] = mapped_column(String(80))
    new_middle_name: Mapped[str | None] = mapped_column(String(80))
    new_last_name: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(String(120))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))


class Address(Base):
    __tablename__ = "address"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    address_type: Mapped[AddressType] = mapped_column(db_enum(AddressType, "address_type"))
    line1: Mapped[str] = mapped_column(String(120))
    line2: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(40))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2), default="US")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)

    person: Mapped[Person] = relationship(back_populates="addresses")


class EmergencyContact(Base):
    __tablename__ = "emergency_contact"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    relationship_to_person: Mapped[str] = mapped_column(String(40))
    phone: Mapped[str] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(120))
    priority: Mapped[int] = mapped_column(Integer, default=1)


class Student(TimestampMixin, Base):
    __tablename__ = "student"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), unique=True)
    level: Mapped[StudentLevel] = mapped_column(db_enum(StudentLevel, "student_level"))
    status: Mapped[StudentStatus] = mapped_column(db_enum(StudentStatus, "student_status"), index=True)
    entry_type: Mapped[EntryType] = mapped_column(db_enum(EntryType, "entry_type"))
    residency: Mapped[Residency] = mapped_column(db_enum(Residency, "residency"))
    admit_term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"))
    catalog_term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"))
    expected_graduation_term_id: Mapped[int | None] = mapped_column(ForeignKey("academic_term.id"))
    status_effective_term_id: Mapped[int | None] = mapped_column(ForeignKey("academic_term.id"))
    first_generation: Mapped[bool] = mapped_column(Boolean, default=False)
    high_school_name: Mapped[str | None] = mapped_column(String(120))
    high_school_gpa: Mapped[float | None]
    is_veteran: Mapped[bool] = mapped_column(Boolean, default=False)
    is_athlete: Mapped[bool] = mapped_column(Boolean, default=False)
    is_honors: Mapped[bool] = mapped_column(Boolean, default=False)
    sevis_id: Mapped[str | None] = mapped_column(String(20))

    person: Mapped[Person] = relationship(back_populates="student")
    programs: Mapped[list["StudentProgram"]] = relationship(back_populates="student")


class StudentProgram(Base):
    """A student's declared major, minor, or certificate. Supports double majors and changes."""

    __tablename__ = "student_program"
    __table_args__ = (UniqueConstraint("student_id", "program_id", "declared_term_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("program.id"), index=True)
    catalog_term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"))
    declared_term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"))
    ended_term_id: Mapped[int | None] = mapped_column(ForeignKey("academic_term.id"))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[StudentProgramStatus] = mapped_column(db_enum(StudentProgramStatus, "student_program_status"))
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    student: Mapped[Student] = relationship(back_populates="programs")
    program: Mapped["Program"] = relationship()


class Instructor(Base):
    __tablename__ = "instructor"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), unique=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    rank: Mapped[str] = mapped_column(String(40))  # professor, associate, assistant, lecturer, adjunct, ta
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    hire_date: Mapped[date | None] = mapped_column(Date)

    person: Mapped[Person] = relationship()


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), unique=True)
    office: Mapped[str] = mapped_column(String(60), index=True)  # registrar, admissions, bursar, financial_aid, ...
    title: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    person: Mapped[Person] = relationship()


class AdvisorAssignment(Base):
    __tablename__ = "advisor_assignment"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    advisor_person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)


from .academic import Program  # noqa: E402  (resolve forward reference)
