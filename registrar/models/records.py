"""Academic record: grades, term summaries, standing, transfer credit, graduation, degrees, audits."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import (
    AcademicActionType,
    AcademicStanding,
    GraduationAppStatus,
    Honors,
    TestType,
    TransferStatus,
    db_enum,
)


class Grade(Base):
    __tablename__ = "grade"

    id: Mapped[int] = mapped_column(primary_key=True)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollment.id"), unique=True)
    grade: Mapped[str] = mapped_column(String(2), index=True)  # A, A-, B+ ... F, W, I, S, U, NR
    quality_points: Mapped[float | None] = mapped_column(Numeric(4, 2))  # per credit; null for non-GPA grades
    counts_in_gpa: Mapped[bool] = mapped_column(Boolean, default=True)
    earns_credit: Mapped[bool] = mapped_column(Boolean, default=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    posted_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    incomplete_deadline: Mapped[date | None] = mapped_column(Date)

    enrollment: Mapped["Enrollment"] = relationship(back_populates="grade")
    changes: Mapped[list["GradeChange"]] = relationship(back_populates="grade_row")


class GradeChange(Base):
    __tablename__ = "grade_change"

    id: Mapped[int] = mapped_column(primary_key=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grade.id"), index=True)
    old_grade: Mapped[str] = mapped_column(String(2))
    new_grade: Mapped[str] = mapped_column(String(2))
    reason: Mapped[str] = mapped_column(Text)
    requested_by_person_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    approved_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    grade_row: Mapped[Grade] = relationship(back_populates="changes")


class StudentTermRecord(Base):
    """One row per student per term after grades post: credits, GPA, standing."""

    __tablename__ = "student_term_record"
    __table_args__ = (UniqueConstraint("student_id", "term_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"), index=True)
    attempted_credits: Mapped[float] = mapped_column(Numeric(5, 1))
    earned_credits: Mapped[float] = mapped_column(Numeric(5, 1))
    gpa_credits: Mapped[float] = mapped_column(Numeric(5, 1))
    term_gpa: Mapped[float | None] = mapped_column(Numeric(4, 3))
    cumulative_attempted: Mapped[float] = mapped_column(Numeric(6, 1))
    cumulative_earned: Mapped[float] = mapped_column(Numeric(6, 1))
    cumulative_gpa: Mapped[float | None] = mapped_column(Numeric(4, 3))
    standing: Mapped[AcademicStanding] = mapped_column(db_enum(AcademicStanding, "academic_standing"))
    classification: Mapped[str] = mapped_column(String(12))  # freshman, sophomore, junior, senior
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AcademicAction(Base):
    """Probation, suspension, dismissal, dean's list, appeals: things that change standing."""

    __tablename__ = "academic_action"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"), index=True)
    action_type: Mapped[AcademicActionType] = mapped_column(db_enum(AcademicActionType, "academic_action_type"))
    action_date: Mapped[date] = mapped_column(Date)
    decided_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class TransferInstitution(Base):
    __tablename__ = "transfer_institution"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(40))
    country: Mapped[str] = mapped_column(String(2), default="US")
    institution_type: Mapped[str] = mapped_column(String(30))  # community_college, university, military, international
    ipeds_unit_id: Mapped[str | None] = mapped_column(String(10))


class ArticulationRule(Base):
    """Standing equivalency: external course -> our course."""

    __tablename__ = "articulation_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("transfer_institution.id"), index=True)
    external_course_code: Mapped[str] = mapped_column(String(20))
    external_course_title: Mapped[str | None] = mapped_column(String(120))
    external_credits: Mapped[float] = mapped_column(Numeric(3, 1))
    equivalent_course_id: Mapped[int | None] = mapped_column(ForeignKey("course.id"))  # null = elective credit only
    effective_term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"))
    expires_term_id: Mapped[int | None] = mapped_column(ForeignKey("academic_term.id"))


class TransferCredit(Base):
    __tablename__ = "transfer_credit"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("transfer_institution.id"), index=True)
    external_course_code: Mapped[str] = mapped_column(String(20))
    external_course_title: Mapped[str | None] = mapped_column(String(120))
    external_credits: Mapped[float] = mapped_column(Numeric(3, 1))
    external_grade: Mapped[str | None] = mapped_column(String(4))
    external_term: Mapped[str | None] = mapped_column(String(20))
    equivalent_course_id: Mapped[int | None] = mapped_column(ForeignKey("course.id"))
    awarded_credits: Mapped[float] = mapped_column(Numeric(3, 1), default=0)
    status: Mapped[TransferStatus] = mapped_column(db_enum(TransferStatus, "transfer_status"))
    articulation_rule_id: Mapped[int | None] = mapped_column(ForeignKey("articulation_rule.id"))
    evaluated_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TestCredit(Base):
    """AP / IB / CLEP credit."""

    __tablename__ = "test_credit"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    test_type: Mapped[TestType] = mapped_column(db_enum(TestType, "test_type"))
    test_subject: Mapped[str] = mapped_column(String(80))
    score: Mapped[str] = mapped_column(String(6))
    test_date: Mapped[date | None] = mapped_column(Date)
    equivalent_course_id: Mapped[int | None] = mapped_column(ForeignKey("course.id"))
    credits_awarded: Mapped[float] = mapped_column(Numeric(3, 1))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GraduationApplication(Base):
    __tablename__ = "graduation_application"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("program.id"))
    intended_term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"), index=True)
    status: Mapped[GraduationAppStatus] = mapped_column(db_enum(GraduationAppStatus, "graduation_app_status"), index=True)
    diploma_name: Mapped[str] = mapped_column(String(160))
    attending_commencement: Mapped[bool] = mapped_column(Boolean, default=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)


class DegreeAwarded(Base):
    __tablename__ = "degree_awarded"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("program.id"))
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("graduation_application.id"))
    conferred_date: Mapped[date] = mapped_column(Date)
    honors: Mapped[Honors] = mapped_column(db_enum(Honors, "honors"), default=Honors.NONE)
    final_gpa: Mapped[float] = mapped_column(Numeric(4, 3))
    total_credits: Mapped[float] = mapped_column(Numeric(5, 1))
    diploma_printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diploma_mailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DegreeAudit(Base):
    """Snapshot of a degree audit run (actual or what-if)."""

    __tablename__ = "degree_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("program.id"))
    catalog_term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"))
    is_what_if: Mapped[bool] = mapped_column(Boolean, default=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    is_complete: Mapped[bool] = mapped_column(Boolean)
    credits_earned: Mapped[float] = mapped_column(Numeric(5, 1))
    credits_remaining: Mapped[float] = mapped_column(Numeric(5, 1))
    result: Mapped[dict] = mapped_column(JSON)  # per-requirement satisfied / remaining courses


from .enrollment import Enrollment  # noqa: E402
