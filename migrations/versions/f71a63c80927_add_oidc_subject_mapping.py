"""Pin federated issuer-subject mapping to locally approved user accounts.

Revision ID: f71a63c80927
Revises: c91e8a2048f1
"""
from alembic import op
import sqlalchemy as sa
revision='f71a63c80927'
down_revision='c91e8a2048f1'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('oidc_subject',sa.String(length=200),nullable=True))
        batch.create_index('ix_users_oidc_subject',['oidc_subject'],unique=True)

def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_index('ix_users_oidc_subject')
        batch.drop_column('oidc_subject')
