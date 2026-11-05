"""instructor salary, lecture staff, grade submission

Revision ID: 9d2f5b7c41a0
Revises: 64244b3c17e8
Create Date: 2026-11-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d2f5b7c41a0'
down_revision: Union[str, Sequence[str], None] = '64244b3c17e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # existing rows get 0 until scripts/load_seed.py reloads the data; the default is dropped right away
    op.add_column('instructor', sa.Column('salary', sa.Integer(), nullable=False, server_default='0'))
    op.alter_column('instructor', 'salary', server_default=None)
    op.create_table('lecture_staff',
    sa.Column('term_code', sa.String(length=6), nullable=False),
    sa.Column('crn', sa.String(length=5), nullable=False),
    sa.Column('university_id', sa.String(length=9), nullable=False),
    sa.Column('role', sa.String(length=12), nullable=False),
    sa.CheckConstraint("role IN ('instructor', 'ta')", name=op.f('ck_lecture_staff_role')),
    sa.ForeignKeyConstraint(['term_code', 'crn'], ['lecture.term_code', 'lecture.crn'], name=op.f('fk_lecture_staff_term_code_lecture')),
    sa.ForeignKeyConstraint(['university_id'], ['instructor.university_id'], name=op.f('fk_lecture_staff_university_id_instructor')),
    sa.PrimaryKeyConstraint('term_code', 'crn', 'university_id', name=op.f('pk_lecture_staff'))
    )
    op.create_index(op.f('ix_lecture_staff_university_id'), 'lecture_staff', ['university_id'], unique=False)
    op.create_table('grade_submission',
    sa.Column('term_code', sa.String(length=6), nullable=False),
    sa.Column('crn', sa.String(length=5), nullable=False),
    sa.Column('submitted_by', sa.String(length=9), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['submitted_by'], ['instructor.university_id'], name=op.f('fk_grade_submission_submitted_by_instructor')),
    sa.ForeignKeyConstraint(['term_code', 'crn'], ['lecture.term_code', 'lecture.crn'], name=op.f('fk_grade_submission_term_code_lecture')),
    sa.PrimaryKeyConstraint('term_code', 'crn', name=op.f('pk_grade_submission'))
    )
    op.create_index(op.f('ix_grade_submission_submitted_by'), 'grade_submission', ['submitted_by'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_grade_submission_submitted_by'), table_name='grade_submission')
    op.drop_table('grade_submission')
    op.drop_index(op.f('ix_lecture_staff_university_id'), table_name='lecture_staff')
    op.drop_table('lecture_staff')
    op.drop_column('instructor', 'salary')
