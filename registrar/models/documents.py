"""Transcripts, verifications, FERPA, disclosures, petitions."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .enums import (
    DeliveryMethod,
    EnrollmentLoad,
    PetitionStatus,
    PetitionType,
    ReleaseScope,
    RequestStatus,
    TranscriptType,
    db_enum,
)


class TranscriptRequest(Base):
    __tablename__ = "transcript_request"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)  # person, not student: alumni too
    transcript_type: Mapped[TranscriptType] = mapped_column(db_enum(TranscriptType, "transcript_type"))
    delivery_method: Mapped[DeliveryMethod] = mapped_column(db_enum(DeliveryMethod, "delivery_method"))
    recipient_name: Mapped[str] = mapped_column(String(160))
    recipient_email: Mapped[str | None] = mapped_column(String(120))
    recipient_address: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[RequestStatus] = mapped_column(db_enum(RequestStatus, "request_status"), index=True)
    fee: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    fee_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    hold_note: Mapped[str | None] = mapped_column(Text)


class EnrollmentVerification(Base):
    __tablename__ = "enrollment_verification"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"))
    purpose: Mapped[str] = mapped_column(String(80))  # insurance, loan_deferment, employment, housing, other
    recipient_name: Mapped[str] = mapped_column(String(160))
    recipient_contact: Mapped[str | None] = mapped_column(String(200))
    enrollment_load: Mapped[EnrollmentLoad | None] = mapped_column(db_enum(EnrollmentLoad, "enrollment_load"))
    status: Mapped[RequestStatus] = mapped_column(db_enum(RequestStatus, "request_status"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))


class FerpaRelease(Base):
    """Student authorizes a named third party (usually a parent) to receive specified information."""

    __tablename__ = "ferpa_release"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    authorized_name: Mapped[str] = mapped_column(String(160))
    relationship_to_student: Mapped[str] = mapped_column(String(40))
    authorized_email: Mapped[str | None] = mapped_column(String(120))
    authorized_phone: Mapped[str | None] = mapped_column(String(30))
    scope: Mapped[ReleaseScope] = mapped_column(db_enum(ReleaseScope, "release_scope"))
    passphrase_hash: Mapped[str | None] = mapped_column(String(64))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FerpaDirectoryOptOut(Base):
    """Student has suppressed directory information (name, enrollment, major, etc.)."""

    __tablename__ = "ferpa_directory_optout"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), unique=True)
    opted_out_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DisclosureLog(Base):
    """FERPA requires a record of each non-exempt disclosure of education records."""

    __tablename__ = "disclosure_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    disclosed_to: Mapped[str] = mapped_column(String(160))
    disclosed_to_type: Mapped[str] = mapped_column(String(40))  # parent, employer, agency, institution, lender, court
    data_categories: Mapped[str] = mapped_column(String(200))  # comma-separated: grades,enrollment,degree
    legal_basis: Mapped[str] = mapped_column(String(80))  # consent, subpoena, directory_info, school_official
    disclosed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    disclosed_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    release_id: Mapped[int | None] = mapped_column(ForeignKey("ferpa_release.id"))


class Petition(Base):
    """Policy exception requests: late add/drop, overload, residency, appeals."""

    __tablename__ = "petition"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    petition_type: Mapped[PetitionType] = mapped_column(db_enum(PetitionType, "petition_type"), index=True)
    term_id: Mapped[int | None] = mapped_column(ForeignKey("academic_term.id"))
    section_id: Mapped[int | None] = mapped_column(ForeignKey("section.id"))
    status: Mapped[PetitionStatus] = mapped_column(db_enum(PetitionStatus, "petition_status"), index=True)
    student_statement: Mapped[str] = mapped_column(Text)
    supporting_documents: Mapped[str | None] = mapped_column(Text)  # paths / URIs
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_rationale: Mapped[str | None] = mapped_column(Text)
