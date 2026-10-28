"""Lorenzi+: o saldo de pontos nunca fica negativo

Revision ID: 20261028100000
Revises: 20261027120000
Create Date: 2026-10-28 10:00:00

Regra do programa (a mesma da carga do Vulto+: "o saldo nunca fica negativo"):

- Trava: antes de gravar uma saida de pontos da plataforma (origem 'sistema': estorno de compra
  cancelada, resgate, vencimento, ajuste), o banco lanca os vencimentos pendentes do cliente e
  limita a saida ao saldo que sobra. Saldo zerado nao tem saida gravada. As cargas (origem
  'vulto+...') gravam o extrato historico ja conferido e ficam de fora: la a diferenca perdoada
  entra como ajuste no mesmo instante.
- Rede de seguranca: `zerar_saldos_negativos_pontos()` lanca um ajuste "saldo negativo zerado" para
  quem estiver negativo por qualquer outra via. Roda na migracao e todo dia no job das 03:00.
- Vencimento: saida que o saldo nao cobria vira divida; o credito seguinte paga a divida antes de
  virar lote. Assim o ajuste que zera o saldo nao vira "pontos que vencem depois". E so conta o que
  aconteceu ate o momento do calculo (movimentacao com data futura nao adianta vencimento).
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "20261028100000"
down_revision: str | Sequence[str] | None = "20261027120000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _anterior():
    """Funcoes de vencimento da migracao 20261024100000 (a base que esta migracao ajusta)."""
    caminho = Path(__file__).with_name("20261024100000_lorenzi_mais_pontos.py")
    spec = importlib.util.spec_from_file_location("lorenzi_mais_pontos_20261024100000", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _trocar(texto: str, de: str, para: str) -> str:
    if de not in texto:
        raise RuntimeError(f"trecho esperado nao encontrado: {de[:60]!r}")
    return texto.replace(de, para, 1)


def _vencimentos_com_divida(base: str) -> str:
    sql = _trocar(
        base, "    lancou integer := 0;\n", "    lancou integer := 0;\n    divida integer := 0;\n"
    )
    sql = _trocar(
        sql,
        "    SELECT GREATEST(COALESCE(sum(pontos), 0), 0) INTO saldo\n"
        "    FROM movimento_pontos WHERE id_usuario = p_usuario AND ocorrido_em <= corte;\n",
        "    SELECT COALESCE(sum(pontos), 0) INTO saldo\n"
        "    FROM movimento_pontos WHERE id_usuario = p_usuario AND ocorrido_em <= corte;\n"
        "    divida := GREATEST(-saldo, 0);\n"
        "    saldo := GREATEST(saldo, 0);\n",
    )
    sql = _trocar(
        sql,
        "        IF m.pontos > 0 THEN\n"
        "            l_ent := array_append(l_ent, m.ocorrido_em);\n"
        "            l_resta := array_append(l_resta, m.pontos);\n",
        "        IF m.pontos > 0 THEN\n"
        "            -- Credito paga primeiro a divida (saida que o saldo nao cobria).\n"
        "            usado := LEAST(m.pontos, divida);\n"
        "            divida := divida - usado;\n"
        "            l_ent := array_append(l_ent, m.ocorrido_em);\n"
        "            l_resta := array_append(l_resta, m.pontos - usado);\n",
    )
    # So o que aconteceu ate "agora": movimentacao datada depois nao adianta vencimento.
    sql = _trocar(
        sql,
        "WHERE id_usuario = p_usuario AND ocorrido_em > corte AND tipo <> 'vencimento'",
        "WHERE id_usuario = p_usuario AND ocorrido_em > corte AND ocorrido_em <= p_agora\n"
        "              AND tipo <> 'vencimento'",
    )
    return _trocar(
        sql,
        "                    falta := falta - usado;\n"
        "                END IF;\n"
        "            END LOOP;\n"
        "        END IF;\n"
        "    END LOOP;\n"
        "    RETURN lancou;\n",
        "                    falta := falta - usado;\n"
        "                END IF;\n"
        "            END LOOP;\n"
        "            divida := divida + falta;\n"
        "        END IF;\n"
        "    END LOOP;\n"
        "    RETURN lancou;\n",
    )


def _todos_zerando(base: str) -> str:
    return _trocar(
        base,
        "    END LOOP;\n    RETURN lancou;\n",
        "    END LOOP;\n    PERFORM public.zerar_saldos_negativos_pontos();\n    RETURN lancou;\n",
    )


ZERAR = """
CREATE OR REPLACE FUNCTION public.zerar_saldos_negativos_pontos()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    r record;
    zerados integer := 0;
