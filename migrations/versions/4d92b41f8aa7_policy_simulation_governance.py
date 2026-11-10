"""Auditable, lender-scoped policy simulations prior to approval.

Revision ID: 4d92b41f8aa7
Revises: 3ca0f1e4ab25
"""
from alembic import op
import sqlalchemy as sa
revision='4d92b41f8aa7'
down_revision='3ca0f1e4ab25'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('policy_simulations',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('org_id',sa.String(36),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('policy_id',sa.String(36),sa.ForeignKey('policies.id'),nullable=False),
        sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('policy_sha256',sa.String(64),nullable=False),
        sa.Column('report',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_policy_simulations_org_id','policy_simulations',['org_id'])
    op.create_index('ix_policy_simulations_policy_id','policy_simulations',['policy_id'])

def downgrade():
    op.drop_index('ix_policy_simulations_policy_id',table_name='policy_simulations')
    op.drop_index('ix_policy_simulations_org_id',table_name='policy_simulations')
    op.drop_table('policy_simulations')
