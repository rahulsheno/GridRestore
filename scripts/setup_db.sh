#!/usr/bin/env bash
# Rebuild the GridRestore database from scratch: schema, migrations, then demo seed.
# Usage: DATABASE_URL=postgresql://user:pass@localhost:5432/gridrestore ./scripts/setup_db.sh [--reset]
# --reset drops and recreates the public schema first (destroys all data in that database).
set -euo pipefail
: "${DATABASE_URL:?set DATABASE_URL first}"
cd "$(dirname "$0")/.."
PSQL="psql -v ON_ERROR_STOP=1 -q $DATABASE_URL"
if [[ "${1:-}" == "--reset" ]]; then
  $PSQL -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
fi
for f in database/schema.sql database/migrations/002_vectors.sql database/migrations/003_auth.sql \
         database/migrations/004_causes.sql database/migrations/005_integrity_audit_versions.sql database/migrations/006_physics.sql database/migrations/007_physics_extensions.sql; do
  echo "applying $f"
  $PSQL -f "$f" >/dev/null
done
python -m backend.seed_demo
python -m backend.vectors >/dev/null
echo "database ready"
