"""Registration: holds, enrollments, waitlists, overrides, time tickets, event log."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import (
    EnrollmentEventType,
    EnrollmentStatus,
    GradingBasis,
    HoldType,
    OverrideType,
    WaitlistStatus,
    db_enum,
)


class Hold(Base):
    __tablename__ = "hold"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    hold_type: Mapped[HoldType] = mapped_column(db_enum(HoldType, "hold_type"))
    placed_by_office: Mapped[str] = mapped_column(String(60))
    placed_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    reason: Mapped[str] = mapped_column(Text)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    blocks_registration: Mapped[bool] = mapped_column(Boolean, default=True)
    blocks_transcript: Mapped[bool] = mapped_column(Boolean, default=False)
    blocks_graduation: Mapped[bool] = mapped_column(Boolean, default=False)


class RegistrationAppointment(Base):
    """Time ticket: when a student may begin registering for a term."""

    __tablename__ = "registration_appointment"
    __table_args__ = (UniqueConstraint("student_id", "term_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"), index=True)
    begins_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    priority_group: Mapped[str | None] = mapped_column(String(30))  # senior, honors, athlete, veteran


class Enrollment(Base):
    __tablename__ = "enrollment"
    __table_args__ = (UniqueConstraint("student_id", "section_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"), index=True)  # denormalized for speed
    status: Mapped[EnrollmentStatus] = mapped_column(db_enum(EnrollmentStatus, "enrollment_status"), index=True)
    grading_basis: Mapped[GradingBasis] = mapped_column(db_enum(GradingBasis, "grading_basis"), default=GradingBasis.LETTER)
    credits: Mapped[float] = mapped_column(Numeric(3, 1))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dropped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_repeat: Mapped[bool] = mapped_column(Boolean, default=False)

    grade: Mapped["Grade | None"] = relationship(back_populates="enrollment", uselist=False)
    events: Mapped[list["EnrollmentEvent"]] = relationship(back_populates="enrollment")


class EnrollmentEvent(Base):
    """Append-only log of everything that happened to an enrollment."""

    __tablename__ = "enrollment_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollment.id"), index=True)
    event_type: Mapped[EnrollmentEventType] = mapped_column(db_enum(EnrollmentEventType, "enrollment_event_type"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    channel: Mapped[str] = mapped_column(String(20), default="self_service")  # self_service, staff, agent, batch
    details: Mapped[dict | None] = mapped_column(JSON)

    enrollment: Mapped[Enrollment] = relationship(back_populates="events")


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entry"
    __table_args__ = (UniqueConstraint("section_id", "student_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[WaitlistStatus] = mapped_column(db_enum(WaitlistStatus, "waitlist_status"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RegistrationOverride(Base):
    __tablename__ = "registration_override"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"), index=True)
    override_type: Mapped[OverrideType] = mapped_column(db_enum(OverrideType, "override_type"))
    granted_by_person_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
