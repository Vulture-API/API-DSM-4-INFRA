# SCRUM-532 — Recepção restrita a MQTT → Redis

Execução local em 23/10/2026, após SCRUM-531 e SCRUM-453 concluídas no Jira.
[Contrato oficial](https://vultureapi.atlassian.net/wiki/spaces/V/pages/46333954).
[PR da recepção](https://github.com/Vulture-API/API-DSM-4-RECEPCAO-DADOS/pull/7).

## Resultado e integração

A recepção não inclui asyncpg, persistidor PostgreSQL ou configurações INGEST_DATABASE_URL /
INGEST_PERSIST_*. Os modos padrão e ingest continuam disponíveis. Persist encerra
com erro antes da configuração/conexões, orientando station-persist consume.
MQTT, campos Redis, ACK após XADD, filas, retentativas, retenção e métricas mantidos.

O INFRA fixa somente o novo gitlink da recepção. Foram removidos o overlay legado,
build-legacy e o fetch de sua imagem congelada. A regressão de ativação, pausa e
retomada do tratamento preserva backlog, pendências, Stream/grupo/volume e os dados.
A detecção de containers antigos órfãos permanece. A pausa mantém MQTT → Redis;
não oferece retorno ao persistidor removido. A compatibilidade de eventos legados,
PERSIST_LEGACY_MAX_ID e a proteção de retenção por grupos continuam disponíveis.

Integrar o PR da recepção em dev antes do PR INFRA em cloudflare. Não se devem
atualizar outros gitlinks ou absorver o índice preparado do checkout original.

## Revisões verificadas

| Componente | SHA |
| --- | --- |
| Base INFRA cloudflare | 99e4c06e28d3053a1ca6d6dfcf2f6efc8915ee54 |
| RECEPCAO-DADOS | 27e86882a540499c74eea649e9195d8f857bc049 |
| PERSISTENCIA-DADOS | c784a2f5c1c91841b5b854fdd4198c4d31653114 |
| BANCO | 5422dee0e1b4fd0fe386a88843716f72e81e3eeb |
| BACKEND | 400936859e4ff0b801e9f305cff5a832df462a6f |
| FRONTEND | 40b928b465a164426ce99a3b7ad874d96f1ca3d8 |

## Evidências locais

| Verificação | Resultado |
| --- | --- |
| Recepção: suíte completa remanescente | 83 testes, 94,82% cobertura, sem skips |
| Tratamento independente, sem alterações | 223 testes, 97,11% cobertura, sem skips |
| BANCO, sem alterações | 11 testes, zero skips; setup repetido, benchmark de 100 mil leituras, particionamento e migrations reaplicadas |
| QA integrada de telemetria | 40 cenários aprovados, zero skips |
| Regressão de produto | 51 verificações E2E aprovadas |
| Lint e formatação | Ruff 0.16.10 aprovado |
| Pacotes e imagem | Builds dos dois serviços; imagem não root; recepção sem asyncpg/módulo antigo |
| Wheel da recepção em ambiente limpo | Instalação, pip check e rejeição do comando persist aprovados |

A correspondência do tratamento removido é coberta pelas suítes atuais de relações,
validação, destinos, persistência e recuperação no PERSISTENCIA-DADOS. A suíte de
persistência integrada verifica leituras/ocorrências/quarentena, comunicação da
estação, duplicatas, conflitos e concorrência. Nenhuma regra legada de descarte ou
conversão para float foi copiada.

Ambiente: Linux, Python 3.12, Node 24, Docker 29.9.1, Redis 7, PostgreSQL 16 e
Mosquitto 2. Projeto exclusivo vulture-qa-etapa8 e projetos de componentes exclusivos,
sem banco externo. Os testes de redelivery mantêm o broker disponível.

JUnit, cobertura, pacotes e logs sanitizados ficam em reports/ e nos artefatos CI.
O workflow preserva Ambiente completo + E2E, as suítes fixadas e os checks da
recepção. O CI da recepção utiliza somente Mosquitto e Redis; o runner do INFRA
fornece PostgreSQL/schema apenas ao tratamento e BANCO. Os gates exigem os cenários
da recepção em vez do número histórico de testes do persistidor removido.

Os resultados da etapa 7 permanecem históricos; seu teste de retorno legado não
integra a suíte corrente. Sem merge, implantação ou migration em banco externo.
As APIs mantêm suas limitações float8/JavaScript. A retirada de código não constitui
uma intervenção em ambientes existentes.
