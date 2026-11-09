#!/usr/bin/env bash
# This is a Compose DEVELOPMENT backup. Protect archives as financial records.
set -euo pipefail
if [[ $# -ne 1 ]]; then echo 'Usage: scripts/docker_backup.sh /secure/backup-directory' >&2; exit 2; fi
cd "$(dirname "${BASH_SOURCE[0]}")/.."
umask 077
out="$(realpath -m "$1")"
if [[ -e "$out" ]]; then echo "Refusing existing destination: $out" >&2; exit 2; fi
mkdir -p "$out"
trap 'if [[ ! -f "$out/verified.marker" ]]; then rm -rf -- "$out"; fi' EXIT
command -v docker >/dev/null || { echo 'Docker is required' >&2; exit 2; }
docker compose exec -T db pg_dump -U aadharshila -d aadharshila --format=custom > "$out/postgres.dump"
# Required document volume and DB are logically separate; stop mutating data for exact consistency.
docker compose exec -T api tar -cz -C /app/var/documents . > "$out/documents.tar.gz"
cat "$out/postgres.dump" | docker compose exec -T db pg_restore --list >/dev/null
tar -tzf "$out/documents.tar.gz" >/dev/null
sha256sum "$out/postgres.dump" "$out/documents.tar.gz" > "$out/SHA256SUMS"
printf '%s\n' "$(date -u +%FT%TZ)" > "$out/verified.marker"
echo "Backup integrity checks complete: $out (restore drill still required)"
