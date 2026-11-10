"""Authenticated document encryption for Aadharshila's local file backend.

AES-256-GCM with per-object nonces and application-scoped associated data.
Keys are supplied by the hosting institution, not generated or stored by the app.
This is an at-rest control, not a substitute for secure object storage, TLS,
separate key custody, retention governance, or independent security assessment.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

HEADER = b'ASHDOC1\x00'
FORMAT_ENCRYPTED = 'AES256_GCM_V1'
FORMAT_LEGACY = 'PLAINTEXT_DEVELOPMENT'
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


class DocumentKeyUnavailable(RuntimeError):
    """The institution keyring is missing, invalid, or lacks the chosen key."""


class DocumentIntegrityError(ValueError):
    """The ciphertext or its binding to the application has changed."""


@dataclass(frozen=True)
class StoredDocument:
    contents: bytes
    storage_format: str
    storage_sha256: str
    key_id: str | None


def encryption_key_status() -> dict:
    """Return key configuration health without exposing key material or file locations."""
    active = os.getenv('AADHARSHILA_DOCUMENT_ACTIVE_KEY_ID', '')
    if not active:
        return {'configured': False, 'status': 'MISSING_ACTIVE_KEY'}
    try:
        keys = _keys()
        if active not in keys:
            return {'configured': False, 'status': 'ACTIVE_KEY_NOT_FOUND'}
        return {'configured': True, 'status': 'ACTIVE_KEY_AVAILABLE'}
    except DocumentKeyUnavailable:
        return {'configured': False, 'status': 'KEYRING_UNAVAILABLE'}


def _keys() -> dict[str, bytes]:
    key_path = os.getenv('AADHARSHILA_DOCUMENT_KEYS_PATH', '')
    if not key_path:
        raise DocumentKeyUnavailable('Institution document keyring is not configured')
    try:
        source = Path(key_path)
        if os.getenv('APP_ENV', 'development') == 'production' and os.name == 'posix':
            # A vault mount can be read-only; it must not be group/world-accessible.
            if source.stat().st_mode & 0o077:
                raise ValueError('Insecure institution keyring filesystem permissions')
        key_data = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(key_data, dict) or not key_data:
            raise ValueError('Invalid keyring format')
        decoded = {}
        for key_id, material in key_data.items():
            if (not isinstance(key_id, str) or not key_id or len(key_id) > 64
                    or not isinstance(material, str)):
                raise ValueError('Invalid keyring entry')
            raw = base64.b64decode(material, validate=True)
            if len(raw) != 32:
                raise ValueError('AES-256-GCM key must be 32 bytes')
            decoded[key_id] = raw
        return decoded
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise DocumentKeyUnavailable('Institution document keyring is unavailable or invalid') from None


def _aad(org_id: str, application_id: str, document_id: str) -> bytes:
    if not all((org_id, application_id, document_id)):
        raise DocumentIntegrityError('Missing document ownership binding')
    return f'aadharshila:document:v1:{org_id}:{application_id}:{document_id}'.encode('utf-8')


def encrypt_document(raw: bytes, org_id: str, application_id: str, document_id: str) -> StoredDocument:
    """Encrypt when a configured active key exists; only development may use plaintext."""
    if not raw or len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError('Invalid document size')
    active = os.getenv('AADHARSHILA_DOCUMENT_ACTIVE_KEY_ID', '')
    production = os.getenv('APP_ENV', 'development') == 'production'
    if not active:
        if production:
            raise DocumentKeyUnavailable('Production requires document encryption key configuration')
        return StoredDocument(raw, FORMAT_LEGACY, hashlib.sha256(raw).hexdigest(), None)
    keys = _keys()
    if active not in keys:
        raise DocumentKeyUnavailable('Active encryption key is absent from institution keyring')
    nonce = os.urandom(12)
    payload = HEADER + nonce + AESGCM(keys[active]).encrypt(nonce, raw, _aad(org_id, application_id, document_id))
    return StoredDocument(payload, FORMAT_ENCRYPTED, hashlib.sha256(payload).hexdigest(), active)


def decrypt_document(stored: bytes, *, storage_format: str, key_id: str | None,
                     org_id: str, application_id: str, document_id: str,
                     plaintext_sha256: str, stored_sha256: str | None = None) -> bytes:
    """Reject cross-case substitution, tampering, missing keys and production plaintext."""
    if stored_sha256 and hashlib.sha256(stored).hexdigest() != stored_sha256:
        raise DocumentIntegrityError('Stored document checksum mismatch')
    if storage_format == FORMAT_LEGACY:
        if os.getenv('APP_ENV', 'development') == 'production':
            raise DocumentKeyUnavailable('Unencrypted legacy documents require an approved migration')
        raw = stored
    elif storage_format == FORMAT_ENCRYPTED:
        if len(stored) < len(HEADER) + 12 + 16 or not stored.startswith(HEADER) or not key_id:
            raise DocumentIntegrityError('Encrypted document envelope is invalid')
        keys = _keys()
        if key_id not in keys:
            raise DocumentKeyUnavailable('Document decryption key is not available')
        nonce = stored[len(HEADER):len(HEADER) + 12]
        try:
            raw = AESGCM(keys[key_id]).decrypt(nonce, stored[len(HEADER) + 12:],
                                               _aad(org_id, application_id, document_id))
        except InvalidTag:
            raise DocumentIntegrityError('Document integrity or ownership binding failed') from None
    else:
        raise DocumentIntegrityError('Unsupported document storage format')
    if len(raw) > MAX_DOCUMENT_BYTES or hashlib.sha256(raw).hexdigest() != plaintext_sha256:
        raise DocumentIntegrityError('Plaintext document checksum mismatch')
    return raw


def storage_filename(document_id: str, storage_format: str, media_type: str) -> str:
    """Return only a safe, document-ID-derived filename. No user input paths."""
    import uuid
    uuid.UUID(document_id)
    if storage_format == FORMAT_ENCRYPTED:
        return f'{document_id}.bin'
    if storage_format == FORMAT_LEGACY:
        if media_type == 'application/pdf':
            return f'{document_id}.pdf'
        if media_type == 'text/plain':
            return f'{document_id}.txt'
    raise DocumentIntegrityError('Invalid storage format or document media type')
