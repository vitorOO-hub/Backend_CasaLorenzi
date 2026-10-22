"""Lorenzi+: compra nova gera pontos e os vencimentos sao lancados todo dia

Revision ID: 20261024100000
Revises: 20261023120000
Create Date: 2026-10-24 10:00:00

O programa de pontos (antes Vulto+, agora Lorenzi+) vale para todos os clientes.

- Credito por compra, com a regra da carga do Vulto+ (scripts/clientes_vulto_carga): R$ 1 = 1 ponto
  sobre o valor da compra, compra online em dobro, arredondando depois de multiplicar (meio vai
  para o par, como o `round` do Python). So compra paga, separada ou entregue da pontos; criada,
  aguardando pagamento ou cancelada nao. Cada credito vale 365 dias.
- So pedido criado depois desta migracao pontua: venda antiga importada (ou resolvida na fila de
  pendentes) ja teve os pontos contados na carga.
- O trigger em `pedido` concilia o extrato a cada mudanca de status, valor, canal ou cliente: o
  checkout grava o pedido com valor 0 e preenche o total depois, e um cancelamento depois do
  credito vira um `estorno` negativo ligado ao pedido (`movimento_pontos.id_pedido`).
- `lancar_vencimentos_pontos(cliente)` lanca o que venceu (mesma regra de
  app/cliente/vencimento_pontos.py) e `lancar_vencimentos_pontos_todos()` faz isso para todos.
  Com pg_cron disponivel (Supabase), ela roda todo dia as 03:00 de Sao Paulo; sem ele (Postgres
  local dos testes) nada e agendado.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from alembic import op

revision: str = "20261024100000"
down_revision: str | Sequence[str] | None = "20261023120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB = "lorenzi-mais-vencimentos"
# Data de referencia da carga do Vulto+: o que venceu ate aqui ja foi lancado por ela.
CORTE_DA_CARGA = "2026-10-21 23:59:59-03"

VENCIMENTOS = f"""
CREATE OR REPLACE FUNCTION public.lancar_vencimentos_pontos(
    p_usuario uuid, p_agora timestamptz DEFAULT now()
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    corte CONSTANT timestamptz := TIMESTAMPTZ '{CORTE_DA_CARGA}';
    saldo integer;
    parte integer;
    falta integer;
    usado integer;
    total integer;
    lancado integer;
    lancou integer := 0;
    data timestamptz;
    entrada timestamptz;
    i integer;
    n integer;
    m record;
    l_ent timestamptz[] := '{{}}';
    l_resta integer[] := '{{}}';
    l_vence timestamptz[] := '{{}}';
    l_ped uuid[] := '{{}}';
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(p_usuario::text, 0));

    -- Saldo na data de corte, repartido do lote mais novo para o mais antigo.
    SELECT GREATEST(COALESCE(sum(pontos), 0), 0) INTO saldo
    FROM movimento_pontos WHERE id_usuario = p_usuario AND ocorrido_em <= corte;
    FOR m IN
        SELECT ocorrido_em, pontos, vence_em, id_pedido FROM movimento_pontos
        WHERE id_usuario = p_usuario AND ocorrido_em <= corte AND pontos > 0
          AND (vence_em IS NULL OR vence_em > corte)
        ORDER BY ocorrido_em DESC, criado_em DESC, id_movimento DESC
    LOOP
        parte := LEAST(m.pontos, saldo);
        saldo := saldo - parte;
        l_ent := array_prepend(m.ocorrido_em, l_ent);
        l_resta := array_prepend(parte, l_resta);
        l_vence := array_prepend(m.vence_em, l_vence);
        l_ped := array_prepend(m.id_pedido, l_ped);
    END LOOP;

    -- Depois do corte: cada movimento na ordem; antes dele, vence o que ja venceu. A ultima
    -- linha (fim = 1) vence o que venceu ate agora.
    FOR m IN
        SELECT * FROM (
            SELECT pontos, ocorrido_em, vence_em, id_pedido, 0 AS fim, criado_em, id_movimento
            FROM movimento_pontos
            WHERE id_usuario = p_usuario AND ocorrido_em > corte AND tipo <> 'vencimento'
            UNION ALL
            SELECT 0, p_agora, NULL, NULL, 1, NULL, NULL
        ) eventos
        ORDER BY fim, ocorrido_em, criado_em, id_movimento
    LOOP
        n := COALESCE(array_length(l_ent, 1), 0);
        LOOP
            data := NULL;
            FOR i IN 1..n LOOP
                IF l_resta[i] > 0 AND l_vence[i] IS NOT NULL AND l_vence[i] > corte
                   AND (l_vence[i] < m.ocorrido_em OR (m.fim = 1 AND l_vence[i] <= m.ocorrido_em))
                   AND (data IS NULL OR l_vence[i] < data) THEN
                    data := l_vence[i];
                END IF;
            END LOOP;
            EXIT WHEN data IS NULL;
            total := 0;
            entrada := NULL;
            FOR i IN 1..n LOOP
                IF l_vence[i] = data THEN
                    total := total + l_resta[i];
                    l_resta[i] := 0;
                    entrada := LEAST(entrada, l_ent[i]);
                END IF;
            END LOOP;
            SELECT COALESCE(-sum(pontos), 0) INTO lancado FROM movimento_pontos
            WHERE id_usuario = p_usuario AND tipo = 'vencimento' AND ocorrido_em = data;
            falta := total - lancado;
            IF falta > 0 THEN
                INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao)
                VALUES (p_usuario, 'vencimento', -falta, data, 'vencimento dos pontos de '
                        || to_char(entrada AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY'));
                lancou := lancou + falta;
            END IF;
        END LOOP;

        EXIT WHEN m.fim = 1;
        IF m.pontos > 0 THEN
            l_ent := array_append(l_ent, m.ocorrido_em);
            l_resta := array_append(l_resta, m.pontos);
            l_vence := array_append(l_vence, m.vence_em);
            l_ped := array_append(l_ped, m.id_pedido);
        ELSE
            -- Estorno de compra sai primeiro do credito da propria compra; o resto, dos antigos.
            falta := -m.pontos;
            FOR i IN 1..n LOOP
                IF falta > 0 AND m.id_pedido IS NOT NULL AND l_ped[i] = m.id_pedido
                   AND l_resta[i] > 0 AND (l_vence[i] IS NULL OR l_vence[i] > m.ocorrido_em) THEN
                    usado := LEAST(l_resta[i], falta);
                    l_resta[i] := l_resta[i] - usado;
                    falta := falta - usado;
                END IF;
            END LOOP;
            FOR i IN 1..n LOOP
                IF falta > 0 AND l_resta[i] > 0
                   AND (l_vence[i] IS NULL OR l_vence[i] > m.ocorrido_em) THEN
                    usado := LEAST(l_resta[i], falta);
                    l_resta[i] := l_resta[i] - usado;
                    falta := falta - usado;
                END IF;
            END LOOP;
        END IF;
    END LOOP;
    RETURN lancou;
END
$fn$
"""

VENCIMENTOS_TODOS = f"""
CREATE OR REPLACE FUNCTION public.lancar_vencimentos_pontos_todos(p_agora timestamptz DEFAULT now())
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    u uuid;
    lancou integer := 0;
BEGIN
    FOR u IN
        SELECT DISTINCT id_usuario FROM movimento_pontos
        WHERE vence_em > TIMESTAMPTZ '{CORTE_DA_CARGA}' AND vence_em <= p_agora
    LOOP
        lancou := lancou + public.lancar_vencimentos_pontos(u, p_agora);
    END LOOP;
    RETURN lancou;
END
$fn$
"""

PONTOS_DA_COMPRA = """
CREATE OR REPLACE FUNCTION public.pontos_da_compra(p_valor numeric, p_canal text)
RETURNS integer
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $fn$
    SELECT CASE
        WHEN v - floor(v) > 0.5 THEN floor(v) + 1
        WHEN v - floor(v) < 0.5 THEN floor(v)
        ELSE floor(v) + mod(floor(v), 2)
    END::integer
    FROM (SELECT GREATEST(COALESCE(p_valor, 0), 0)
                 * CASE WHEN p_canal = 'online' THEN 2 ELSE 1 END AS v) x
$fn$
"""


def _credito(inicio: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION public.pedido_credita_pontos()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    cli uuid;
    desejado integer;
    atual integer;
    dif integer;
    pontua boolean;
    agora timestamptz;
BEGIN
    IF NEW.criado_em < TIMESTAMPTZ '{inicio}' THEN
        RETURN NEW;
    END IF;
    SELECT s.codigo IN ('pago', 'separado', 'entregue') INTO pontua
    FROM status_pedido s WHERE s.id_status_pedido = NEW.id_status_pedido;

    FOREACH cli IN ARRAY ARRAY[
        CASE WHEN TG_OP = 'UPDATE' THEN OLD.id_cliente END, NEW.id_cliente
    ] LOOP
        CONTINUE WHEN cli IS NULL;
        CONTINUE WHEN NOT EXISTS (
            SELECT 1 FROM usuario u JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
            WHERE u.id_usuario = cli AND t.codigo = 'cliente'
        );
        desejado := CASE WHEN cli = NEW.id_cliente AND COALESCE(pontua, false)
                         THEN public.pontos_da_compra(NEW.valor_total, NEW.canal_venda) ELSE 0 END;
        SELECT COALESCE(sum(pontos), 0) INTO atual FROM movimento_pontos
        WHERE id_usuario = cli AND id_pedido = NEW.id_pedido AND tipo IN ('credito', 'estorno');
        dif := desejado - atual;
        -- clock_timestamp: credito e estorno na mesma transacao ficam na ordem em que aconteceram.
        agora := clock_timestamp();
        IF dif > 0 THEN
            INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em,
                                          descricao, id_pedido, criado_em)
            VALUES (cli, 'credito', dif, agora, agora + interval '365 days',
                    'compra ' || NEW.numero_pedido, NEW.id_pedido, agora);
        ELSIF dif < 0 THEN
            INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao,
                                          id_pedido, criado_em)
            VALUES (cli, 'estorno', dif, agora,
                    'estorno da compra ' || NEW.numero_pedido, NEW.id_pedido, agora);
        END IF;
    END LOOP;
    RETURN NEW;
END
$fn$
"""


AGENDAR = f"""
DO $do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron') THEN
        CREATE EXTENSION IF NOT EXISTS pg_cron;
        IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = '{JOB}') THEN
            PERFORM cron.unschedule('{JOB}');
        END IF;
        -- 06:00 UTC = 03:00 em Sao Paulo.
        PERFORM cron.schedule(
            '{JOB}', '0 6 * * *', 'SELECT public.lancar_vencimentos_pontos_todos()'
        );
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'pg_cron indisponivel; vencimentos diarios nao agendados: %', SQLERRM;
END
$do$
"""

DESAGENDAR = f"""
DO $do$
BEGIN
    -- IFs separados: sem pg_cron, a tabela cron.job nem existe.
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = '{JOB}') THEN
            PERFORM cron.unschedule('{JOB}');
        END IF;
    END IF;
END
$do$
"""

FUNCOES = (
    "public.lancar_vencimentos_pontos(uuid, timestamptz)",
    "public.lancar_vencimentos_pontos_todos(timestamptz)",
    "public.pedido_credita_pontos()",
)


def upgrade() -> None:
    inicio = datetime.now(UTC).isoformat()
    op.execute(
        "ALTER TABLE public.movimento_pontos ADD COLUMN IF NOT EXISTS id_pedido UUID "
        "REFERENCES public.pedido (id_pedido) ON UPDATE CASCADE ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_movimento_pontos_pedido "
        "ON public.movimento_pontos (id_pedido) WHERE id_pedido IS NOT NULL"
    )
    for comando in (PONTOS_DA_COMPRA, VENCIMENTOS, VENCIMENTOS_TODOS, _credito(inicio)):
        op.execute(comando)
    for funcao in FUNCOES:
        op.execute(f"REVOKE ALL ON FUNCTION {funcao} FROM PUBLIC, anon, authenticated")
    op.execute("DROP TRIGGER IF EXISTS trg_pedido_credita_pontos ON public.pedido")
    op.execute(
        """
        CREATE TRIGGER trg_pedido_credita_pontos
        AFTER INSERT OR UPDATE OF id_status_pedido, valor_total, canal_venda, id_cliente
        ON public.pedido
        FOR EACH ROW EXECUTE FUNCTION public.pedido_credita_pontos()
        """
    )
    op.execute(AGENDAR)


def downgrade() -> None:
    op.execute(DESAGENDAR)
    op.execute("DROP TRIGGER IF EXISTS trg_pedido_credita_pontos ON public.pedido")
    for funcao in (*FUNCOES, "public.pontos_da_compra(numeric, text)"):
        op.execute(f"DROP FUNCTION IF EXISTS {funcao}")
    op.execute("DROP INDEX IF EXISTS public.idx_movimento_pontos_pedido")
    op.execute("ALTER TABLE public.movimento_pontos DROP COLUMN IF EXISTS id_pedido")
