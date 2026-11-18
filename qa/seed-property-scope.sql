-- Somente PostgreSQL descartável de QA. Senha conhecida: senha123.
-- O Cliente recebe escrita deliberadamente para verificar a restrição por perfil.
BEGIN;
INSERT INTO roles(name) VALUES ('Administrador'),('Gerente Agrícola'),('Cliente') ON CONFLICT(name) DO NOTHING;
INSERT INTO role_permissions(role_id,permission_code)
SELECT r.id,p.code FROM roles r CROSS JOIN permissions p
WHERE r.name IN ('Administrador','Gerente Agrícola','Cliente') ON CONFLICT DO NOTHING;
WITH accounts(email,role_name) AS (VALUES
  ('scope-admin@qa.test','Administrador'),
  ('scope-manager@qa.test','Gerente Agrícola'),
  ('scope-client@qa.test','Cliente')
), inserted AS (
  INSERT INTO users(role_id,name)
  SELECT r.id,a.email FROM accounts a JOIN roles r ON r.name=a.role_name
  WHERE NOT EXISTS(SELECT 1 FROM credentials c WHERE c.email=a.email)
  RETURNING id,name
)
INSERT INTO credentials(user_id,email,password_hash)
SELECT id,name,'scrypt$16384$8$1$a9c1f00d5eedc0ffee1234567890abcd$4a4033066dcb2a37839f9d82be5a791972bd0361af20e684524da72832d4dcb4df5586de96fcabae8127f709117fa7988e691ff3041b6738141c53b2d5c74b6a' FROM inserted;
COMMIT;
