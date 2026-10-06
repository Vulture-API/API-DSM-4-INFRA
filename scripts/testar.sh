#!/usr/bin/env bash
# Sobe o ambiente completo e roda o teste ponta a ponta (Linux, macOS, Git Bash).
#
#   ./scripts/testar.sh            commits fixados dos submodules
#   ./scripts/testar.sh --local    pastas irmãs (../API-DSM-4-*)
#   ./scripts/testar.sh --test-db usa PostgreSQL descartável
#   ./scripts/testar.sh --down     derruba e apaga o banco no fim
set -euo pipefail
cd "$(dirname "$0")/.."

DOWN=0
COMPOSE_ARGS=(-f docker-compose.yml)
for arg in "$@"; do
  case "$arg" in
    --local) export SERVICES_DIR=.. ;;
    --down) DOWN=1 ;;
    --test-db) COMPOSE_ARGS+=(-f docker-compose.test.yml) ;;
    *) echo "opção desconhecida: $arg"; exit 2 ;;
  esac
done

docker info >/dev/null 2>&1 || { echo "Docker não está rodando."; exit 1; }

docker compose "${COMPOSE_ARGS[@]}" up -d --build --wait || { docker compose "${COMPOSE_ARGS[@]}" ps; exit 1; }
docker compose "${COMPOSE_ARGS[@]}" ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"

status=0
node scripts/e2e.mjs || status=1
[ "$DOWN" = 1 ] && docker compose "${COMPOSE_ARGS[@]}" down -v
exit $status
