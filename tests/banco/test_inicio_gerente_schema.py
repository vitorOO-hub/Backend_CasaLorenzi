"""Migration do inicio do gerente: colunas, constraints, RLS e a conversao dos pedidos antigos."""

import importlib.util
from datetime import UTC, datetime

import psycopg
import pytest

from tests.banco.apoio import como, e_erro, tenta
from tests.banco.conftest import RAIZ

pytestmark = pytest.mark.banco

CAMINHO = RAIZ / "alembic" / "versions" / "20261007130000_inicio_gerente.py"


def migration():
    spec = importlib.util.spec_from_file_location("inicio_gerente", CAMINHO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def pedido(conn, fab, *, observacao=None, total=100, **colunas):
    """Insere um pedido; `colunas` sobrescreve ou acrescenta colunas (ex.: canal_venda)."""
    dados = {
        "numero_pedido": f"S-{fab._proximo()}",
        "id_loja": fab.loja(),
        "id_cliente": fab.usuario("cliente").id,
        "valor_total": total,
        "observacao": observacao,
        **colunas,
    }
    nomes = ", ".join(dados)
    marcadores = ", ".join(["%s"] * len(dados))
    return conn.execute(
        f"INSERT INTO pedido ({nomes}, id_status_pedido) VALUES ({marcadores}, "  # nosec B608
        "(SELECT id_status_pedido FROM status_pedido WHERE codigo = 'criado')) RETURNING id_pedido",
        list(dados.values()),
    ).fetchone()[0]


def coluna(conn, id_pedido, nome):
    return conn.execute(
        f"SELECT {nome} FROM pedido WHERE id_pedido = %s",  # nosec B608
        (id_pedido,),
    ).fetchone()[0]


# ------------------------------------------------------------------ pedido


def test_pedido_novo_nasce_online_e_sem_frete(conn, fab):
    id_pedido = pedido(conn, fab)
    assert coluna(conn, id_pedido, "canal_venda") == "online"
    assert float(coluna(conn, id_pedido, "valor_frete")) == 0.0


@pytest.mark.parametrize("canal", ["loja", "online"])
def test_canais_validos(conn, fab, canal):
    assert coluna(conn, pedido(conn, fab, canal_venda=canal), "canal_venda") == canal


@pytest.mark.parametrize("canal", ["telefone", "", "LOJA", "online "])
def test_canal_invalido_e_recusado(conn, fab, canal):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            pedido(conn, fab, canal_venda=canal)


def test_frete_negativo_e_recusado(conn, fab):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            pedido(conn, fab, valor_frete=-1)


def test_canal_nao_aceita_nulo(conn, fab):
    with pytest.raises(psycopg.errors.NotNullViolation):
        with conn.transaction():
            pedido(conn, fab, canal_venda=None)


def test_indices_de_consulta_existem(conn):
    achados = {
        linha[0]
        for linha in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
            "AND indexname IN ('idx_pedido_loja_criado_em', 'idx_item_pedido_id_variacao', "
            "'idx_ajuste_estoque_loja_status')"
        ).fetchall()
    }
    assert achados == {
        "idx_pedido_loja_criado_em",
        "idx_item_pedido_id_variacao",
        "idx_ajuste_estoque_loja_status",
    }


# ------------------------------------------------------------------ pedidos que ja existiam


def passos_de_conversao():
    return [c for c in migration().SUBIDA if "UPDATE public.pedido" in c]


def converter(conn, fab, observacao, total=100):
    """Cria o pedido como o banco antigo o deixava e roda os UPDATEs da migration."""
    id_pedido = pedido(conn, fab, observacao=observacao, total=total)
    for comando in passos_de_conversao():
        conn.execute(comando.replace(":", "\\:") if False else comando)
    return id_pedido


