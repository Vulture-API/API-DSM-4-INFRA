#!/usr/bin/env bash
# PostgreSQL interno sempre. --local usa checkouts irmãos; --down limpa somente QA.
set -euo pipefail
cd "$(dirname "$0")/.."
DOWN=0
for arg in "$@"; do
  case "$arg" in
    --local) export SERVICES_DIR=.. ;;
    --down) DOWN=1 ;;
    --test-db) ;; # compatibilidade: agora é o padrão obrigatório
    *) echo "opção desconhecida: $arg"; exit 2 ;;
  esac
done
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-vulture-qa-$(date +%s)-$$}"
[[ "$COMPOSE_PROJECT_NAME" == vulture-qa-* ]] || { echo 'Projeto deve começar com vulture-qa-'; exit 2; }
export PERSIST_SOURCE_ID="${PERSIST_SOURCE_ID:-$COMPOSE_PROJECT_NAME-redis-history}"
export DATABASE_URL=''
export JWT_SECRET="${JWT_SECRET:-$(node -e 'console.log(require("crypto").randomBytes(32).toString("hex"))')}"
args=(--env-file /dev/null -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml -f docker-compose.test.yml)
cleanup() { if [[ "$DOWN" == 1 ]]; then docker compose "${args[@]}" down -v; fi; }
trap cleanup EXIT
docker info >/dev/null
docker compose "${args[@]}" up -d --build --wait --wait-timeout 180
BACKEND_URL="http://localhost:${BACKEND_PORT:-3000}" FRONTEND_URL="http://localhost:${PROXY_PORT:-8080}" node scripts/e2e.mjs
