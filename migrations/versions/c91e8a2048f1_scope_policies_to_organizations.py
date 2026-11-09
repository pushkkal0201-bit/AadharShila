"""Scope credit policies to the owning lender.

Revision ID: c91e8a2048f1
Revises: a320f6c2026b

Legacy ownership is derived from policy author/approver organizations. When it
cannot be established unambiguously, the migration stops instead of guessing.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c91e8a2048f1'
down_revision = 'a320f6c2026b'
branch_labels = None
depends_on = None

CONVENTION = {'uq': 'uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s'}


def upgrade():
    conn = op.get_bind()
    accounts = dict(conn.execute(sa.text('SELECT id, org_id FROM users')).all())
    orgs = [row[0] for row in conn.execute(sa.text('SELECT id FROM organizations')).all()]
    policies = conn.execute(sa.text(
        'SELECT id, product, state, author_id, approver_id FROM policies'
    )).all()
    ownership = {}
    active = set()
    for policy_id, product, state, author_id, approver_id in policies:
        signers = [user_id for user_id in (author_id, approver_id) if user_id]
        if any(user_id not in accounts for user_id in signers):
            raise RuntimeError('Policy author or approver is missing; resolve ownership')
        candidates = {accounts[user_id] for user_id in signers}
        if len(candidates) == 1:
            org_id = candidates.pop()
        elif not candidates and len(orgs) == 1:
            org_id = orgs[0]
        else:
            raise RuntimeError('Ambiguous policy organization; resolve ownership')
        ownership[policy_id] = org_id
        if state == 'ACTIVE':
            key = (org_id, product)
            if key in active:
                raise RuntimeError('Multiple active policies for one lender/product')
            active.add(key)

    # All data checks occur before schema DDL (especially important on SQLite).
    op.add_column('policies', sa.Column('org_id', sa.String(36), nullable=True))
    for policy_id, org_id in ownership.items():
        conn.execute(sa.text(
            'UPDATE policies SET org_id=:org_id WHERE id=:id'
        ), {'org_id': org_id, 'id': policy_id})

    previous_unique = ('policies_product_version_key'
                       if conn.dialect.name == 'postgresql'
                       else 'uq_policies_product_version')
    with op.batch_alter_table('policies', naming_convention=CONVENTION) as batch:
        batch.alter_column('org_id', existing_type=sa.String(36), nullable=False)
        batch.drop_constraint(previous_unique, type_='unique')
        batch.create_foreign_key('fk_policies_org_id', 'organizations',
                                 ['org_id'], ['id'])
        batch.create_unique_constraint('uq_policies_org_product_version',
                                       ['org_id', 'product', 'version'])
        batch.create_index('ix_policies_org_id', ['org_id'])
    op.create_index('uq_policies_one_active_per_org_product', 'policies',
                    ['org_id', 'product'], unique=True,
                    sqlite_where=sa.text("state='ACTIVE'"),
                    postgresql_where=sa.text("state='ACTIVE'"))


def downgrade():
    conn = op.get_bind()
    duplicate = conn.execute(sa.text(
        'SELECT product, version FROM policies '
        'GROUP BY product, version HAVING count(*) > 1'
    )).first()
    if duplicate:
        raise RuntimeError('Tenant-specific versions prevent safe downgrade')
    op.drop_index('uq_policies_one_active_per_org_product', table_name='policies')
    with op.batch_alter_table('policies', naming_convention=CONVENTION) as batch:
        batch.drop_index('ix_policies_org_id')
        batch.drop_constraint('uq_policies_org_product_version', type_='unique')
        batch.drop_constraint('fk_policies_org_id', type_='foreignkey')
        batch.create_unique_constraint('uq_policies_product_version',
                                       ['product', 'version'])
        batch.drop_column('org_id')
