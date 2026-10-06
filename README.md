# AgriTech — INFRA

Executa a plataforma com um backend Node monolítico, frontend separado, recepção Python, MQTT e Redis. O PostgreSQL principal é externo. Para testes, existe um overlay com banco descartável.

Os repositórios ficam em `services/` como submódulos com commits fixados: BACKEND, FRONTEND, RECEPCAO-DADOS e BANCO. Os quatro submódulos Node antigos foram substituídos pelo BACKEND; seus históricos continuam nos repositórios originais.

## Executar com banco externo

Requisitos: Docker com Compose, Git e Node 24 para scripts/testes.

```bash
git clone --recurse-submodules https://github.com/Vulture-API/API-DSM-4-INFRA.git
cd API-DSM-4-INFRA
cp .env.example .env
# Configure DATABASE_URL em .env com o PostgreSQL já provisionado.
docker compose up -d --build --wait
```

Schema e migrations continuam no API-DSM-4-BANCO. O Compose principal não cria PostgreSQL nem aplica seeds/migrations no banco externo.

| Serviço | Porta no host | Responsabilidade |
| --- | --- | --- |
| `backend` | 3000, somente localhost | Todas as APIs e motor de regras |
| `frontend` | 3010, somente localhost | Portal Next.js |
| `nginx` | 8080, somente localhost | Proxy do portal |
| `mosquitto` | 1883 | Recepção MQTT |
| `redis` | interna | Stream de telemetria |
| `recepcao` | — | MQTT → Redis, Python |
| `recepcao-persist` | — | Redis → PostgreSQL, Python |
| `simulador` | — | Consulta cadastros e publica MQTT |

Acesse o portal em `http://localhost:8080` ou `http://localhost:3010`. A API está em `http://localhost:3000`. `BACKEND_PORT` e `MQTT_PORT` podem ser definidos no `.env`.

Os quatro build args existentes do frontend apontam para `http://backend:3000`. As rotas relativas e os contratos foram preservados; não é necessário alterar seu código. Os destinos são gravados pelo Next.js durante o build, portanto atualizações exigem recompilar o frontend.

## Validar sem usar o banco externo

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build --wait
FRONTEND_URL=http://localhost:8080 node scripts/e2e.mjs
# Remove somente o ambiente descartável e seus volumes.
docker compose -f docker-compose.yml -f docker-compose.test.yml down -v
```

Esse ambiente se chama `vulture-test`, usa PostgreSQL 16 e aplica `schema-neon.sql` e `seed-dev.sql` em um volume próprio. Não usa a `DATABASE_URL` do `.env`. Não execute simultaneamente com o ambiente principal nas mesmas portas; pare o principal antes do teste ou ajuste as portas.

O PostgreSQL de testes é exposto em `127.0.0.1:5433` (`TEST_POSTGRES_PORT`). Para executar as integrações do backend enquanto esse banco está ativo:

```bash
cd services/API-DSM-4-BACKEND
npm ci
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/agritech_test npm run test:coverage
```

Os testes SQL usam schemas temporários próprios. O seed de desenvolvimento é mínimo: o simulador pode publicar zero leituras até existirem estações e sensores cadastrados; o E2E cria seu próprio cadastro completo e remove os dados ao final.

### Scripts auxiliares

Linux, macOS e Git Bash:

```bash
./scripts/testar.sh --test-db --down
```

PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\testar.ps1 -TestDatabase -Down
```

Sem `--test-db`/`-TestDatabase`, os scripts usam o banco externo configurado. O E2E cria e remove registros; prefira o ambiente descartável. `--local`/`-Local` usa `SERVICES_DIR=..`, exigindo os quatro repositórios em pastas irmãs. `-Unit` também executa as verificações do BACKEND e do frontend.

## Fluxo de dados

