"""Link evidence records to provider invocations.

Revision ID: a320f6c2026b
Revises: db86f5f7b680
"""
from alembic import op
import sqlalchemy as sa
revision='a320f6c2026b'
down_revision='db86f5f7b680'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('evidence') as batch:
        batch.add_column(sa.Column('provider_invocation_id',sa.String(36),nullable=True))
        batch.create_index('ix_evidence_provider_invocation_id',['provider_invocation_id'])
        batch.create_foreign_key('fk_evidence_provider_invocation','provider_invocations',
                                 ['provider_invocation_id'],['id'])
def downgrade():
    with op.batch_alter_table('evidence') as batch:
        batch.drop_constraint('fk_evidence_provider_invocation',type_='foreignkey')
        batch.drop_index('ix_evidence_provider_invocation_id')
        batch.drop_column('provider_invocation_id')
