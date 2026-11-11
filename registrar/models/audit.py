"""Audit log of every change an agent writes (registration, drop, withdrawal, grade posting).

One row per committed change, written in the same transaction as the change itself, so a change without an audit
row cannot exist. The only table with a surrogate key: a log entry has no natural one.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ChangeLog(Base):
    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    clock: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # the agent's clock (as_of) at the change
    actor_university_id: Mapped[str] = mapped_column(String(9))
    role: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(32))  # register, drop, withdraw, post_grade
    detail: Mapped[dict] = mapped_column(JSONB)