```mermaid
flowchart LR
  Estacao[Estação / datalogger] --> MQTT[Mosquitto]
  MQTT --> Ingest[Recepção Python]
  Ingest --> Redis[(Redis Stream)]
  Redis --> Persist[Persistidor Python]
  Persist --> PG[(PostgreSQL)]
  Monolito[Backend Node: usuários, sensores, estações e alertas] --> PG
  Front[Frontend Next.js] --> Monolito
  Nginx[Nginx] --> Front
  Simulador[Simulador] --> MQTT
  Simulador --> Monolito
```

Tópico MQTT: `estacoes/<MAC>/dados`.

```json
{"estacao_id":"AA:BB:CC:DD:EE:01","unix_time":1760000000,"temp":23.5,"umid":61}
```

`estacao_id` identifica o MAC cadastrado. As chaves de medições usam os `local_identifier` dos sensores. O Python conserva o protocolo existente; o monolito consulta as leituras persistidas e processa as regras de alerta.

## CI e teste ponta a ponta

O workflow E2E usa exatamente os commits fixados nos gitlinks, sem `git submodule update --remote`. Ele valida o simulador, compila as imagens e executa o ambiente completo com banco descartável. Roda em PR, manualmente e nos dias úteis às 07h de Brasília.

O E2E verifica cadastros, conflitos, paginação, publicação MQTT, status Online, disparo/reconhecimento de alertas, páginas e proxies do frontend. `BACKEND_URL` configura todas as chamadas de API; `FRONTEND_URL`, `MQTT_HOST`, `MQTT_PORT` e `E2E_TIMEOUT_MS` permanecem disponíveis.

A qualidade do BACKEND é validada em seu próprio CI: lint, formatação, tipos, testes SQL, cobertura mínima de 80% de linhas, auditoria crítica e build Docker. Nenhum workflow publica imagens ou faz deploy automático.

## Atualizar e implantar manualmente

Publique primeiro os commits do BACKEND, depois a revisão do INFRA que referencia esses commits. Até essa publicação, os novos gitlinks só podem ser resolvidos nos checkouts locais que possuem os objetos Git.

Na primeira troca de arquitetura, use o checkout antigo para parar as APIs antigas, especialmente `api-alertas`, antes de habilitar o motor do monolito. Pare o Compose antigo sem `-v`, preservando o volume Redis. Em seguida, atualize o INFRA e seus submódulos:

```bash
git pull --ff-only
git submodule update --init --recursive
docker compose up -d --build --remove-orphans --wait
```

Não use `--remote` no deploy: a revisão do INFRA fixa as versões compatíveis. Confira `docker compose ps`, `/health`, o portal e os logs do backend. O motor fica habilitado no Compose; ele lê o mesmo checkpoint PostgreSQL existente.

### Reversão

Pare o monolito com `docker compose down`, sem `-v`. Restaure a revisão anterior do INFRA, execute `git submodule update --init --recursive` e suba o Compose daquela revisão. Como a migração não altera schema nem protocolo MQTT, o banco e o Redis permanecem compatíveis. Garanta que somente um motor de regras esteja ativo durante a transição.

## Comandos úteis

| Comando | Uso |
| --- | --- |
| `docker compose ps` | Estado dos serviços |
| `docker compose logs -f backend` | API e motor de regras |
| `docker compose logs -f recepcao-persist` | Persistência da telemetria |
| `docker compose up -d --build backend frontend --wait` | Recompilar API e rewrites do portal |
| `docker compose down` | Parar ambiente principal e manter Redis |

O Mosquitto desta configuração é o broker de desenvolvimento sem autenticação. PostgreSQL de testes e API ficam acessíveis somente em localhost. O healthcheck Nginx usa IPv4 explícito, compatível com seu listener. Não aplique as migrations de particionamento no banco externo como parte desta migração.

O inventário, o diagrama detalhado e as evidências estão em `services/API-DSM-4-BACKEND/docs/`. A documentação local para Confluence fica em `confluence/` no checkout principal do BACKEND e está fora do Git; publicação e aprovação do time continuam pendentes.
