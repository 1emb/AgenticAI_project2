"""Accounts, roles, permissions, and the global audit log."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UserAccount(Base):
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), unique=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(String(200))


class Permission(Base):
    __tablename__ = "permission"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)  # enrollment.register.self, grade.post, transcript.issue
    description: Mapped[str | None] = mapped_column(String(200))


class RolePermission(Base):
    __tablename__ = "role_permission"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), index=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permission.id"), index=True)


class UserRole(Base):
    """Role grant, optionally scoped to a department or college (e.g. a chair of one department)."""

    __tablename__ = "user_role"
    __table_args__ = (UniqueConstraint("user_id", "role_id", "department_id", "college_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("department.id"))
    college_id: Mapped[int | None] = mapped_column(ForeignKey("college.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    granted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Who changed what. Every write through the application layer should land here."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"), index=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="user")  # user, agent, system, batch
    action: Mapped[str] = mapped_column(String(40))  # insert, update, delete, read_sensitive
    table_name: Mapped[str] = mapped_column(String(60), index=True)
    record_id: Mapped[int | None] = mapped_column(index=True)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    reason: Mapped[str | None] = mapped_column(String(200))
