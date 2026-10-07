-- Imita o que o Supabase ja entrega no banco hospedado: papeis, schema auth e privilegios padrao.
-- So para o Postgres de teste local; nunca roda no Supabase.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN
        CREATE ROLE supabase_auth_admin NOLOGIN NOINHERIT;
    END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim.sub', true), ''),
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
    )::uuid
$$;

CREATE OR REPLACE FUNCTION auth.jwt() RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim', true), ''),
        nullif(current_setting('request.jwt.claims', true), '')
    )::jsonb
$$;

CREATE OR REPLACE FUNCTION auth.role() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim.role', true), ''),
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
    )::text
$$;

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role, supabase_auth_admin;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role, supabase_auth_admin;
GRANT EXECUTE ON FUNCTION auth.uid(), auth.jwt(), auth.role()
    TO anon, authenticated, service_role, supabase_auth_admin;

-- O Supabase concede tudo por padrao nas tabelas e funcoes novas do schema public.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;

-- Realtime do Supabase: publicacao das mudancas e a tabela de mensagens dos canais privados
-- (Broadcast e Presence). So o necessario para testar as policies do chat.
DROP PUBLICATION IF EXISTS supabase_realtime;
CREATE PUBLICATION supabase_realtime;

CREATE SCHEMA IF NOT EXISTS realtime;

CREATE TABLE IF NOT EXISTS realtime.messages (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    topic TEXT NOT NULL,
    extension TEXT NOT NULL,
    payload JSONB,
    event TEXT,
    private BOOLEAN DEFAULT FALSE,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE realtime.messages ENABLE ROW LEVEL SECURITY;

-- O Realtime real informa o canal pela configuracao realtime.topic antes de checar a policy.
CREATE OR REPLACE FUNCTION realtime.topic() RETURNS text
LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('realtime.topic', true), '') $$;

GRANT USAGE ON SCHEMA realtime TO anon, authenticated, service_role;
GRANT SELECT, INSERT ON realtime.messages TO authenticated;
GRANT EXECUTE ON FUNCTION realtime.topic() TO anon, authenticated, service_role;
