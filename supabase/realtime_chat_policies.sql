-- Policies dos canais privados do chat ao vivo (Realtime Authorization).
--
-- A migration 20261007120000 ja cria estas policies. Rode este arquivo no SQL Editor do painel do
-- Supabase SO se a migration tiver avisado "sem permissao em realtime.messages".
--
-- O canal de cada conversa se chama "chamado:<uuid do atendimento>" e e criado no front com
-- { config: { private: true } }. So entra (ler) e so envia (digitando, presenca) quem enxerga o
-- atendimento: o proprio cliente, a equipe da loja do chamado ou o admin.

DROP POLICY IF EXISTS "chat - receber presenca e digitacao do chamado" ON realtime.messages;
DROP POLICY IF EXISTS "chat - enviar presenca e digitacao do chamado" ON realtime.messages;

CREATE POLICY "chat - receber presenca e digitacao do chamado" ON realtime.messages
FOR SELECT TO authenticated
USING (
    extension IN ('broadcast', 'presence')
    AND CASE
        WHEN realtime.topic() ~ '^chamado:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        THEN public.app_pode_ver_atendimento(split_part(realtime.topic(), ':', 2)::uuid)
        ELSE false
    END
);

CREATE POLICY "chat - enviar presenca e digitacao do chamado" ON realtime.messages
FOR INSERT TO authenticated
WITH CHECK (
    extension IN ('broadcast', 'presence')
    AND CASE
        WHEN realtime.topic() ~ '^chamado:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        THEN public.app_pode_ver_atendimento(split_part(realtime.topic(), ':', 2)::uuid)
        ELSE false
    END
);

-- Postgres Changes: as tabelas precisam estar na publicacao supabase_realtime.
ALTER PUBLICATION supabase_realtime ADD TABLE public.mensagem;
ALTER PUBLICATION supabase_realtime ADD TABLE public.atendimento;
