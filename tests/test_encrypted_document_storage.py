"""Cross-platform document encryption, provenance and recovery regression suite.

Only synthetic document bytes and ephemeral test-only keys are used.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path

import pytest

from aadharshila.secure_documents import (
    DocumentIntegrityError, DocumentKeyUnavailable, encrypt_document, decrypt_document,
    storage_filename, FORMAT_ENCRYPTED, FORMAT_LEGACY,
)
from aadharshila.recovery import backup_sqlite, restore_sqlite
from aadharshila.db import SessionLocal
from aadharshila.models import Document


def configure_keys(monkeypatch, tmp_path, *, key_ids=('key-a',)):
    ring={name:base64.b64encode(os.urandom(32)).decode('ascii') for name in key_ids}
    filename=tmp_path/'institution-doc-keys.json'
    filename.write_text(json.dumps(ring),encoding='utf-8')
    monkeypatch.setenv('AADHARSHILA_DOCUMENT_KEYS_PATH',str(filename))
    monkeypatch.setenv('AADHARSHILA_DOCUMENT_ACTIVE_KEY_ID',key_ids[0])
    return filename,ring


def test_encryption_roundtrip_nonce_and_ownership_binding(monkeypatch,tmp_path):
    configure_keys(monkeypatch,tmp_path)
    raw=b'Mortgage statement - SYNTHETIC ONLY; no real person data'
    doc_id=str(uuid.uuid4())
    a=encrypt_document(raw,'org-a','application-a',doc_id)
    b=encrypt_document(raw,'org-a','application-a',doc_id)
    assert a.storage_format==FORMAT_ENCRYPTED
    assert raw not in a.contents and a.contents!=b.contents
    assert a.storage_sha256==hashlib.sha256(a.contents).hexdigest()
    args=dict(storage_format=a.storage_format,key_id=a.key_id,org_id='org-a',
              application_id='application-a',document_id=doc_id,
              plaintext_sha256=hashlib.sha256(raw).hexdigest(),stored_sha256=a.storage_sha256)
    assert decrypt_document(a.contents,**args)==raw
    with pytest.raises(DocumentIntegrityError):
        decrypt_document(a.contents,**{**args,'application_id':'application-b'})
    with pytest.raises(DocumentIntegrityError):
        decrypt_document(a.contents[:-1]+bytes([a.contents[-1]^1]),**args)
    with pytest.raises(DocumentIntegrityError):
        decrypt_document(a.contents,**{**args,'stored_sha256':'0'*64})


def test_key_rotation_keeps_existing_documents_readable(monkeypatch,tmp_path):
    _,keys=configure_keys(monkeypatch,tmp_path,key_ids=('old','new'))
    raw=b'private synthetic document'
    doc_id=str(uuid.uuid4())
    old=encrypt_document(raw,'org','app',doc_id)
    monkeypatch.setenv('AADHARSHILA_DOCUMENT_ACTIVE_KEY_ID','new')
    new=encrypt_document(raw,'org','app',doc_id)
    assert old.key_id=='old' and new.key_id=='new'
    for obj in (old,new):
        assert decrypt_document(obj.contents,storage_format=obj.storage_format,key_id=obj.key_id,
            org_id='org',application_id='app',document_id=doc_id,
            plaintext_sha256=hashlib.sha256(raw).hexdigest(),stored_sha256=obj.storage_sha256)==raw
    # Revoked key material must not silently fall back to the active key.
    Path(os.environ['AADHARSHILA_DOCUMENT_KEYS_PATH']).write_text(json.dumps({'new':keys['new']}))
    with pytest.raises(DocumentKeyUnavailable):
        decrypt_document(old.contents,storage_format=old.storage_format,key_id=old.key_id,
            org_id='org',application_id='app',document_id=doc_id,
            plaintext_sha256=hashlib.sha256(raw).hexdigest(),stored_sha256=old.storage_sha256)


def test_production_never_writes_or_serves_plaintext(monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.delenv('AADHARSHILA_DOCUMENT_ACTIVE_KEY_ID',raising=False)
    with pytest.raises(DocumentKeyUnavailable):
        encrypt_document(b'file','org','application',str(uuid.uuid4()))
    with pytest.raises(DocumentKeyUnavailable):
        decrypt_document(b'file',storage_format=FORMAT_LEGACY,key_id=None,org_id='org',
            application_id='app',document_id=str(uuid.uuid4()),
            plaintext_sha256=hashlib.sha256(b'file').hexdigest())


def test_encrypted_document_upload_download_scoped(monkeypatch,tmp_path,cases,client,login):
    configure_keys(monkeypatch,tmp_path)
    app_id=cases['AS-1001']['id']
    upload=b'SYNTHETIC_ONLY: encrypted-docs-case-42\nmonthly_income: 78321\n'
    headers=login('analyst')
    res=client.post(f'/api/v1/applications/{app_id}/documents',
       files={'file':('synthetic.txt',upload,'text/plain')},headers=headers)
    assert res.status_code==200,res.text
    body=res.json()
    assert body['encrypted_at_rest'] is True and body['verified'] is False
    doc_id=body['id']
    with SessionLocal() as db:
        row=db.get(Document,doc_id)
        assert row.storage_format==FORMAT_ENCRYPTED
        assert row.encryption_key_id=='key-a'
        ciphertext=Path(row.path).read_bytes()
        assert ciphertext.startswith(b'ASHDOC1\x00') and upload not in ciphertext
    fetched=client.get(f'/api/v1/applications/{app_id}/documents/{doc_id}/download')
    assert fetched.status_code==200,fetched.text
    assert fetched.content==upload
    assert fetched.headers.get('cache-control')=='no-store'
    incorrect=client.get(f"/api/v1/applications/{cases['AS-1002']['id']}/documents/{doc_id}/download")
    assert incorrect.status_code==404
    with SessionLocal() as db:
        row=db.get(Document,doc_id)
        path=Path(row.path)
    original=path.read_bytes()
    try:
        path.write_bytes(original[:-1]+bytes([original[-1]^1]))
        altered=client.get(f'/api/v1/applications/{app_id}/documents/{doc_id}/download')
        assert altered.status_code==409
    finally:
        path.write_bytes(original)


def test_sqlite_backup_restore_keeps_ciphertext_and_no_keys(monkeypatch,tmp_path):
    configure_keys(monkeypatch,tmp_path)
    database=tmp_path/'source.db'
    docs=tmp_path/'docs';docs.mkdir()
    doc_id=str(uuid.uuid4());raw=b'private synthetic mortgage evidence'
    stored=encrypt_document(raw,'org','app',doc_id)
    name=storage_filename(doc_id,stored.storage_format,'text/plain')
    (docs/name).write_bytes(stored.contents)
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE applications(id TEXT PRIMARY KEY)')
        db.execute("INSERT INTO applications VALUES('app')")
        db.execute('''CREATE TABLE documents(id TEXT, path TEXT, media_type TEXT, byte_count INTEGER,
                  sha256 TEXT, storage_format TEXT, storage_sha256 TEXT, encryption_key_id TEXT)''')
        db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)',
            (doc_id,str(docs/name),'text/plain',len(raw),hashlib.sha256(raw).hexdigest(),
             stored.storage_format,stored.storage_sha256,stored.key_id))
    archive=tmp_path/'encrypted-backup.zip'
    manifest=backup_sqlite(database,docs,archive)
    assert manifest['format']=='aadharshila-sqlite-backup-v2'
    assert manifest['encryption_keys_included'] is False
    db_restore=tmp_path/'new'/'db.sqlite';docs_restore=tmp_path/'new'/'documents'
    result=restore_sqlite(archive,db_restore,docs_restore)
    assert result['restored_document_count']==1
    assert (docs_restore/name).read_bytes()==stored.contents
    # Decryption keys remain outside the backup; ciphertext remains portable across drives.
    assert decrypt_document((docs_restore/name).read_bytes(),storage_format=stored.storage_format,
        key_id=stored.key_id,org_id='org',application_id='app',document_id=doc_id,
        plaintext_sha256=hashlib.sha256(raw).hexdigest(),stored_sha256=stored.storage_sha256)==raw


def test_key_status_does_not_reveal_secrets(monkeypatch,tmp_path):
    from aadharshila.secure_documents import encryption_key_status
    monkeypatch.delenv('AADHARSHILA_DOCUMENT_ACTIVE_KEY_ID',raising=False)
    assert encryption_key_status()['status']=='MISSING_ACTIVE_KEY'
    file,_=configure_keys(monkeypatch,tmp_path)
    status=encryption_key_status()
    assert status=={'configured':True,'status':'ACTIVE_KEY_AVAILABLE'}
    assert str(file) not in str(status)


@pytest.mark.skipif(os.name!='posix', reason='POSIX filesystem mode validation')
def test_production_rejects_insecure_keyring_permissions(monkeypatch,tmp_path):
    filename,_=configure_keys(monkeypatch,tmp_path)
    filename.chmod(0o644)
    monkeypatch.setenv('APP_ENV','production')
    try:
        with pytest.raises(DocumentKeyUnavailable):
            encrypt_document(b'fake borrower upload','org','app',str(uuid.uuid4()))
        filename.chmod(0o600)
        obj=encrypt_document(b'fake borrower upload','org','app',str(uuid.uuid4()))
        assert obj.storage_format==FORMAT_ENCRYPTED
    finally:
        filename.chmod(0o600)
