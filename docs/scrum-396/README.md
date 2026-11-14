# SCRUM-396 — Escopo de acesso por propriedade

Entrega das tarefas SCRUM-608 a SCRUM-618 atribuídas a Rafael (Sette 0_0), em 14/11/2026. As branches foram publicadas sem PRs, merges ou deploys; a integração ainda depende de merge. Os status do Jira foram preservados. CI remoto não executado, conforme escolha do usuário; validações locais com PostgreSQL e ambiente Docker descartáveis.

## Entregas e contratos

- [Branches, bases e commits por tarefa](branches.md), também disponíveis em [JSON](branches.json).
- [Contrato OpenAPI 1.7.0](contrato-api.yaml): mantém o contrato anterior e acrescenta identidade e gestão de vínculos. Os caminhos são relativos à base da API; no backend integrado, a base efetiva é `/api`.
- [Dicionário físico de user_properties](dicionario-user-properties.md) e [modelo SQL](modelo-user-properties.sql).
- [Resultados das validações](validacao.json).

A implementação usa as camadas existentes: autenticação consulta perfil, permissões e vínculos no PostgreSQL; `resolveAccessibleProperties` centraliza o escopo; contexto assíncrono isolado por requisição leva esse escopo às consultas parametrizadas dos repositórios. Os filtros entram antes de contagens, paginação e agregações. Processadores internos de telemetria não herdam uma restrição global de usuário.

## Regras de acesso

| Perfil | Propriedades | Escrita |
|---|---|---|
| Administrador | Todas; ainda exige permissão da funcionalidade | Conforme as permissões atuais |
| Gerente Agrícola | Somente vínculos explícitos | Conforme permissões, dentro do escopo |
| Cliente | Somente vínculos explícitos | Sempre recusada; consultas e geração de relatórios são permitidas |
| Outros perfis | Somente vínculos explícitos | Conforme permissões, dentro do escopo |

Sem vínculos, coleções e totais ficam vazios. As rotas por ID retornam o mesmo 404 para recursos inexistentes ou fora do escopo. Referências de origem e destino em associações e corpos de criação/edição também são verificadas. Autenticação e permissão precedem validação da entrada e verificação do escopo.

A regra cobre propriedades, estações, sensores, dados atuais, séries, histórico, estatísticas, previsão, alertas, ocorrências, relatórios e aliases existentes. No WebSocket, o acesso é revisto a cada ciclo e novamente depois de carregar o lote, antes de enviá-lo. Uma estação específica revogada encerra a conexão; uma assinatura global passa a enviar somente estações ainda permitidas.

`ACCESS_CONTROL_ENABLED=false` preserva o modo legado. A identidade e os endpoints administrativos de vínculos são protegidos em ambos os modos. O JWT continua contendo apenas `sub`; direitos atuais não são confiados ao token.

## API de vínculos

- `GET /api/auth/me` acrescenta `role_name` e `property_ids`: `null` para escopo global, `[]` para nenhum vínculo e uma lista de IDs para escopo restrito.
- `GET /api/users/{id}/properties` retorna a lista de propriedades vinculadas. Exige Administrador e `users.read`.
- `PUT /api/users/{id}/properties` recebe `{ "property_ids": [1, 2] }`, substitui a lista atomicamente e retorna as propriedades vinculadas. Exige Administrador e `users.update`. `[]` remove todos; IDs repetidos são normalizados.

Parâmetros inválidos retornam 400; falta de autenticação, 401; perfil/permissão insuficiente, 403; usuário ou propriedade inexistente, 404. Falhas preservam os vínculos anteriores. Substituições concorrentes são serializadas por lock do usuário.

O frontend oferece seleção múltipla ao Administrador, reabre os vínculos persistidos e invalida os caches afetados. Se criar/editar o usuário funcionar e salvar vínculos falhar, o formulário mantém a identidade criada e repete apenas a etapa pendente. Mudanças de perfil, permissões ou escopo limpam dados anteriores e reiniciam o WebSocket. Cliente não recebe ações de escrita mesmo com concessões indevidas; POST de relatório continua sendo consulta.

## Banco e integração

Aplicar a migration `022_user_properties.sql` depois da 021, antes de iniciar o backend atualizado. Ela cria PK composta, FKs com cascata e índice por propriedade. O backfill dos proprietários ocorre apenas ao criar a tabela; reaplicar não devolve acesso revogado. `owner_user_id` permanece cadastral. A propriedade criada pelo Gerente e o vínculo do criador são gravados na mesma transação.

O instalador e `docker-compose.test.yml` incluem a migration. O seed demo vincula Carlos Mendes à Fazenda Santa Rita e Fernanda Costa à Fazenda Boa Vista. Seu seed e reaplicação foram conferidos em banco descartável.

O E2E existente permanece em modo legado; uma etapa adicional prepara `qa/seed-property-scope.sql`, liga o controle, executa `scripts/e2e-property-scope.mjs` e restaura o modo legado antes da QA de telemetria. Essa fixture cria contas exclusivamente para QA e concede escrita ao Cliente deliberadamente para comprovar que o perfil continua impedido de escrever.

As versões finais dos componentes estão fixadas no gitlink da INFRA. Para reproduzir, usar um projeto Docker exclusivo com prefixo `vulture-qa-`, o overlay de teste, portas livres e segredo descartável; ignorar `.env`. Nunca aplicar esses seeds ou comandos de teste em banco compartilhado.

## Documentação oficial

Atualização da SCRUM-618 preparada sobre o conteúdo atual, preservando imagens e anotações existentes:

- [Contrato de API](https://vultureapi.atlassian.net/wiki/spaces/V/pages/21495809)
- [Dicionário de dados](https://vultureapi.atlassian.net/wiki/spaces/V/pages/19660801)
- [Modelo Banco](https://vultureapi.atlassian.net/wiki/spaces/V/pages/17203205)

Essas páginas identificam a entrega em branches e a pendência de merge. O modelo histórico é preservado e recebe a evolução N:N; diferenças históricas fora dessa evolução não foram reescritas.
