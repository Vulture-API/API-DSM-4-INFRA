# SCRUM-618 — Vínculos de acesso por propriedade

Entrega implementada nas branches da SCRUM-396; integração depende de merge.

| Campo físico | Tipo | Restrições | Significado |
|---|---|---|---|
| user_id | integer | NOT NULL, PK composta, FK users.id, ON DELETE CASCADE | Usuário com vínculo de acesso |
| property_id | integer | NOT NULL, PK composta, FK properties.id, ON DELETE CASCADE | Propriedade acessível |

A PK `(user_id, property_id)` impede duplicações. `idx_user_properties_property` apoia consultas e cascatas por propriedade. O relacionamento entre usuários e propriedades é N:N. No dicionário histórico, `usuarios` corresponde a `users` e `propriedades` a `properties` no banco físico.

`properties.owner_user_id` continua representando o responsável cadastral. A migration 022 popula os vínculos dos proprietários existentes uma única vez; depois, alterar o responsável não concede nem revoga acesso. Um Administrador pode remover um vínculo inclusive do responsável. Criar uma propriedade como Gerente Agrícola registra o vínculo do criador na mesma transação.

Administrador tem escopo global; Gerente Agrícola, Cliente e outros perfis usam vínculos explícitos e ainda precisam das permissões da funcionalidade. Cliente permanece em modo leitura mesmo quando recebe concessões de escrita. Geração de relatórios é consulta, inclusive via POST.
