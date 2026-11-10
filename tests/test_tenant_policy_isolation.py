"""End-to-end lender-policy boundaries and upgrade regression tests."""
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from aadharshila.db import SessionLocal
from aadharshila.models import Application, Organization, Policy, User
from aadharshila.security import hash_password, token_for
from aadharshila.service import active_policy, build_assessment


def test_lender_policies_cannot_cross_organizations(client, login, cases):
    """Both API and assessment layer enforce tenant ownership independently."""
    login('analyst')
    with SessionLocal() as db:
        original = db.scalar(select(Organization).where(Organization.name=='Aadharshila Demo'))
        original_policy = active_policy(db, 'LAP', original.id)
        sample = db.get(Application, cases['AS-1002']['id'])
        second = Organization(name='Independent lender ' + uuid.uuid4().hex[:12])
        db.add(second)
        db.flush()
        foreign_author = User(org_id=second.id, username='tenant-author-'+uuid.uuid4().hex[:10],
                              role='POLICY_AUTHOR', password_hash=hash_password('unused-test-only'))
        foreign_approver = User(org_id=second.id, username='tenant-approver-'+uuid.uuid4().hex[:10],
                                role='POLICY_APPROVER', password_hash=hash_password('unused-test-only'))
        db.add_all([foreign_author,foreign_approver])
        db.flush()
        foreign_policy = Policy(org_id=second.id,name='Second lender illustration',product='LAP',
                                version=1,state='ACTIVE',config={**original_policy.config,'annual_rate_percent':12.5},
                                author_id=foreign_author.id,approver_id=foreign_approver.id)
        db.add(foreign_policy)
        db.commit()
        second_id=second.id
        foreign_id=foreign_policy.id
        first_id=original_policy.id
        author_token=token_for(foreign_author)
        approver_token=token_for(foreign_approver)
    try:
        with SessionLocal() as db:
            assert active_policy(db,'LAP',second_id).id==foreign_id
            assert active_policy(db,'LAP',original.id).id==first_id
            with pytest.raises(ValueError, match='Cross-organization'):
                build_assessment(db, db.get(Application,sample.id), policy=db.get(Policy,foreign_id))

        headers={'Authorization':'Bearer '+author_token}
        result=client.get('/api/v1/policies', headers=headers)
        assert result.status_code==200
        assert {p['id'] for p in result.json()['items']}=={foreign_id}
        assert client.post('/api/v1/policies/'+first_id+'/validate',headers=headers).status_code==404
        assert client.post('/api/v1/policies/'+first_id+'/simulate',headers=headers).status_code==404
        assert client.get('/api/v1/applications/'+sample.id,headers=headers).status_code==404
        approver={'Authorization':'Bearer '+approver_token}
        assert client.post('/api/v1/policies/'+first_id+'/approve',headers=approver,json={'reason':'Foreign lender cannot approve this policy'}).status_code==404
        assert client.post('/api/v1/policies/'+first_id+'/activate',headers=approver,json={'reason':'Foreign lender cannot activate this policy'}).status_code==404
        config=result.json()['items'][0]['config']
        create=client.post('/api/v1/policies',json={'product':'LAP','config':config},headers=headers)
        assert create.status_code==201,create.text
        assert create.json()['version']==2

        # Existing lender's policies stay unchanged by second-lender policy drafting.
        original_view=client.get('/api/v1/policies',headers={'Authorization':'Bearer '+token_for(_first_lender_author())})
        assert original_view.status_code==200
        assert foreign_id not in {p['id'] for p in original_view.json()['items']}
    finally:
        with SessionLocal() as db:
            db.query(Policy).filter(Policy.org_id==second_id).delete(synchronize_session=False)
            db.query(User).filter(User.org_id==second_id).delete(synchronize_session=False)
            db.query(Organization).filter(Organization.id==second_id).delete(synchronize_session=False)
            db.commit()


def _first_lender_author():
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.username=='policy_author'))


def test_legacy_migration_backfills_policy_owners(tmp_path):
    db_path=tmp_path/'legacy.sqlite'
    root=Path(__file__).resolve().parents[1]
    env={**os.environ, 'DATABASE_URL':'sqlite:///'+str(db_path), 'APP_ENV':'development'}
    def migrate(target):
        return subprocess.run([sys.executable,'-m','alembic','upgrade',target],cwd=root,
                              env=env,capture_output=True,text=True,timeout=40)
    old=migrate('a320f6c2026b')
    assert old.returncode==0,old.stderr
    with sqlite3.connect(db_path) as db:
        db.execute('INSERT INTO organizations(id,name) VALUES (?,?)',('tenant-legacy','Legacy lender'))
        db.execute('INSERT INTO users(id,org_id,username,password_hash,role,active) VALUES (?,?,?,?,?,?)',
                   ('author-legacy','tenant-legacy','legacy-author','unused','POLICY_AUTHOR',1))
        db.execute('INSERT INTO policies(id,name,product,version,state,config,author_id,approver_id) VALUES (?,?,?,?,?,?,?,?)',
                   ('policy-legacy','Legacy policy','HOME_LOAN',1,'ACTIVE',json.dumps({'product':'HOME_LOAN'}),'author-legacy',None))
    upgraded=migrate('head')
    assert upgraded.returncode==0,upgraded.stderr
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT org_id FROM policies WHERE id=?',('policy-legacy',)).fetchone()[0]=='tenant-legacy'
        cols=[r[1] for r in db.execute('PRAGMA table_info(policies)')]
        assert 'org_id' in cols
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        db.execute('INSERT INTO organizations(id,name) VALUES (?,?)',('tenant-new','New lender'))
        db.execute('INSERT INTO policies(id,org_id,name,product,version,state,config) VALUES (?,?,?,?,?,?,?)',
                   ('policy-new','tenant-new','Other loan','HOME_LOAN',1,'ACTIVE','{}'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO policies(id,org_id,name,product,version,state,config) VALUES (?,?,?,?,?,?,?)',
                       ('duplicate','tenant-legacy','Wrong','HOME_LOAN',1,'ACTIVE','{}'))


def test_only_one_active_policy_per_lender_product(cases):
    from sqlalchemy.exc import IntegrityError
    with SessionLocal() as db:
        org=db.scalar(select(Organization).where(Organization.name=='Aadharshila Demo'))
        current=active_policy(db,'HOME_LOAN',org.id)
        impossible=Policy(org_id=org.id, name='Simultaneous active policy',
                          product='HOME_LOAN', version=current.version+10000,
                          state='ACTIVE',config={**current.config,'version':current.version+10000})
        db.add(impossible)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_logout_requires_authenticated_csrf(client,login):
    login('borrower')
    assert client.get('/api/v1/auth/me').status_code==200
    rejected=client.post('/api/v1/auth/logout')
    assert rejected.status_code==403
    assert client.get('/api/v1/auth/me').status_code==200
    token=client.cookies.get('aadharshila_csrf')
    ok=client.post('/api/v1/auth/logout',headers={'X-CSRF-Token':token})
    assert ok.status_code==200
    assert client.get('/api/v1/auth/me').status_code==401
