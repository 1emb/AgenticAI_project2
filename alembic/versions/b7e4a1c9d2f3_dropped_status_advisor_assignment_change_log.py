"""dropped enrollment status, advisor assignment, change log

Merge of Duong's advising-agent branch into main (2026-11-11). His own enrollment table is not used: the enrollment
table of 64244b3c17e8 stays and gains a fourth status, `dropped` (left by the drop deadline: no grade, no seat, not
on the transcript). advisor_assignment and change_log come from his migrations d67e9bad4b1e and 22250c5ff9f0.

Revision ID: b7e4a1c9d2f3
Revises: 9d2f5b7c41a0
Create Date: 2026-11-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b7e4a1c9d2f3'
down_revision: Union[str, Sequence[str], None] = '9d2f5b7c41a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATUS = "status IN ('enrolled', 'completed', 'withdrawn')"
NEW_STATUS = "status IN ('enrolled', 'completed', 'withdrawn', 'dropped')"
OLD_GRADE = ("(status = 'enrolled' AND grade IS NULL) OR (status = 'withdrawn' AND grade = 'W') "
             "OR (status = 'completed' AND grade IS NOT NULL AND grade <> 'W')")
NEW_GRADE = OLD_GRADE + " OR (status = 'dropped' AND grade IS NULL)"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f('ck_enrollment_enrollment_status'), 'enrollment', type_='check')
    op.create_check_constraint(op.f('ck_enrollment_enrollment_status'), 'enrollment', NEW_STATUS)
    op.drop_constraint(op.f('ck_enrollment_status_grade'), 'enrollment', type_='check')
    op.create_check_constraint(op.f('ck_enrollment_status_grade'), 'enrollment', NEW_GRADE)
    op.create_table('advisor_assignment',
    sa.Column('student_university_id', sa.String(length=9), nullable=False),
    sa.Column('advisor_university_id', sa.String(length=9), nullable=False),
    sa.ForeignKeyConstraint(['advisor_university_id'], ['instructor.university_id'], name=op.f('fk_advisor_assignment_advisor_university_id_instructor')),
    sa.ForeignKeyConstraint(['student_university_id'], ['student.university_id'], name=op.f('fk_advisor_assignment_student_university_id_student')),
    sa.PrimaryKeyConstraint('student_university_id', name=op.f('pk_advisor_assignment'))
    )
    op.create_index(op.f('ix_advisor_assignment_advisor_university_id'), 'advisor_assignment', ['advisor_university_id'], unique=False)
    op.create_table('change_log',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('clock', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor_university_id', sa.String(length=9), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_change_log'))
    )


def downgrade() -> None:
    """Downgrade schema. Dropped rows are deleted first: the old constraints do not allow them."""
    op.drop_table('change_log')
    op.drop_index(op.f('ix_advisor_assignment_advisor_university_id'), table_name='advisor_assignment')
    op.drop_table('advisor_assignment')
    op.execute("DELETE FROM enrollment WHERE status = 'dropped'")
    op.drop_constraint(op.f('ck_enrollment_status_grade'), 'enrollment', type_='check')
    op.create_check_constraint(op.f('ck_enrollment_status_grade'), 'enrollment', OLD_GRADE)
    op.drop_constraint(op.f('ck_enrollment_enrollment_status'), 'enrollment', type_='check')
    op.create_check_constraint(op.f('ck_enrollment_enrollment_status'), 'enrollment', OLD_STATUS)
