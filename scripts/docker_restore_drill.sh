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
find "$newdir" -type f -print | head -n 5
printf '%s\n' 'Restore drill completed into isolated database and temp document directory.'
