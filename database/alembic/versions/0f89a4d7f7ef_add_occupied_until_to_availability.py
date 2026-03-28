"""add occupied_until to availability

Revision ID: 0f89a4d7f7ef
Revises: d4b0d15883de
Create Date: 2026-03-27 23:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0f89a4d7f7ef'
down_revision: Union[str, None] = 'd4b0d15883de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('availability', sa.Column('occupied_until', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('availability', 'occupied_until')
