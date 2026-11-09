# Backup and recovery exercises

## Exercised SQLite development recovery

On 10 November 2026, `python -m aadharshila.recovery` created a backup from the locally seeded `aadharshila.db` and restored it to a different directory. `PRAGMA integrity_check` succeeded, and application counts matched: **16 source / 16 restored**. There were **no uploaded documents** in the primary seed database. A separate automated recovery test with one uploaded synthetic text document passed content-hash comparison, cross-directory restoration, overwrite refusal and tamper rejection.

Run a backup on Windows PowerShell from the project folder (including `D:\`):

```powershell
.\.venv\Scripts\python.exe -m aadharshila.recovery backup --database .\aadharshila.db --documents .\var\documents --output .\private-backups\demo-1.zip
.\.venv\Scripts\python.exe -m aadharshila.recovery verify --archive .\private-backups\demo-1.zip
.\.venv\Scripts\python.exe -m aadharshila.recovery restore --archive .\private-backups\demo-1.zip --database .\recovered\aadharshila.db --documents .\recovered\documents
```

Restoration never overwrites an existing database or document directory. Update `DATABASE_URL` and `UPLOAD_DIR` to reference the recovered location before running it. Preserve backups privately; application data can contain sensitive financial information.

## PostgreSQL Compose development backup and isolated restore

Commands are supplied and configured as an automated CI job. They require Docker; **Docker could not be executed in the authoring container**. Use:

```bash
bash scripts/docker_backup.sh /private/new-backup-dir
bash scripts/docker_restore_drill.sh /private/new-backup-dir
```

The scripts capture a PostgreSQL custom-format dump and compressed document directory, verify checksums, then restore into a newly created disposable database and a temporary document directory without altering the running application database. A live database and document volume are not transactionally synchronized: quiesce writes before taking a cross-store-consistent backup. A real deployment additionally needs encrypted offsite retention, PostgreSQL WAL/PITR, storage replication, RPO/RTO exercises, key recovery, failover testing and security audit trails.
