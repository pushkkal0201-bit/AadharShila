# Document encryption and recovery boundary

This stage adds **AES-256-GCM for newly uploaded document bytes** at the existing local-storage layer. It is a technical security control, **not** evidence of lender authorization, independent security certification, regulator approval, an HSM, an encrypted object-storage deployment, or comprehensive protection of every database field.

## What is protected

- A unique 96-bit random nonce per upload, authenticated AES-256-GCM encryption, and explicit key ID for rotation.
- Additional authenticated data binds the ciphertext to the lender organization, application ID and document ID. Substituting ciphertext across applications is rejected.
- Database fields retain the plaintext SHA-256 and original length; the stored-ciphertext SHA-256 is separate. Neither checksum authenticates the source of a borrower's uploaded document.
- Permission-scoped downloads verify ciphertext SHA-256, the AEAD tag, ownership binding and decrypted plaintext hash before returning bytes with `Cache-Control: no-store`.
- File updates use a same-directory temporary file, restricted mode on POSIX and atomic replacement; Windows paths and drive letters are supported.

## Configuration

Provision the **keyring outside GitHub, the app container image and public backups**. The file format is a JSON mapping of opaque key IDs to RFC4648 base64-encoded **32-byte** keys. A lender-approved key management process must generate, distribute, rotate, revoke and recover keys. Never use the example text as key material.

```text
AADHARSHILA_DOCUMENT_KEYS_PATH=D:\\Security\\Aadharshila\\document-keys.json
AADHARSHILA_DOCUMENT_ACTIVE_KEY_ID=lender-key-2026
```

On Linux, mount the keyring from a secret manager using owner-only file permissions (e.g. `0600`) into a restricted path (e.g. `/run/secrets/document-keys.json`). On Windows, enforce equivalent NTFS ACLs via the hosting administrator. No key or keyring path is returned by the readiness endpoint. Readiness includes `document_storage.status`; production uploads fail closed without a configured active key. Existing plaintext development uploads are **not served in production**; do not switch a live environment on before planning an approved re-encryption migration.

## Key rotation and backups

New uploads use `AADHARSHILA_DOCUMENT_ACTIVE_KEY_ID`. Old ciphertexts remain bound to their original key IDs, so previous keys must be retained in secure custody until all corresponding documents are lawfully re-encrypted or purged. Removing an old key prevents decryption; silently trying the current active key is prohibited. The SQLite development backup has a v2 archive format for encrypted documents; it verifies and restores **ciphertext**, and does **not** contain encryption keys. Restores across Windows D: drive paths resolve by document UUID and canonical storage filename. The restored document still needs the original institution keyring.

Production PostgreSQL backups and encrypted object storage require their own validated retention, PITR, recovery and independent permission controls. The current docker-compose test demonstrates development container recovery, not enterprise disaster recovery.

## Explicit limitations

- **Legacy files are unencrypted.** They remain readable only in development; real migration of legacy documents and deletion of residual plaintext copies requires separately approved engineering and evidence of verified backups.
- **Extracted metadata in the database is not independently encrypted by this module.** In production, raw OCR text and document-derived financial fields are not persisted by this stage. A production lender needs encrypted structured-data storage, restricted search indexes, deletion policy and external audit.
- No integrated key vault, HSM, transparent key rotation, retention enforcement, legal hold, issuer signature validation, vulnerability audit, secure production deployment, or external provider authorization is claimed.
- Actual ClamAV scanning is still a prerequisite for production uploads. A missing/unsupported scanner does not become a pass because encryption is enabled.

## Verification

Run `python -m pytest -q tests/test_encrypted_document_storage.py`, then the full suite, and `python -m alembic upgrade head` on disposable staging data. Tests cover AES-GCM binding and tampering, different ciphertext nonces, key rotation behavior, real API upload/download, tenant boundaries, production plaintext refusal, development SQLite ciphertext backup and restore, and a fresh migration.

### Process-isolated extraction checkpoint

PDF extraction has moved from the API process to a dedicated, resource-bounded Python subprocess (`document_isolation.py` / `isolated_document_worker.py`). The subprocess consumes untrusted PDF bytes on stdin, has bounded stdout and completion time, and receives a minimal environment without provider tokens. The caller marks extracted content **unverified** regardless of the parser result. On Windows, process-level resource limits require operating-system/container enforcement; POSIX CPU/address-space limits are applied in the child.

This implementation is **not a comprehensive parser sandbox**. For actual lender data, add process/container account separation, seccomp/AppArmor, no-network egress and separately backed restricted storage, and obtain a qualified external security review. Production scanning and encryption remain mandatory and fail closed when unavailable.
