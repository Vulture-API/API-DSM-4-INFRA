# Etapa 7 — QA da integração e transição da telemetria

Destino: Confluence VultureDocs, página filha de
[Contrato de telemetria — recepção e tratamento](https://vultureapi.atlassian.net/wiki/spaces/V/pages/46333954).
Verificar título existente antes de publicar. Este arquivo é a cópia versionada do
conteúdo de entrega; a publicação e a revisão pelo time devem ser conferidas no Jira.

Execução: 22/10/2026. Responsável pela execução: conta pessoal do solicitante.
Tarefas: [SCRUM-531](https://vultureapi.atlassian.net/browse/SCRUM-531) e
[SCRUM-453](https://vultureapi.atlassian.net/browse/SCRUM-453).
PR de integração: https://github.com/Vulture-API/API-DSM-4-INFRA/pull/1 (base cloudflare).
PR de QA: encadeado na branch SCRUM-531; atualizar o link após sua criação.
A referência [Processo de QA](https://vultureapi.atlassian.net/wiki/spaces/V/pages/30605317)
está como proposta em revisão. Aprovação do CI não substitui aceite funcional.

## Topologia, versões e ambiente

Estações → Mosquitto (QoS 1) → RECEPCAO-DADOS → Redis/AOF → PERSISTENCIA-DADOS
(`consume`) → PostgreSQL → BACKEND/FRONTEND. Somente recepção/Redis dependem do MQTT;
a recepção não possui configuração de banco. O novo tratamento possui imagem e
configurações independentes e não foi ativado em ambiente externo.

| Repositório | SHA fixado |
| --- | --- |
| BACKEND | 400936859e4ff0b801e9f305cff5a832df462a6f |
| FRONTEND | 40b928b465a164426ce99a3b7ad874d96f1ca3d8 |
| BANCO | 5422dee0e1b4fd0fe386a88843716f72e81e3eeb |
| PERSISTENCIA-DADOS | c784a2f5c1c91841b5b854fdd4198c4d31653114 |
| RECEPCAO-DADOS | 537d2ffba212a5e2b5abbeb5456368d4409a29d3 |
| Imagem legada de ensaio | 4d83b0382b838e0a6f63c37edd365e6d761b2ca1 |

Ensaio local: Linux, Docker Engine 29.9.1, Python 3.12, Node 24, Redis 7,
PostgreSQL 16, Mosquitto 2. Portas somente localhost; banco interno e projeto
`vulture-qa-etapa7`. CI usa projeto exclusivo por run/attempt e gitlinks fixados.
O inventário completo de versões/imagens/digests está nos artefatos do Actions.
As alterações preparadas no índice original da cloudflare, incluindo gitlinks de
BACKEND/FRONTEND, foram preservadas; implementação em checkout isolado.

O banco descartável aplica schema → 015 → 016_occurrences →
016_sensor_limits_and_reading_precision → 017 → 018 → seed. Health TCP aguarda
inicialização completa. Nenhuma migration foi aplicada em banco externo.

## Matriz de rastreabilidade

| Critério | Cenário executável | Evidência | Resultado |
| --- | --- | --- | --- |
| Recepção independente de banco/tratamento e backlog | `test_receiver_independent_pg_outage_then_backlog` | JUnit + logs do cenário | Aprovado no ensaio |
| Redis indisponível, broker mantido disponível | `test_redis_outage_retries_with_broker_alive` | JUnit + Redis/AOF | Aprovado no ensaio |
| Envelope/limite de tamanho, preservação de campos | `test_definitive_envelope_rejection`, `test_oversize_envelope`, `test_mixed_fields...` | JUnit + BYTEA original | Aprovado no ensaio |
| Múltiplos sensores e relações por estação | `test_mixed_fields...`, `test_unknown_station_rejection`, `test_mac_identification` | SQL + JUnit | Aprovado no ensaio |
| Timestamp ausente/inválido/corte legado explícito | `test_missing_timestamp...`, `test_invalid_timestamp...`, `test_explicit_legacy_cutoff...` | JUnit + ledger | Aprovado no ensaio |
| Decimal exato e limites inclusivos | `test_limits_inclusive_and_extreme_decimal_sql`, `test_mixed_fields...` | SQL NUMERIC + JUnit | Aprovado no ensaio |
| Destinos mistos, leitura inconsistente e ocorrência | `test_mixed_fields...`, `test_invalid_values...` | SQL + séries HTTP de dados válidos | Aprovado no ensaio |
| Duplicatas, conflito e consumidores concorrentes | `test_duplicates_conflicts_concurrent_consumers` | Leituras/ocorrências/resultados + JUnit | Aprovado no ensaio |
| Queda antes do commit | `test_sigkill_before_commit_and_other_identity_recovers` | Lock PG + SIGKILL, ledger vazio antes da retomada | Aprovado no ensaio |
| Commit sem ACK e retomada por outra identidade | `test_commit_before_xack_acl_failure_and_recovery` | ACL -XACK, PEL e contagens duráveis | Aprovado no ensaio |
| Falha na quarentena causa rollback | `test_quarantine_failure_rolls_back_then_recovers` | Trigger temporária + PEL + transação | Aprovado no ensaio |
| Replay rastreável e UUID idempotente | `test_replay_dry_run_and_idempotent_uuid_preserve_accepted` | CLI/ledger/attempts; dry-run sem escrita | Aprovado no ensaio |
| Conteúdo ausente não desaparece sem prova | `test_missing_content_records_incident_without_ack` | Incidente PG + pendência preservada | Aprovado no ensaio |
| Retenção protege todos os grupos | `test_retention_protects_old_pending_and_all_groups` | 250 eventos antigos; grupo atrasado/pendente/ausente | Aprovado no ensaio |
| Inspeções não escrevem nem criam grupos | `test_inspection_modes_do_not_write_or_create_groups` | CLI inspect/resolve/validate + SQL/Redis | Aprovado no ensaio |
| Transição, pausa e retorno legado controlado | `test_cutover_pause_and_controlled_legacy_return_preserve_history` | Volume/grupo/Stream mantidos, nenhum escritor simultâneo | Aprovado no ensaio |
| Imagens independentes e não root | `test_production_images_non_root_and_separate_configuration` | UID e configuração Compose | Conferir execução final/CI |
| Regressão de produto | `scripts/e2e.mjs` | 51 verificações aprovadas | Aprovado no ensaio |
| Suítes fixadas e cobertura por componente | `scripts/check-components.py` | JUnit/cobertura/pacotes + TAP Banco | Aprovado no ensaio |

Recepção: 100 testes, 92,93% cobertura. Tratamento: 223 testes, 97,11% cobertura.
BANCO: 11 testes sem skips; setup repetido, benchmark de 100 mil leituras,
particionamento e migrations 013/016/017/018 reaplicadas. Não se calcula média
entre componentes. Novos testes INFRA são adicionais às suítes originais.

## Reprodução e evidências

Seguir README para ambiente QA novo, `DATABASE_URL` vazia, `PERSIST_SOURCE_ID`
explícito e exclusivo da história. Executar E2E antes das fixtures de extremos;
`pytest qa --junitxml=reports/telemetry.xml`, `scripts/require-results.py` e
`scripts/check-components.py`. Coletar `scripts/evidence.py` antes do cleanup.
O workflow E2E mantém o check **Ambiente completo + E2E**, PR/manual e agenda
07h Brasília em dias úteis, e publica os relatórios e logs sanitizados.

`reports/telemetry.xml`: cenários integrados, sem skips. `reports/scenarios/`:
logs por cenário. `reports/transitions/`: inventário salvo antes de parar escritores,
mesmo quando uma ativação posterior falha. `reports/components/`: JUnit, cobertura,
pacotes e TAP Banco. `reports/inventory.json`, gitlinks e versions: reprodução.
Links de execução e SHA final dos PRs devem constar no comentário das tarefas.

Falhas da montagem inicial dos testes foram corrigidas no runner: inclusão dos
testes excluídos pelo Dockerignore de produção, captura de stderr dos logs e
encerramento idempotente quando negar XACK já encerra o consumidor. Não houve
skips para ocultar falhas. A matriz final deve refletir somente as execuções finais.

## Transição e reversão

1. `telemetry.py preflight`: validar configuração, schema, MQTT/Redis/recepção,
identidade de origem, imagens, volume, Stream/grupo, posição e PEL (amostra limitada
com contagem total do grupo). Lock exclusivo por projeto no host do operador.
2. `activate`: construir antes de parar os consumidores; guardar inventário antes
da troca; parar legado/novo do projeto e confirmar encerramento; iniciar somente
tratamento com o mesmo grupo e SOURCE_ID. Não resetar/recriar grupo existente.
3. Verificar status, lag/pendências, destinos, consultas e logs. A troca é restrita
a um operador por projeto; o lock local não coordena hosts distintos. Se alguém
iniciar containers manualmente em paralelo, interromper e investigar.
4. Reversão padrão `pause`: parar novo tratamento, manter MQTT → Redis, AOF/volume,
PEL e PostgreSQL. Não reativar legado automaticamente após ACKs do novo.
5. Ensaio legado: imagem congelada, grupo drenado, publicadores controlados,
entradas conhecidas/compatíveis; iniciar apenas legado e pará-lo antes do novo.
Verificar volumes e ausência de escritores simultâneos. Não equivale a fallback
irrestrito ou compatibilidade de validação/precisão/quarentena.

Nenhum procedimento operacional usa ACK manual, reset de grupo, exclusão de
pendências ou limpeza do Stream. `down -v` só em projeto QA identificado e descartável.

## Limites e continuidade

- Retenção desabilitada por padrão; ao habilitar, configurar todos os grupos
obrigatórios, inclusive o PERSIST_GROUP efetivo. Falha de metadados/grupo ausente
impede corte. PERSIST_LEGACY_MAX_ID nunca é inferido.
- Mosquitto local tem persistence false: ensaios mantêm broker disponível;
não se declara durabilidade de restart do broker, QoS 0 ou exactly once.
- Precisão exata está no tratamento/PostgreSQL; APIs atuais convertem para
float8/JavaScript e podem falhar em NUMERIC extremo. Não houve mudança HTTP.
- Séries de dados válidos filtram inconsistentes; não se estende essa afirmação
à semântica de todas as consultas, especialmente overview/snapshot.
- Scripts PowerShell foram atualizados; execução automatizada é Linux.
- Sem deploy, migrations externas ou merge. SCRUM-532 aguarda validação do time
antes de retirar o pacote/dependências PostgreSQL da recepção.