@pytest.mark.parametrize(
    ("observacao", "canal", "frete"),
    [
        ("Checkout pelo portal. Entrega: casa. Frete: R$ 49.00.", "online", 49.0),
        ("Checkout pelo portal. Entrega: loja. Frete: R$ 0.00.", "online", 0.0),
        ("Checkout pelo portal. Frete: R$ 19,90.", "online", 19.9),
        ("Checkout pelo portal. Retirada na loja.", "online", 0.0),
        ("Pedido de teste para validar o fluxo inicial.", "loja", 0.0),
        (None, "loja", 0.0),
    ],
)
def test_pedidos_antigos_viram_canal_e_frete_certos(conn, fab, observacao, canal, frete):
    id_pedido = converter(conn, fab, observacao, total=300)
    assert coluna(conn, id_pedido, "canal_venda") == canal
    assert float(coluna(conn, id_pedido, "valor_frete")) == frete


def test_frete_lido_do_texto_nunca_passa_do_total(conn, fab):
    id_pedido = converter(conn, fab, "Checkout pelo portal. Frete: R$ 500.00.", total=100)
    assert float(coluna(conn, id_pedido, "valor_frete")) == 100.0


# ------------------------------------------------------------------ ajuste_estoque


@pytest.fixture
def base(conn, fab):
    loja = fab.loja()
    produto = conn.execute(
        "INSERT INTO produto (nome, preco_base) VALUES ('Produto ajuste', 10) RETURNING id_produto"
    ).fetchone()[0]
    variacao = conn.execute(
        "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda) "
        "VALUES (%s, 'AJ-1', 'Azul', 'M', 10) RETURNING id_variacao",
        (produto,),
    ).fetchone()[0]
    return {
        "loja": loja,
        "variacao": variacao,
        "operador": fab.usuario("operador_estoque", loja=loja),
        "gerente": fab.usuario("gerente_loja", loja=loja),
    }


def inserir(conn, base, **colunas):
    padrao = {
        "id_loja": base["loja"],
        "id_variacao": base["variacao"],
        "id_usuario_solicitante": base["operador"].id,
        "quantidade": -2,
        "motivo": "Peca danificada",
    }
    padrao.update(colunas)
    nomes = ", ".join(padrao)
    marcadores = ", ".join(["%s"] * len(padrao))
    return conn.execute(
        f"INSERT INTO ajuste_estoque ({nomes}) VALUES ({marcadores}) RETURNING id_ajuste_estoque",  # nosec B608
        list(padrao.values()),
    ).fetchone()[0]


def recusa(conn, tipo, base, **colunas):
    with pytest.raises(tipo):
        with conn.transaction():
            inserir(conn, base, **colunas)


def test_ajuste_nasce_pendente_sem_decisao(conn, base):
    id_ajuste = inserir(conn, base)
    status, decisor, decidido = conn.execute(
        "SELECT status, id_usuario_decisor, decidido_em FROM ajuste_estoque "
        "WHERE id_ajuste_estoque = %s",
        (id_ajuste,),
    ).fetchone()
    assert (status, decisor, decidido) == ("pendente", None, None)


def test_ajuste_aprovado_e_rejeitado_exigem_quem_e_quando(conn, base):
    agora = datetime.now(UTC)
    for status in ("aprovado", "rejeitado"):
        recusa_ok = {"motivo_recusa": "Nao bate"} if status == "rejeitado" else {}
        inserir(
            conn,
            base,
            status=status,
            id_usuario_decisor=base["gerente"].id,
            decidido_em=agora,
            **recusa_ok,
        )
        recusa(conn, psycopg.errors.CheckViolation, base, status=status)
        recusa(conn, psycopg.errors.CheckViolation, base, status=status, decidido_em=agora)
        recusa(
            conn,
            psycopg.errors.CheckViolation,
            base,
            status=status,
            id_usuario_decisor=base["gerente"].id,
        )


def test_ajuste_pendente_nao_pode_ter_decisao(conn, base):
    recusa(
        conn,
        psycopg.errors.CheckViolation,
        base,
        id_usuario_decisor=base["gerente"].id,
        decidido_em=datetime.now(UTC),
    )
    recusa(conn, psycopg.errors.CheckViolation, base, decidido_em=datetime.now(UTC))


