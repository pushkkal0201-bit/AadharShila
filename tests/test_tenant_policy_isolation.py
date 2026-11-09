"""Security regressions for lender policy ownership and schema upgrades."""
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from aadharshila.db import SessionLocal
from aadharshila.models import Application, Organization, Policy, User
from aadharshila.security import hash_password, token_for
from aadharshila.service import active_policy, build_assessment


def test_lender_policy_isolation_across_api_and_assessment(client, cases, login):
    login('analyst')
    with SessionLocal() as db:
        original = db.scalar(select(Organization).where(Organization.name == 'Aadharshila Demo'))
        original_policy = active_policy(db, 'LAP', original.id)
        case_id = cases['AS-1002']['id']
        other = Organization(name='Independent lender ' + uuid.uuid4().hex[:12])
        db.add(other)
        db.flush()
        author = User(org_id=other.id, username='other-author-'+uuid.uuid4().hex[:10],
                      password_hash=hash_password('test-only'), role='POLICY_AUTHOR')
        approver = User(org_id=other.id, username='other-approver-'+uuid.uuid4().hex[:10],
                        password_hash=hash_password('test-only'), role='POLICY_APPROVER')
        db.add_all([author, approver])
        db.flush()
        p = Policy(org_id=other.id, name='Independent lender rules', product='LAP',
                   version=1, state='ACTIVE',
                   config={**original_policy.config, 'annual_rate_percent': 12.5},
                   author_id=author.id, approver_id=approver.id)
        db.add(p)
        db.commit()
        org_id, policy_id, first_id = other.id, p.id, original_policy.id
        author_token, approver_token = token_for(author), token_for(approver)
    try:
        with SessionLocal() as db:
            assert active_policy(db, 'LAP', org_id).id == policy_id
            assert active_policy(db, 'LAP', original.id).id == first_id
            with pytest.raises(ValueError, match='Cross-organization'):
                build_assessment(db, db.get(Application, case_id), policy=db.get(Policy, policy_id))
        h = {'Authorization': 'Bearer ' + author_token}
        listing = client.get('/api/v1/policies', headers=h)
        assert listing.status_code == 200
        assert {x['id'] for x in listing.json()['items']} == {policy_id}
        assert client.post('/api/v1/policies/'+first_id+'/validate', headers=h).status_code == 404
        assert client.post('/api/v1/policies/'+first_id+'/simulate', headers=h).status_code == 404
        assert client.get('/api/v1/applications/'+case_id, headers=h).status_code == 404
        approver_h = {'Authorization': 'Bearer ' + approver_token}
        assert client.post('/api/v1/policies/'+first_id+'/approve', headers=approver_h).status_code == 404
        assert client.post('/api/v1/policies/'+first_id+'/activate', headers=approver_h).status_code == 404
        creation = client.post('/api/v1/policies', headers=h, json={
            'product':'LAP','config':listing.json()['items'][0]['config']})
        assert creation.status_code == 201, creation.text
        assert creation.json()['version'] == 2
    finally:
        with SessionLocal() as db:
            db.query(Policy).filter(Policy.org_id == org_id).delete(synchronize_session=False)
            db.query(User).filter(User.org_id == org_id).delete(synchronize_session=False)
            db.query(Organization).filter(Organization.id == org_id).delete(synchronize_session=False)
            db.commit()


def test_single_active_policy_per_lender_product(cases):
    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.name == 'Aadharshila Demo'))
        current = active_policy(db, 'HOME_LOAN', org.id)
        db.add(Policy(org_id=org.id, product='HOME_LOAN', name='Competing version',
                      version=current.version+10000, state='ACTIVE',
                      config={**current.config, 'version':current.version+10000}))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_logout_requires_csrf_for_cookie_auth(client, login):
    login('borrower')
    assert client.get('/api/v1/auth/me').status_code == 200
    assert client.post('/api/v1/auth/logout').status_code == 403
    assert client.get('/api/v1/auth/me').status_code == 200
    csrf = client.cookies.get('aadharshila_csrf')
    assert client.post('/api/v1/auth/logout', headers={'X-CSRF-Token':csrf}).status_code == 200
    assert client.get('/api/v1/auth/me').status_code == 401


def test_legacy_policy_migration_and_tenant_version_uniqueness(tmp_path):
    path=tmp_path/'legacy.sqlite'
    root=Path(__file__).resolve().parents[1]
    env={**os.environ, 'DATABASE_URL':'sqlite:///'+str(path), 'APP_ENV':'development'}
    def upgrade(target):
        return subprocess.run([sys.executable,'-m','alembic','upgrade',target],cwd=root,
                              env=env,text=True,capture_output=True,timeout=40)
    old=upgrade('a320f6c2026b')
    assert old.returncode==0,old.stderr
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO organizations(id,name) VALUES ('old-org','Legacy lender')")
        db.execute("INSERT INTO users(id,org_id,username,password_hash,role,active) VALUES ('old-author','old-org','old-author','test-only','POLICY_AUTHOR',1)")
        db.execute("INSERT INTO policies(id,name,product,version,state,config,author_id) VALUES (?,?,?,?,?,?,?)",
                   ('old-policy','Historical HOME_LOAN','HOME_LOAN',1,'ACTIVE',
                    json.dumps({'product':'HOME_LOAN'}),'old-author'))
    upgraded=upgrade('head')
    assert upgraded.returncode==0,upgraded.stderr
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT org_id FROM policies WHERE id='old-policy'").fetchone()[0]=='old-org'
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
        db.execute("INSERT INTO organizations(id,name) VALUES ('second-org','Other lender')")
        db.execute("INSERT INTO policies(id,org_id,name,product,version,state,config) VALUES (?,?,?,?,?,?,?)",
                   ('new-policy','second-org','Different lender','HOME_LOAN',1,'ACTIVE','{}'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO policies(id,org_id,name,product,version,state,config) VALUES (?,?,?,?,?,?,?)",
                       ('duplicate-policy','old-org','Duplicate','HOME_LOAN',1,'ACTIVE','{}'))
