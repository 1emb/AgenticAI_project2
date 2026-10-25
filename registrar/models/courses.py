"""Catalog, prerequisites, schedule of classes, rooms."""
from datetime import time

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import CourseLevel, InstructionMode, InstructorRole, PrereqType, SectionStatus, db_enum


class Subject(Base):
    __tablename__ = "subject"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(6), unique=True)  # CS, MATH, ENGL
    name: Mapped[str] = mapped_column(String(120))
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)


class Course(Base):
    __tablename__ = "course"
    __table_args__ = (UniqueConstraint("subject_id", "course_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id"), index=True)
    course_number: Mapped[str] = mapped_column(String(6))  # 1110, 2210, 3315L
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    credits_min: Mapped[float] = mapped_column(Numeric(3, 1))
    credits_max: Mapped[float] = mapped_column(Numeric(3, 1))
    level: Mapped[CourseLevel] = mapped_column(db_enum(CourseLevel, "course_level"))
    is_gen_ed: Mapped[bool] = mapped_column(Boolean, default=False)
    gen_ed_area: Mapped[str | None] = mapped_column(String(40))  # communication, math, science, humanities...
    is_repeatable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"))
    retired_term_id: Mapped[int | None] = mapped_column(ForeignKey("academic_term.id"))

    subject: Mapped[Subject] = relationship()
    prerequisites: Mapped[list["CoursePrerequisite"]] = relationship(
        back_populates="course", foreign_keys="CoursePrerequisite.course_id"
    )


class CoursePrerequisite(Base):
    """Rows sharing a group_number are alternatives (OR); different groups are all required (AND)."""

    __tablename__ = "course_prerequisite"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)
    required_course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)
    prereq_type: Mapped[PrereqType] = mapped_column(db_enum(PrereqType, "prereq_type"))
    min_grade: Mapped[str] = mapped_column(String(2), default="C-")
    group_number: Mapped[int] = mapped_column(Integer, default=1)

    course: Mapped[Course] = relationship(back_populates="prerequisites", foreign_keys=[course_id])
    required_course: Mapped[Course] = relationship(foreign_keys=[required_course_id])


class Building(Base):
    __tablename__ = "building"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Room(Base):
    __tablename__ = "room"
    __table_args__ = (UniqueConstraint("building_id", "room_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("building.id"), index=True)
    room_number: Mapped[str] = mapped_column(String(10))
    capacity: Mapped[int] = mapped_column(Integer)
    room_type: Mapped[str] = mapped_column(String(30))  # classroom, lab, lecture_hall, seminar
    has_av: Mapped[bool] = mapped_column(Boolean, default=True)


class Section(Base):
    __tablename__ = "section"
    __table_args__ = (
        UniqueConstraint("term_id", "crn"),
        UniqueConstraint("term_id", "course_id", "section_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_term.id"), index=True)
    crn: Mapped[str] = mapped_column(String(6))  # course reference number, unique within a term
    section_number: Mapped[str] = mapped_column(String(4))  # M01, 001, D01 (distance)
    credits: Mapped[float] = mapped_column(Numeric(3, 1))
    capacity: Mapped[int] = mapped_column(Integer)
    waitlist_capacity: Mapped[int] = mapped_column(Integer, default=10)
    instruction_mode: Mapped[InstructionMode] = mapped_column(db_enum(InstructionMode, "instruction_mode"))
    status: Mapped[SectionStatus] = mapped_column(db_enum(SectionStatus, "section_status"), default=SectionStatus.OPEN)
    campus: Mapped[str] = mapped_column(String(30), default="Las Cruces")
    notes: Mapped[str | None] = mapped_column(Text)

    course: Mapped[Course] = relationship()
    meetings: Mapped[list["SectionMeeting"]] = relationship(back_populates="section")
    instructors: Mapped[list["SectionInstructor"]] = relationship(back_populates="section")


class SectionMeeting(Base):
    __tablename__ = "section_meeting"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"), index=True)
    days: Mapped[str] = mapped_column(String(7))  # subset of MTWRFSU
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("room.id"), index=True)
    meeting_type: Mapped[str] = mapped_column(String(20), default="lecture")  # lecture, lab, discussion

    section: Mapped[Section] = relationship(back_populates="meetings")


class SectionInstructor(Base):
    __tablename__ = "section_instructor"
    __table_args__ = (UniqueConstraint("section_id", "instructor_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"), index=True)
    instructor_id: Mapped[int] = mapped_column(ForeignKey("instructor.id"), index=True)
    role: Mapped[InstructorRole] = mapped_column(db_enum(InstructorRole, "instructor_role"))

    section: Mapped[Section] = relationship(back_populates="instructors")
