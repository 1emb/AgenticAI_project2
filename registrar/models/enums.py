"""Controlled vocabularies. Stored as VARCHAR with a CHECK constraint (non-native enums)."""
import enum

from sqlalchemy import Enum


def db_enum(py_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(
        py_enum,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        create_constraint=True,
    )


class StudentStatus(str, enum.Enum):
    ACTIVE = "active"
    LEAVE = "leave_of_absence"
    WITHDRAWN = "withdrawn"
    SUSPENDED = "suspended"
    DISMISSED = "dismissed"
    GRADUATED = "graduated"


class EntryType(str, enum.Enum):
    FIRST_TIME = "first_time"
    TRANSFER = "transfer"
    READMIT = "readmit"


class Residency(str, enum.Enum):
    RESIDENT = "resident"
    NONRESIDENT = "nonresident"
    INTERNATIONAL = "international"


class TermType(str, enum.Enum):
    FALL = "fall"
    SPRING = "spring"
    SUMMER = "summer"


class CourseLevel(str, enum.Enum):
    LOWER = "lower_division"
    UPPER = "upper_division"
    GRADUATE = "graduate"


class RequirementCategory(str, enum.Enum):
    CORE = "core"
    ELECTIVE = "elective"
    GENERAL_EDUCATION = "general_education"
