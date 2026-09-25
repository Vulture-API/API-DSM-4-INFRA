#!/usr/bin/env bash
# Sobe o ambiente completo e roda o teste ponta a ponta (Linux, macOS, Git Bash).
#
#   ./scripts/testar.sh            submodules (branch dev)
#   ./scripts/testar.sh --local    pastas irmãs (../API-DSM-4-*)
#   ./scripts/testar.sh --down     derruba e apaga o banco no fim
set -euo pipefail
cd "$(dirname "$0")/.."

DOWN=0
for arg in "$@"; do
  case "$arg" in
    --local) export SERVICES_DIR=.. ;;
    --down) DOWN=1 ;;
    *) echo "opção desconhecida: $arg"; exit 2 ;;
  esac
done

docker info >/dev/null 2>&1 || { echo "Docker não está rodando."; exit 1; }

docker compose up -d --build --wait || { docker compose ps; exit 1; }
docker compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"

status=0
node scripts/e2e.mjs || status=1
[ "$DOWN" = 1 ] && docker compose down -v
exit $status