@pytest.mark.parametrize(
    "colunas",
    [{"quantidade": 0}, {"motivo": "   "}, {"motivo": ""}, {"status": "cancelado"}],
    ids=["quantidade zero", "motivo em branco", "motivo vazio", "status desconhecido"],
)
def test_ajuste_recusa_dados_invalidos(conn, base, colunas):
    recusa(conn, psycopg.errors.CheckViolation, base, **colunas)


@pytest.mark.parametrize(
    "colunas",
    [
        {"id_loja": "00000000-0000-0000-0000-000000000001"},
        {"id_variacao": "00000000-0000-0000-0000-000000000001"},
        {"id_usuario_solicitante": "00000000-0000-0000-0000-000000000001"},
    ],
    ids=["loja", "variacao", "solicitante"],
)
def test_ajuste_so_aponta_para_registros_que_existem(conn, base, colunas):
    recusa(conn, psycopg.errors.ForeignKeyViolation, base, **colunas)


def test_nao_se_apaga_loja_variacao_ou_usuario_com_ajuste(conn, base):
    inserir(conn, base)
    for tabela, chave, valor in (
        ("variacao_produto", "id_variacao", base["variacao"]),
        ("usuario", "id_usuario", base["operador"].id),
        ("loja", "id_loja", base["loja"]),
    ):
        with pytest.raises(psycopg.errors.RestrictViolation):
            with conn.transaction():
                conn.execute(f"DELETE FROM {tabela} WHERE {chave} = %s", (valor,))  # nosec B608


# ------------------------------------------------------------------ RLS


def test_ajuste_estoque_tem_rls_ligado_e_forcado(conn):
    ligado, forcado = conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = 'ajuste_estoque' AND relnamespace = 'public'::regnamespace"
    ).fetchone()
    assert ligado and forcado


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_front_nao_le_nem_escreve_ajustes(conn, base, role):
    inserir(conn, base)
    with como(conn, role=role, sub=base["gerente"].auth, papel="gerente_loja", loja=base["loja"]):
        assert e_erro(tenta(conn, "SELECT 1 FROM ajuste_estoque"))
        assert e_erro(
            tenta(
                conn,
                "INSERT INTO ajuste_estoque (id_loja, id_variacao, id_usuario_solicitante, "
                "quantidade, motivo) VALUES (%s, %s, %s, 1, 'x')",
                (base["loja"], base["variacao"], base["operador"].id),
            )
        )
        assert e_erro(tenta(conn, "UPDATE ajuste_estoque SET status = 'aprovado'"))
        assert e_erro(tenta(conn, "DELETE FROM ajuste_estoque"))


def test_pedido_continua_com_as_policies_de_antes(conn, fab):
    """Colunas novas nao mudam quem ve o pedido: o dono e a equipe da loja, ninguem mais."""
    loja, outra = fab.loja(), fab.loja()
    dono, estranho = fab.usuario("cliente"), fab.usuario("cliente")
    gerente, gerente_de_fora = (
        fab.usuario("gerente_loja", loja=loja),
        fab.usuario("gerente_loja", loja=outra),
    )
    conn.execute(
        "INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido, canal_venda) "
        "VALUES ('RLS-1', %s, %s, "
        "(SELECT id_status_pedido FROM status_pedido WHERE codigo = 'pago'), 'loja')",
        (loja, dono.id),
    )
    quem_ve = {"dono": (dono, None), "gerente": (gerente, "gerente_loja")}
    for nome, (usuario, papel) in quem_ve.items():
        with como(conn, sub=usuario.auth, papel=papel, loja=usuario.loja):
            assert len(tenta(conn, "SELECT 1 FROM pedido WHERE numero_pedido = 'RLS-1'")) == 1, nome
    for nome, (usuario, papel) in {
        "estranho": (estranho, None),
        "gerente de fora": (gerente_de_fora, "gerente_loja"),
    }.items():
        with como(conn, sub=usuario.auth, papel=papel, loja=usuario.loja):
            assert tenta(conn, "SELECT 1 FROM pedido WHERE numero_pedido = 'RLS-1'") == [], nome