BEGIN
    FOR r IN
        SELECT id_usuario, sum(pontos) AS saldo FROM movimento_pontos
        GROUP BY id_usuario HAVING sum(pontos) < 0
    LOOP
        PERFORM pg_advisory_xact_lock(hashtextextended(r.id_usuario::text, 0));
        INSERT INTO movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, descricao)
        SELECT r.id_usuario, 'ajuste', -sum(pontos), clock_timestamp(),
               'saldo negativo zerado (regra do programa: o saldo nunca fica negativo)'
        FROM movimento_pontos WHERE id_usuario = r.id_usuario
        HAVING sum(pontos) < 0;
        zerados := zerados + 1;
    END LOOP;
    RETURN zerados;
END
$fn$
"""

TRAVA = """
CREATE OR REPLACE FUNCTION public.pontos_saldo_nao_negativo()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    saldo integer;
BEGIN
    -- So saidas validas da plataforma; linha invalida segue para as regras da tabela recusarem.
    IF NEW.pontos >= 0 OR NEW.origem IS DISTINCT FROM 'sistema'
       OR NEW.tipo NOT IN ('resgate', 'vencimento', 'estorno', 'ajuste')
       OR NEW.vence_em IS NOT NULL THEN
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.id_usuario::text, 0));
    -- Vencimentos pendentes primeiro: a saida so pode usar pontos que ainda valem agora.
    IF NEW.tipo <> 'vencimento' THEN
        PERFORM public.lancar_vencimentos_pontos(NEW.id_usuario, now());
    END IF;
    SELECT COALESCE(sum(pontos), 0) INTO saldo
    FROM movimento_pontos WHERE id_usuario = NEW.id_usuario;
    IF saldo + NEW.pontos >= 0 THEN
        RETURN NEW;
    END IF;
    IF saldo <= 0 THEN
        RETURN NULL;  -- saldo ja zerado: a saida nao tem de onde sair
    END IF;
    NEW.pontos := -saldo;
    NEW.descricao := NEW.descricao || ' (limitado ao saldo)';
    RETURN NEW;
END
$fn$
"""

FUNCOES = (
    "public.zerar_saldos_negativos_pontos()",
    "public.pontos_saldo_nao_negativo()",
)


def upgrade() -> None:
    anterior = _anterior()
    op.execute(ZERAR)
    op.execute(TRAVA)
    for funcao in FUNCOES:
        op.execute(f"REVOKE ALL ON FUNCTION {funcao} FROM PUBLIC, anon, authenticated")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_movimento_pontos_saldo_nao_negativo ON public.movimento_pontos"
    )
    op.execute(
        """
        CREATE TRIGGER trg_movimento_pontos_saldo_nao_negativo
        BEFORE INSERT ON public.movimento_pontos
        FOR EACH ROW EXECUTE FUNCTION public.pontos_saldo_nao_negativo()
        """
    )
    op.execute(_vencimentos_com_divida(anterior.VENCIMENTOS))
    op.execute(_todos_zerando(anterior.VENCIMENTOS_TODOS))
    op.execute("SELECT public.zerar_saldos_negativos_pontos()")


def downgrade() -> None:
    anterior = _anterior()
    op.execute(anterior.VENCIMENTOS)
    op.execute(anterior.VENCIMENTOS_TODOS)
    op.execute(
        "DROP TRIGGER IF EXISTS trg_movimento_pontos_saldo_nao_negativo ON public.movimento_pontos"
    )
    for funcao in FUNCOES:
        op.execute(f"DROP FUNCTION IF EXISTS {funcao}")
