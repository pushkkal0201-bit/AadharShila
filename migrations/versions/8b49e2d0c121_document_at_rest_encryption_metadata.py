"""Track encryption metadata separately from plaintext upload fingerprints.

Revision ID: 8b49e2d0c121
Revises: f71a63c80927
"""
from alembic import op
import sqlalchemy as sa

revision = '8b49e2d0c121'
down_revision = 'f71a63c80927'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('storage_format', sa.String(length=32),
                                   nullable=False, server_default='PLAINTEXT_DEVELOPMENT'))
        batch.add_column(sa.Column('storage_sha256', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('encryption_key_id', sa.String(length=64), nullable=True))


def downgrade():
    # Dropping encryption metadata would make encrypted documents unreadable;
    # a destructive rollback must not silently proceed.
    raise RuntimeError('Encrypted document metadata cannot be safely dropped. Restore the prior schema and files from a verified backup.')
