"""Grades: the letters the registrar can record and the points they carry."""
from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GradeScale(Base):
    """One row per letter grade. Rows are inserted by the initial migration, not by the seed.
    GPA uses rows with points; a grade earns credit when points > 0. W (withdrawn) and I (incomplete)
    carry no points, so they are left out of GPA and earn nothing."""

    __tablename__ = "grade_scale"

    letter: Mapped[str] = mapped_column(String(2), primary_key=True)  # A, A-, B+, ... F, W, I
    points: Mapped[float | None] = mapped_column(Numeric(2, 1))  # 4.0 down to 0.0; null for W and I
