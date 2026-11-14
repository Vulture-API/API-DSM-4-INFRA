-- SCRUM-608 / SCRUM-618. Modelo físico após aplicar a migration 022.
-- O responsável cadastral owner_user_id não concede acesso continuamente.
CREATE TABLE user_properties (
  user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  property_id integer NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, property_id)
);
CREATE INDEX idx_user_properties_property ON user_properties(property_id);
-- Na migration, o backfill de owner_user_id acontece somente na criação da tabela.
-- Reaplicar não restaura vínculos removidos pelo Administrador.
