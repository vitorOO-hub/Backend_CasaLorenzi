-- Rode no SQL Editor do Supabase se a migration 20261007200000 avisou falta de permissao em auth.users.
-- A funcao public.criar_cliente_no_cadastro() ja existe (criada pela migration); falta so o trigger.
DROP TRIGGER IF EXISTS trg_criar_cliente_no_cadastro ON auth.users;
CREATE TRIGGER trg_criar_cliente_no_cadastro
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.criar_cliente_no_cadastro();
