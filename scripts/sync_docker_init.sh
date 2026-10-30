#!/usr/bin/env bash
# Copy the canonical SQL files into docker/init in the order PostgreSQL's init directory runs them.
set -euo pipefail
cd "$(dirname "$0")/.."
cp database/schema.sql docker/init/01-schema.sql
cp database/migrations/002_vectors.sql docker/init/02-vectors.sql
cp database/migrations/003_auth.sql docker/init/03-auth.sql
cp database/migrations/004_causes.sql docker/init/04-causes.sql
cp database/migrations/005_integrity_audit_versions.sql docker/init/05-integrity-audit-versions.sql
cp database/migrations/006_physics.sql docker/init/06-physics.sql
cp database/migrations/007_physics_extensions.sql docker/init/07-physics-extensions.sql
cp database/migrations/008_auth_hardening.sql docker/init/08-auth-hardening.sql
cp database/migrations/009_embeddings_st.sql docker/init/09-embeddings-st.sql
cp database/migrations/010_element_physics_map.sql docker/init/10-element-physics-map.sql
echo "docker/init synced"
