# Sobe o ambiente completo e roda o teste ponta a ponta.
#
#   powershell -ExecutionPolicy Bypass -File scripts\testar.ps1            # submodules (branch dev)
#   powershell -ExecutionPolicy Bypass -File scripts\testar.ps1 -Local     # pastas irmãs (..\API-DSM-4-*)
#   powershell -ExecutionPolicy Bypass -File scripts\testar.ps1 -Unit      # + lint/testes/build de cada repo
#   powershell -ExecutionPolicy Bypass -File scripts\testar.ps1 -Down      # derruba e apaga o banco no fim
#
# Requer Docker Desktop aberto e Node 20+ (só para o e2e.mjs e o -Unit).
param([switch]$Local, [switch]$Unit, [switch]$Down)

$ErrorActionPreference = "Stop"
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz

if ($Local) { $env:SERVICES_DIR = ".." }
$servicos = if ($env:SERVICES_DIR) { Join-Path $raiz $env:SERVICES_DIR } else { Join-Path $raiz "services" }
$servicos = (Resolve-Path $servicos).Path
Write-Host "Código dos serviços: $servicos" -ForegroundColor Cyan

$repos = "API-DSM-4-USUARIO", "API-DSM-4-PARAMETROS", "API-DSM-4-ESTACOES", "API-DSM-4-ALERTAS",
         "API-DSM-4-RECEPCAO-DADOS", "API-DSM-4-BANCO", "API-DSM-4-FRONTEND"
foreach ($r in $repos) {
  if (-not (Test-Path (Join-Path $servicos $r))) {
    Write-Host "Falta $r em $servicos." -ForegroundColor Red
    if (-not $Local) { Write-Host "Rode: git submodule update --init --remote" }
    exit 1
  }
}

docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "Docker não está rodando. Abra o Docker Desktop." -ForegroundColor Red; exit 1 }

$falhas = 0
function Rodar($titulo, $comando) {
  $saida = cmd /c "$comando 2>&1"
  if ($LASTEXITCODE -eq 0) { Write-Host ("  ok     " + $titulo) -ForegroundColor Green }
  else {
    Write-Host ("  FALHA  " + $titulo) -ForegroundColor Red
    $saida | Select-Object -Last 25 | ForEach-Object { Write-Host ("         " + $_) }
    $script:falhas++
  }
  return $saida
}

if ($Unit) {
  Write-Host "`nTestes de cada repositório (como no CI)" -ForegroundColor Cyan
  foreach ($r in "API-DSM-4-USUARIO", "API-DSM-4-PARAMETROS", "API-DSM-4-ESTACOES", "API-DSM-4-ALERTAS") {
    Write-Host $r
    Push-Location (Join-Path $servicos $r)
    if (-not (Test-Path node_modules)) { Rodar "npm ci" "npm ci --no-audit --no-fund" | Out-Null }
    foreach ($s in "lint", "format", "typecheck", "test:coverage", "build") { Rodar $s "npm run -s $s" | Out-Null }
    Pop-Location
  }
  Write-Host "API-DSM-4-FRONTEND"
  Push-Location (Join-Path $servicos "API-DSM-4-FRONTEND\app")
  if (-not (Test-Path node_modules)) { Rodar "npm ci" "npm ci --no-audit --no-fund" | Out-Null }
  foreach ($s in "lint", "test", "build") { Rodar $s "npm run -s $s" | Out-Null }
  Pop-Location
}

Write-Host "`nSubindo o ambiente (primeira vez demora: baixa imagens e compila)" -ForegroundColor Cyan
docker compose up -d --build --wait
if ($LASTEXITCODE -ne 0) {
  docker compose ps
  Write-Host "Falha ao subir. Logs: docker compose logs <servico>" -ForegroundColor Red
  exit 1
}
docker compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"

Write-Host "`nTeste ponta a ponta" -ForegroundColor Cyan
node scripts/e2e.mjs
if ($LASTEXITCODE -ne 0) { $falhas++ }

if ($Down) { docker compose down -v }

Write-Host ""
if ($falhas -eq 0) {
  Write-Host "TUDO OK" -ForegroundColor Green
  Write-Host "Front: http://localhost:3010"
  exit 0
}
Write-Host "$falhas FALHA(S)" -ForegroundColor Red
exit 1
