# AgriTech — INFRA

Ambiente integrado com backend Node, frontend Next.js, recepção MQTT/Redis e
tratamento Python independente. Documentação oficial no [Confluence](https://vultureapi.atlassian.net/wiki/spaces/V/pages/46333954).

Requisitos: Docker Compose v2, Git, Node 24 e Python 3.12 para operação/QA.

```bash
git clone --recurse-submodules https://github.com/Vulture-API/API-DSM-4-INFRA.git
cd API-DSM-4-INFRA
```

O ambiente principal usa PostgreSQL externo previamente migrado. Configure `.env`
com DATABASE_URL e PERSIST_SOURCE_ID. A ativação controlada abaixo substitui o
consumidor antigo. Esta entrega não autoriza implantação ou migrations externas.

| Serviço | Porta local padrão | Responsabilidade |
| --- | --- | --- |
| backend | 3000 | APIs, cadastros, consultas, motor de regras |
| frontend / nginx | 3010 / 8080 | Portal / proxy |
| mosquitto | 1883 | MQTT de desenvolvimento sem autenticação |
| redis | interna | AOF e Stream |
| recepcao | nenhuma | MQTT → Redis |
| persistencia | nenhuma | Redis → PostgreSQL |
| simulador (perfil demo) | nenhuma | Publicação automática optativa |

## SCRUM-531 — Topologia de telemetria

Estações → MQTT QoS 1 → `recepcao` (Python, MQTT/Redis) → `telemetry:ingest`
→ `persistencia` (Python, Redis/PostgreSQL) → leituras/ocorrências/quarentena.
O BACKEND mantém APIs, cadastros e consultas. O tratamento tem imagem própria,
comando `consume`, healthcheck `python -m station_persist status` e usuário sem root.
Não há endpoint HTTP nos serviços Python. O código legado permanece na recepção
até SCRUM-532, mas `recepcao-persist` saiu do Compose principal.

Os submódulos são fixados em commits. BACKEND/FRONTEND continuam nas revisões da
base `cloudflare`; atualizações locais preparadas desses serviços não fazem parte
desta entrega. CI nunca usa `submodule update --remote`. O novo submódulo usa HTTPS.

### Configuração e ambiente descartável

Copie `.env.example` para desenvolvimento. Defina `PERSIST_SOURCE_ID` como identidade
estável da história Redis; nunca a gere a cada reinício do ambiente principal.
`TELEMETRY_STREAM` e `PERSIST_GROUP` devem preservar Stream/grupo anteriores.
O consumidor gera identidade distinta por container/PID; ao executar manualmente
com `-e PERSIST_CONSUMER=...`, use uma identidade exclusiva (lease impede duplicação).
`PERSIST_LEGACY_MAX_ID` é opcional e explícito: nunca inferir o corte de eventos
normalizados. Retenção fica desabilitada; antes de ativá-la, inclua o grupo configurado
e os demais consumidores em `INGEST_RETENTION_REQUIRED_GROUPS`.
Redis conserva AOF/volume e usa `noeviction`. Mosquitto local usa `persistence false`:
a garantia não inclui reinício durável do broker nem QoS 0.

```bash
./scripts/testar.sh --down           # banco interno, projeto exclusivo, cleanup restrito
./scripts/testar.sh --local --down   # checkouts irmãos, inclusive PERSISTENCIA-DADOS
# Windows: ./scripts/testar.ps1 -Down [-Local]
```

QA ignora `.env` e substitui DATABASE_URL por banco interno. Portas BACKEND_PORT,
FRONTEND_PORT, PROXY_PORT, MQTT_PORT e TEST_POSTGRES_PORT são configuráveis e publicadas
somente em localhost. O simulador é optativo: `docker compose --profile demo up -d`.
O PostgreSQL descartável aplica schema, 015, as duas 016, 017, 018 e seed, nessa ordem.
Healthcheck TCP só permite dependentes após terminar a inicialização. Recepção não
aguarda PostgreSQL e não recebe configuração de banco. Use outro projeto QA para
reexecutar sobre banco novo; não aplique migrations externas com estes scripts.

### Pré-verificação, ativação e pausa

Os comandos abaixo atuam no projeto indicado, usam lock local por projeto e geram
inventário sem credenciais (revisões, imagens, volumes, Stream/grupo/PEL). Um único
operador deve coordenar o projeto; não execute `compose up` manualmente em paralelo
à troca. O lock não coordena operadores em outros hosts. Migrations são pré-requisito
validado pelo pacote e devem ser preparadas fora desta entrega, nunca automaticamente.

```bash
python3 scripts/telemetry.py preflight --project vulture --evidence reports/preflight.json
python3 scripts/telemetry.py activate  --project vulture --evidence reports/activation.json
python3 scripts/telemetry.py pause     --project vulture --evidence reports/pause.json
# Em QA, acrescentar --test e usar --project vulture-qa-<identificador>.
```

Ativação constrói antes de parar escritores; valida schema/configuração e identidade,
para os consumidores do projeto (inclusive o órfão recepcao-persist), verifica saída
e inicia apenas persistencia, sem parar MQTT/Redis/recepção/PostgreSQL nem recriar
grupo. A identidade fica vinculada à história no Redis. Confira status, backlog,
pendências, logs, destinos e consultas após a troca; health não substitui aceite.
Se houver falha, a operação encerra explicitamente: inspecione o relatório e pause.

A reversão padrão **pausa o novo tratamento** e mantém MQTT → Redis, PEL e banco.
Não reinicia automaticamente o legado depois de ACKs do novo serviço. Não use ACK
manual, reset de grupo, exclusão de pendências ou limpeza do Stream para resolver erros.
`docker compose down` para sem apagar volumes; `down -v` é restrito ao QA descartável.

### Retorno controlado ao legado (somente ensaio)

Congele a imagem antiga com `telemetry.py build-legacy --test --project vulture-qa-...`
e `--evidence reports/legacy.json`. O SHA é 4d83b0382b838e0a6f63c37edd365e6d761b2ca1.
Pause o novo, confirme zero escritores e grupo drenado (lag e pendências zero), e
controle todos os publicadores. Só então inclua `docker-compose.legacy.yml` e perfil
`legacy-rehearsal`, iniciando **apenas** recepcao-persist. Publique dados conhecidos e
compatíveis; pare o legado antes de ativar o novo. Conserve os mesmos volumes/grupo.
Esse ensaio não promete validação, precisão, quarentena, replay ou idempotência
equivalentes no legado e não autoriza seu retorno irrestrito em ambiente real.


## SCRUM-453 — QA integrada

A suíte `qa/` publica MQTT QoS 1 e observa Redis/PostgreSQL/CLI/API. Não importa
implementações de validação nem acrescenta opções de teste aos serviços.
Cada cenário usa Stream e cadastro exclusivos no projeto Docker descartável.
Falhas são reproduzidas com indisponibilidade local, lock PostgreSQL + SIGKILL,
ACL Redis que impede XACK e trigger temporária na quarentena. Triggers/usuários
são removidos ao final; o cenário de conteúdo ausente corrompe deliberadamente
uma entrada de teste e exige incidente durável/PEL preservada, sem ACK manual.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r qa/requirements.txt
# Suba primeiro o overlay descartável, com COMPOSE_PROJECT_NAME=vulture-qa-<id>,
# PERSIST_SOURCE_ID=<identidade da história> e DATABASE_URL vazia.
# Se mudar portas, exporte MQTT_PORT, TEST_REDIS_PORT e TEST_POSTGRES_PORT para pytest.
.venv/bin/pytest qa --junitxml=reports/telemetry.xml
.venv/bin/python scripts/require-results.py
python3 scripts/check-components.py
python3 scripts/evidence.py  # antes de down -v, somente projeto vulture-qa-*
```

Os cenários interrompem os serviços do projeto QA e deixam recepção/tratamento
principais parados; não use esse projeto como ambiente de desenvolvimento compartilhado.
O ambiente descartável deve ser novo para o E2E de regressão: rode `node scripts/e2e.mjs`
antes da suíte de falhas. A fixture NUMERIC extremo permanece no banco para evidência;
as APIs/motor existentes convertem para float8 e podem falhar com esse valor.
Precisão extrema é conferida em SQL. Não há mudança do contrato HTTP nesta etapa.
Séries de dados válidos excluem inconsistentes; o snapshot/overview atual tem outra
semântica e não se declara que todas as consultas filtram inconsistentes.

O check **Ambiente completo + E2E** preserva a regressão do produto e executa a QA
ampliada. Um segundo job executa os testes dos gitlinks de recepção e tratamento
com lint, pacote e cobertura >=80% por componente, e os testes do BANCO, benchmark
com 100 mil leituras, particionamento e reaplicação das migrations 016/017/018.
Integrações não podem passar com skips. Os runners de verificação incluem os testes,
sem herdar sua exclusão do `.dockerignore` de produção. As imagens de produção
continuam usando os Dockerfiles originais sem root.

JUnit, cobertura, pacotes, logs por cenário, inventário de imagens/volumes e SHAs
ficam em `reports/` (fora do Git) e nos artefatos do Actions. Os scripts de Bash e
PowerShell são auxiliares; o ensaio automatizado executado em CI é Linux.
A referência de QA no Confluence é proposta em revisão; CI não representa aceite
funcional do PO. Evidências finais e limitações devem ser revisadas pelo time antes
que a SCRUM-532 remova o persistidor legado.
