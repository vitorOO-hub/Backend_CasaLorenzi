-- Rode no SQL Editor do Supabase SOMENTE se a migration 20261008110000 avisou que nao tinha
-- permissao em auth.users. Desativa a linha de `usuario` quando a conta some do Auth.

CREATE OR REPLACE FUNCTION public.desativar_usuario_ao_excluir_conta()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
BEGIN
    UPDATE public.usuario
    SET ativo = false, auth_user_id = NULL, atualizado_em = now()
    WHERE auth_user_id = OLD.id;
    RETURN OLD;
END
$fn$;

REVOKE ALL ON FUNCTION public.desativar_usuario_ao_excluir_conta() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS trg_desativar_usuario_ao_excluir_conta ON auth.users;
CREATE TRIGGER trg_desativar_usuario_ao_excluir_conta
AFTER DELETE ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.desativar_usuario_ao_excluir_conta();
