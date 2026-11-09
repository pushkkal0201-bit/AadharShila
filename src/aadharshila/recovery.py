"""Portable, integrity-checked *SQLite development* backup and recovery.

This does not replace production PostgreSQL WAL, PITR, object-store versioning
or a documented disaster recovery runbook. Never include real borrower data
in demonstration ZIPs or public artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_name(doc_id: str, media_type: str) -> str:
    import uuid
    uuid.UUID(doc_id)
    suffix = '.pdf' if media_type == 'application/pdf' else '.txt' if media_type == 'text/plain' else None
    if not suffix:
        raise ValueError('Unsupported document media type in database')
    return f'{doc_id}{suffix}'


def inspect_database(filename: Path):
    with sqlite3.connect(str(filename)) as db:
        result = db.execute('PRAGMA integrity_check').fetchone()
        if not result or result[0] != 'ok':
            raise ValueError('Database integrity check failed')
        rows = db.execute('SELECT id, path, media_type, byte_count, sha256 FROM documents').fetchall()
        count = db.execute('SELECT count(*) FROM applications').fetchone()[0]
    return rows, count


def source_document_path(path: str, doc_id: str, media_type: str, root: Path) -> Path:
    source = Path(path)
    root = root.resolve()
    if source.is_absolute():
        candidate = source.resolve()
        if candidate.is_file() and root in candidate.parents:
            return candidate
    else:
        candidate = (root / source).resolve()
        if candidate.is_file() and root in candidate.parents:
            return candidate
    return root / document_name(doc_id, media_type)


def backup_sqlite(database: Path, documents: Path, output: Path) -> dict:
    database, documents, output = Path(database), Path(documents), Path(output)
    if not database.is_file():
        raise FileNotFoundError('SQLite database does not exist')
    if output.exists():
        raise FileExistsError('Refusing to overwrite an existing backup')
    with tempfile.TemporaryDirectory(prefix='aadharshila-backup-') as temp:
        snapshot = Path(temp) / 'snapshot.sqlite'
        with sqlite3.connect(str(database)) as source, sqlite3.connect(str(snapshot)) as target:
            source.backup(target)
        rows, applications = inspect_database(snapshot)
        db_bytes = snapshot.read_bytes()
        manifest = {'format': 'aadharshila-sqlite-backup-v1',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'database_sha256': digest(db_bytes), 'application_count': applications,
                    'documents': [], 'scope': 'DEVELOPMENT_SQLITE_ONLY'}
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('database.sqlite', db_bytes)
                for doc_id, stored_path, media_type, count, expected in rows:
                    filename = document_name(doc_id, media_type)
                    source_path = source_document_path(stored_path, doc_id, media_type, documents)
                    raw = source_path.read_bytes()
                    if len(raw) != count or digest(raw) != expected:
                        raise ValueError(f'Invalid stored document: {doc_id}')
                    archive.writestr('documents/' + filename, raw)
                    manifest['documents'].append({'name': filename, 'byte_count': count, 'sha256': expected})
                archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True, indent=2))
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    return manifest


def validate_archive(archive: Path) -> tuple[dict, bytes, dict[str, bytes]]:
    with zipfile.ZipFile(archive) as package:
        files = package.infolist()
        if sum(member.file_size for member in files) > MAX_ARCHIVE_BYTES:
            raise ValueError('Archive exceeds 512 MiB uncompressed limit')
        names = {member.filename for member in files}
        if 'manifest.json' not in names or 'database.sqlite' not in names:
            raise ValueError('Not an Aadharshila SQLite backup')
        manifest = json.loads(package.read('manifest.json'))
        if manifest.get('format') != 'aadharshila-sqlite-backup-v1':
            raise ValueError('Unknown backup format')
        db_bytes = package.read('database.sqlite')
        if digest(db_bytes) != manifest.get('database_sha256'):
            raise ValueError('Database checksum does not match manifest')
        checked = {}
        for doc in manifest['documents']:
            name = doc['name']
            if Path(name).name != name or not name.endswith(('.pdf', '.txt')):
                raise ValueError('Invalid document archive path')
            raw = package.read('documents/' + name)
            if digest(raw) != doc['sha256'] or len(raw) != doc['byte_count']:
                raise ValueError('Document checksum does not match manifest')
            checked[name] = raw
        if names != ({'manifest.json', 'database.sqlite'} | {'documents/' + n for n in checked}):
            raise ValueError('Unexpected archive members')
    return manifest, db_bytes, checked


def restore_sqlite(archive: Path, database: Path, documents: Path) -> dict:
    archive, database, documents = Path(archive), Path(database), Path(documents)
    if database.exists() or documents.exists():
        raise FileExistsError('Restore destinations must not exist; refusing to overwrite data')
    manifest, db_bytes, document_bytes = validate_archive(archive)
    database.parent.mkdir(parents=True, exist_ok=True)
    documents.parent.mkdir(parents=True, exist_ok=True)
    temp_db = database.with_name(database.name + '.restoring')
    temp_docs = documents.with_name(documents.name + '.restoring')
    if temp_db.exists() or temp_docs.exists():
        raise FileExistsError('Stale restore staging files exist')
    try:
        temp_db.write_bytes(db_bytes)
        temp_docs.mkdir()
        for name, raw in document_bytes.items():
            (temp_docs / name).write_bytes(raw)
        rows, count = inspect_database(temp_db)
        if count != manifest['application_count'] or len(rows) != len(document_bytes):
            raise ValueError('Restored database does not match manifest inventory')
        for doc_id, _, media_type, byte_count, sha in rows:
            name = document_name(doc_id, media_type)
            raw = (temp_docs / name).read_bytes()
            if len(raw) != byte_count or digest(raw) != sha:
                raise ValueError('Restored document failed database comparison')
        os.replace(temp_db, database)
        os.replace(temp_docs, documents)
    finally:
        temp_db.unlink(missing_ok=True)
        if temp_docs.exists():
            shutil.rmtree(temp_docs)
    return {'restored_application_count': count, 'restored_document_count': len(document_bytes),
            'database': str(database), 'documents': str(documents), 'integrity': 'VERIFIED_LOCALLY'}


def main():
    parser = argparse.ArgumentParser(description='Aadharshila development SQLite backup/restore')
    command = parser.add_subparsers(dest='command', required=True)
    backup = command.add_parser('backup')
    backup.add_argument('--database', type=Path, required=True)
    backup.add_argument('--documents', type=Path, required=True)
    backup.add_argument('--output', type=Path, required=True)
    restore = command.add_parser('restore')
    restore.add_argument('--archive', type=Path, required=True)
    restore.add_argument('--database', type=Path, required=True)
    restore.add_argument('--documents', type=Path, required=True)
    check = command.add_parser('verify')
    check.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'backup': result = backup_sqlite(args.database, args.documents, args.output)
    elif args.command == 'restore': result = restore_sqlite(args.archive, args.database, args.documents)
    else:
        result = {'manifest': validate_archive(args.archive)[0], 'status': 'CHECKSUMS_VERIFIED'}
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
