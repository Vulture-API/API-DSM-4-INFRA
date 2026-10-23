# Banco interno obrigatório; -TestDatabase mantido por compatibilidade.
param([switch]$Local, [switch]$Down, [switch]$TestDatabase)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($Local) { $env:SERVICES_DIR = '..' }
if (-not $env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME = 'vulture-qa-' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
if ($env:COMPOSE_PROJECT_NAME -notlike 'vulture-qa-*') { throw 'Projeto deve começar com vulture-qa-' }
if (-not $env:PERSIST_SOURCE_ID) { $env:PERSIST_SOURCE_ID = $env:COMPOSE_PROJECT_NAME + '-redis-history' }
$env:DATABASE_URL = ''
$composeArgs = @('--env-file', 'NUL', '-p', $env:COMPOSE_PROJECT_NAME, '-f', 'docker-compose.yml', '-f', 'docker-compose.test.yml')
try {
    docker compose @composeArgs up -d --build --wait --wait-timeout 180
    if ($LASTEXITCODE) { throw 'Falha ao subir QA' }
    $env:BACKEND_URL = 'http://localhost:' + $(if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { '3000' })
    $env:FRONTEND_URL = 'http://localhost:' + $(if ($env:PROXY_PORT) { $env:PROXY_PORT } else { '8080' })
    node scripts/e2e.mjs
    if ($LASTEXITCODE) { throw 'E2E reprovado' }
} finally {
    if ($Down) { docker compose @composeArgs down -v }
}
