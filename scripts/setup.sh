#!/usr/bin/env bash
# setup.sh — one-shot bootstrap for the Mini Data Platform
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── prerequisites ─────────────────────────────────────────────────────────────
command -v docker  >/dev/null 2>&1 || error "Docker is not installed."
docker compose version >/dev/null 2>&1 || error "Docker Compose v2 plugin is required."

info "Mini Data Platform — bootstrap starting"

# ── environment ────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    warn "Created .env from .env.example — review credentials before going to production."
fi

# ── build custom images ────────────────────────────────────────────────────────
info "Building Docker images…"
docker compose build

# ── start infrastructure ───────────────────────────────────────────────────────
info "Starting PostgreSQL & MinIO…"
docker compose up -d postgres minio

info "Waiting for PostgreSQL to be ready…"
for i in $(seq 1 30); do
    docker compose exec -T postgres pg_isready -U airflow >/dev/null 2>&1 && break
    printf "  attempt %d/30\r" "$i"; sleep 3
done
echo ""

info "Waiting for MinIO to be ready…"
for i in $(seq 1 30); do
    curl -sf http://localhost:9000/minio/health/live >/dev/null && break
    printf "  attempt %d/30\r" "$i"; sleep 3
done
echo ""

# ── MinIO bucket setup ─────────────────────────────────────────────────────────
info "Creating MinIO buckets…"
docker compose run --rm minio-setup

# ── Airflow init ───────────────────────────────────────────────────────────────
info "Initialising Airflow database & admin user…"
docker compose up airflow-init
info "Airflow initialised."

# ── start remaining services ───────────────────────────────────────────────────
info "Starting Airflow webserver, scheduler and Metabase…"
docker compose up -d airflow-webserver airflow-scheduler metabase

info "Waiting for Metabase to be healthy…"
for i in $(seq 1 40); do
    curl -sf http://localhost:3001/api/health | grep -q '"status":"ok"' && break
    printf "  attempt %d/40\r" "$i"; sleep 10
done
echo ""

info "Provisioning Metabase dashboard and KPIs…"
if command -v python3 >/dev/null 2>&1; then
    python3 -m pip install -q -r scripts/requirements.txt
    python3 scripts/setup_metabase.py
else
    warn "python3 not found — skipping Metabase provisioning."
    warn "Run manually: pip install requests && python3 scripts/setup_metabase.py"
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       Mini Data Platform is running!                 ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Airflow   → http://localhost:8080  (admin / admin)  ║${NC}"
echo -e "${GREEN}║  MinIO     → http://localhost:9001  (minioadmin)     ║${NC}"
echo -e "${GREEN}║  Metabase  → http://localhost:3001  (admin)          ║${NC}"
echo -e "${GREEN}║  PostgreSQL→ localhost:5432         (airflow)        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
info "To inject sample data:"
echo "  cd data_generator && pip install -r requirements.txt && python generate_data.py"
echo ""
info "To stop the platform:"
echo "  docker compose down"
echo ""
info "To wipe all data (volumes):"
echo "  docker compose down -v"
