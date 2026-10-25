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


class StudentLevel(str, enum.Enum):
    UNDERGRADUATE = "undergraduate"
    GRADUATE = "graduate"


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


class ProgramType(str, enum.Enum):
    MAJOR = "major"
    MINOR = "minor"
    CERTIFICATE = "certificate"


class StudentProgramStatus(str, enum.Enum):
    DECLARED = "declared"
    CHANGED = "changed"
    COMPLETED = "completed"
    DROPPED = "dropped"


class RequirementType(str, enum.Enum):
    CORE = "core"
    MAJOR_ELECTIVE = "major_elective"
    GENERAL_EDUCATION = "general_education"
    FREE_ELECTIVE = "free_elective"
    RESIDENCY = "residency"


class TermType(str, enum.Enum):
    FALL = "fall"
    SPRING = "spring"
    SUMMER = "summer"


class CourseLevel(str, enum.Enum):
    LOWER = "lower_division"
    UPPER = "upper_division"
    GRADUATE = "graduate"


class PrereqType(str, enum.Enum):
    PREREQUISITE = "prerequisite"
    COREQUISITE = "corequisite"


class InstructionMode(str, enum.Enum):
    IN_PERSON = "in_person"
    ONLINE = "online"
    HYBRID = "hybrid"


class SectionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class InstructorRole(str, enum.Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TA = "teaching_assistant"


class HoldType(str, enum.Enum):
    FINANCIAL = "financial"
    ADVISING = "advising"
    CONDUCT = "conduct"
    IMMUNIZATION = "immunization"
    REGISTRAR = "registrar"
    ADMISSIONS = "admissions"


class EnrollmentStatus(str, enum.Enum):
    REGISTERED = "registered"
    WAITLISTED = "waitlisted"
    DROPPED = "dropped"
    WITHDRAWN = "withdrawn"
    COMPLETED = "completed"


class GradingBasis(str, enum.Enum):
    LETTER = "letter"
    SATISFACTORY = "s_u"
    AUDIT = "audit"


class EnrollmentEventType(str, enum.Enum):
    REGISTER = "register"
    DROP = "drop"
    WITHDRAW = "withdraw"
    WAITLIST_ADD = "waitlist_add"
    WAITLIST_PROMOTE = "waitlist_promote"
    WAITLIST_REMOVE = "waitlist_remove"
    GRADE_POST = "grade_post"
    GRADE_CHANGE = "grade_change"
    OVERRIDE = "override_applied"


class OverrideType(str, enum.Enum):
    PREREQUISITE = "prerequisite"
    CAPACITY = "capacity"
    TIME_CONFLICT = "time_conflict"
    LEVEL = "level"
    CREDIT_OVERLOAD = "credit_overload"


class WaitlistStatus(str, enum.Enum):
    WAITING = "waiting"
    NOTIFIED = "notified"
    ENROLLED = "enrolled"
    EXPIRED = "expired"
    REMOVED = "removed"


class AcademicStanding(str, enum.Enum):
    GOOD = "good_standing"
    DEANS_LIST = "deans_list"
    PROBATION = "probation"
    SUSPENSION = "suspension"
    DISMISSAL = "dismissal"


class AcademicActionType(str, enum.Enum):
    PROBATION = "probation"
    SUSPENSION = "suspension"
    DISMISSAL = "dismissal"
    REINSTATEMENT = "reinstatement"
    DEANS_LIST = "deans_list"
    APPEAL_GRANTED = "appeal_granted"
    APPEAL_DENIED = "appeal_denied"


class TransferStatus(str, enum.Enum):
    PENDING = "pending"
    AWARDED = "awarded"
    DENIED = "denied"


class TestType(str, enum.Enum):
    AP = "AP"
    IB = "IB"
    CLEP = "CLEP"
    DSST = "DSST"


class GraduationAppStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    DENIED = "denied"
    CONFERRED = "conferred"


class Honors(str, enum.Enum):
    NONE = "none"
    CUM_LAUDE = "cum_laude"
    MAGNA = "magna_cum_laude"
    SUMMA = "summa_cum_laude"


class TranscriptType(str, enum.Enum):
    OFFICIAL = "official"
    UNOFFICIAL = "unofficial"


class DeliveryMethod(str, enum.Enum):
    ELECTRONIC = "electronic"
    MAIL = "mail"
    PICKUP = "pickup"


class RequestStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    ON_HOLD = "on_hold"
    PROCESSING = "processing"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class EnrollmentLoad(str, enum.Enum):
    FULL_TIME = "full_time"
    THREE_QUARTER = "three_quarter_time"
    HALF_TIME = "half_time"
    LESS_THAN_HALF = "less_than_half_time"
    NOT_ENROLLED = "not_enrolled"


class ReleaseScope(str, enum.Enum):
    GRADES = "grades"
    ENROLLMENT = "enrollment"
    FINANCIAL = "financial"
    ALL = "all"


class PetitionType(str, enum.Enum):
    LATE_ADD = "late_add"
    LATE_DROP = "late_drop"
    RETRO_WITHDRAWAL = "retroactive_withdrawal"
    CREDIT_OVERLOAD = "credit_overload"
    RESIDENCY_RECLASS = "residency_reclassification"
    STANDING_APPEAL = "academic_standing_appeal"
    GRADE_APPEAL = "grade_appeal"
    REQUIREMENT_WAIVER = "requirement_waiver"


class PetitionStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    DENIED = "denied"


class AddressType(str, enum.Enum):
    PERMANENT = "permanent"
    MAILING = "mailing"
    LOCAL = "local"
