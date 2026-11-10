#!/usr/bin/env bash
# Restores into a disposable PostgreSQL database; never overwrites a live DB.
set -euo pipefail
if [[ $# -ne 1 ]]; then echo 'Usage: scripts/docker_restore_drill.sh /backup-directory' >&2; exit 2; fi
cd "$(dirname "${BASH_SOURCE[0]}")/.."
backup="$(realpath "$1")"
(cd "$backup" && sha256sum -c SHA256SUMS)
trial="recovery_$(date +%s)_$RANDOM"
[[ "$trial" =~ ^[a-z0-9_]+$ ]] || exit 2
cleanup(){ docker compose exec -T db dropdb -U aadharshila --if-exists "$trial" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker compose exec -T db createdb -U aadharshila "$trial"
cat "$backup/postgres.dump" | docker compose exec -T db pg_restore -U aadharshila --no-owner -d "$trial"
actual="$(docker compose exec -T db psql -U aadharshila -d "$trial" -At -c 'SELECT count(*) FROM applications')"
echo "Restored development database has $actual applications"
# Ensure the archive is extractable without ever merging data into the running volume.
newdir="$(mktemp -d)"
trap 'rm -rf "$newdir"; cleanup' EXIT
tar -xzf "$backup/documents.tar.gz" -C "$newdir"
# Reconcile document metadata in the *restored* database against the restored files.
# This detects missing, swapped and corrupt ciphertext without decrypting it.
checked=0
while IFS=$'\t' read -r object_path expected_hash; do
  [[ -z "$object_path" ]] && continue
  filename="$(basename -- "$object_path")"
  if [[ ! "$filename" =~ ^[0-9a-f-]{36}\.(txt|pdf|bin)$ ]]; then
    echo "Unexpected restored document filename" >&2;exit 1
  fi
  [[ -f "$newdir/$filename" ]] || { echo "Restored document missing" >&2;exit 1; }
  actual_hash="$(sha256sum "$newdir/$filename" | cut -d' ' -f1)"
  [[ "$actual_hash" == "$expected_hash" ]] || { echo "Restored document integrity mismatch" >&2;exit 1; }
  checked=$((checked+1))
done < <(docker compose exec -T db psql -U aadharshila -d "$trial" -At -F $'\t' -c 'SELECT path,COALESCE(storage_sha256,sha256) FROM documents ORDER BY id')
reported="$(docker compose exec -T db psql -U aadharshila -d "$trial" -At -c 'SELECT count(*) FROM documents')"
[[ "$checked" == "$reported" ]] || { echo "Document restore count mismatch" >&2;exit 1; }
echo "Restored and hash-verified $checked document objects"
printf '%s\n' 'Restore drill completed into isolated database and temp document directory.'
