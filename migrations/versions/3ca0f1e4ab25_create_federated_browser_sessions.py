"""Persist individually revocable opaque browser sessions.

Revision ID: 3ca0f1e4ab25
Revises: 8b49e2d0c121
"""
from alembic import op
import sqlalchemy as sa
revision='3ca0f1e4ab25'
down_revision='8b49e2d0c121'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('federated_sessions',
        sa.Column('token_hash',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('revoked_at',sa.DateTime(timezone=True),nullable=True))
    op.create_index('ix_federated_sessions_user_id','federated_sessions',['user_id'])

def downgrade():
    op.drop_index('ix_federated_sessions_user_id',table_name='federated_sessions')
    op.drop_table('federated_sessions')
