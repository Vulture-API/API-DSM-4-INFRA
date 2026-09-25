# API-DSM-4-INFRA

Repositório para subir o AgroTech inteiro na máquina de uma vez: banco, as APIs, a recepção MQTT, o front e um simulador de estações. Também tem o teste ponta a ponta que a gente usa para ver se os serviços continuam conversando entre si.

Os serviços não ficam aqui. Cada um continua no seu repositório e entra como submodule na pasta `services/`, sempre na branch `dev`.

## 🚀 Rodando tudo junto

Precisa de:

- Docker Desktop aberto
- Git
- Node 20 ou mais novo (só para o teste ponta a ponta)

No PowerShell:

```powershell
git clone --recurse-submodules https://github.com/Vulture-API/API-DSM-4-INFRA.git
cd API-DSM-4-INFRA
powershell -ExecutionPolicy Bypass -File scripts\testar.ps1
```

No Linux, Mac ou Git Bash:

```bash
git clone --recurse-submodules https://github.com/Vulture-API/API-DSM-4-INFRA.git
cd API-DSM-4-INFRA
./scripts/testar.sh
```

O script sobe os containers, espera todo mundo ficar saudável e roda o teste. Se terminar com `TUDO OK`, é só abrir http://localhost:3010.

A primeira vez demora uns minutos porque baixa as imagens e compila tudo. Depois fica rápido.

Se quiser só subir, sem rodar o teste:

```bash
docker compose up -d --build
```

## 🧩 O que sobe

| Serviço | Porta | Repositório |
| --- | --- | --- |
| Front | 3010 | API-DSM-4-FRONTEND |
| Usuários | 3000 | API-DSM-4-USUARIO |
| Parâmetros e sensores | 3001 | API-DSM-4-PARAMETROS |
| Alertas (com o motor de regras) | 3002 | API-DSM-4-ALERTAS |
| Estações | 3005 | API-DSM-4-ESTACOES |
| Recepção MQTT → Redis | | API-DSM-4-RECEPCAO-DADOS (`ingest`) |
| Redis → Postgres | | API-DSM-4-RECEPCAO-DADOS (`persist`) |
| PostgreSQL 16 | 5433 | schema e seeds do API-DSM-4-BANCO |
| Mosquitto (MQTT) | 1883 | |
| Redis | só dentro da rede do Docker | |
| Simulador de estações | | `scripts/simulador.mjs` |

O caminho de um dado é esse:

```
estação → MQTT → recepcao → Redis → recepcao-persist → Postgres → APIs → front
```

O Postgres está na 5433 para não brigar com um Postgres que você já tenha instalado na 5432. Para conectar pelo DBeaver ou pelo psql: `postgresql://postgres:postgres@localhost:5433/vulture`.

## 🌱 Dados de demonstração

Quando o banco é criado pela primeira vez, ele já vem com dados para dar para mexer no sistema:

- 10 usuários (senha de todos: `senha123`) e 6 propriedades
- 15 estações e 93 sensores
- 7 dias de leituras, uma a cada 10 minutos
- 20 regras de alerta e os alertas que elas já teriam disparado

Com tudo no ar, o simulador manda uma leitura por minuto das estações ativas. As estações 05 e 10 ficam Offline de propósito, e a 15 nunca comunicou, para dar para ver os status no front.

Esses dados são só para ambiente local. Não rodar o `seed-demo.sql` no Neon.

## 🛠️ Comandos que a gente mais usa

| Comando | Para quê |
| --- | --- |
| `docker compose ps` | ver o que está rodando |
| `docker compose logs -f api-alertas` | acompanhar o log de um serviço |
| `docker compose up -d --build frontend` | recompilar só um serviço |
| `docker compose down` | parar tudo (o banco fica salvo) |
| `docker compose down -v` | parar tudo e apagar o banco |
| `node scripts/e2e.mjs` | rodar só o teste ponta a ponta |
| `git submodule update --remote` | puxar a última versão da `dev` de todos os serviços |

## 🧪 Testando o que você mudou antes de subir

Se você clonou os repositórios um do lado do outro (por exemplo `API4\API-DSM-4-ESTACOES`, `API4\API-DSM-4-INFRA`...), dá para o compose usar essas pastas em vez dos submodules. Assim você testa a sua branch junto com o resto:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\testar.ps1 -Local
```

O `-Local` é o mesmo que colocar `SERVICES_DIR=..` no `.env` (tem um exemplo no `.env.example`).

Outras opções do script:

- `-Unit` roda também lint, testes e build de cada repositório, igual ao CI
- `-Down` derruba tudo e apaga o banco no final

## ✅ O que o teste ponta a ponta verifica

O `scripts/e2e.mjs` não precisa instalar nada e apaga tudo o que cria no final. Ele passa pelas histórias da Sprint 1:

- **US03 Usuários:** cria, recusa e-mail repetido, edita, desativa e confere a paginação
- **US02 Parâmetros e sensores:** cria tipo de sensor, recusa nome repetido, vincula sensor a uma estação
- **US01 Estações:** lista propriedades, cria estação, normaliza o MAC e recusa MAC repetido
- **US04 Status:** a estação nasce Offline, recebe uma leitura pelo MQTT e fica Online
- **US05 Alertas:** cria a regra `temp > 30`, manda uma leitura de 35,5 e confere que o alerta disparou e pode ser reconhecido
- **Front:** as telas abrem e o proxy `/api/*` chega em cada serviço

São 51 verificações. No final aparece quantas passaram.

## 📡 Formato da mensagem da estação

Tópico `estacoes/<MAC>/dados`:

```json
{ "estacao_id": "AA:BB:CC:DD:EE:01", "unix_time": 1760000000, "temp": 23.5, "umid": 61 }
```

- `estacao_id` é o MAC cadastrado na estação
- cada outro campo numérico é o identificador de um sensor da estação (o `local_identifier`)
- campo que não bate com nenhum sensor é ignorado, e o log do `recepcao-persist` mostra quantos foram

## 🤖 CI

O workflow `.github/workflows/e2e.yml` sobe o ambiente com a `dev` de todos os repositórios e roda o teste ponta a ponta. Ele roda em PR, dá para disparar na mão e roda sozinho todo dia útil às 7h. Se algum merge quebrar a integração entre os serviços, aparece aqui.

## ⚠️ Problemas comuns

- **Porta ocupada:** confira se não tem outro Postgres, Redis ou Node usando a porta. O Redis não expõe porta de propósito.
- **Front apontando para o lugar errado:** o front grava os endereços das APIs no build. Mudou algum endereço, rode `docker compose up -d --build frontend`.
- **Banco com dados antigos:** os seeds só rodam quando o volume é criado. Para começar do zero, `docker compose down -v` e suba de novo.
- **Mapa sem fundo:** o mapa usa os tiles do OpenStreetMap, então precisa de internet. Sem internet os pinos aparecem mesmo assim.

## Limites

Esse ambiente é só para desenvolvimento. O Mosquitto não tem autenticação e o banco usa senha fixa. As migrations 010 a 012 do API-DSM-4-BANCO (particionamento com pg_partman) não rodam aqui porque a imagem do Postgres não tem a extensão.
