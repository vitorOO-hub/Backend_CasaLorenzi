"""Pela API de verdade: o token de quem foi desativado ou rebaixado deixa de valer na hora."""

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core import vigencia
from app.core.config import Settings
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para

pytestmark = pytest.mark.banco

ROTA = "/api/v1/painel/gerencia/pendencias"


@pytest.fixture
def cena(banco_migrado, monkeypatch):
    """Cria, com commit (a API usa outra conexao), uma loja e um gerente; apaga tudo no fim."""
    monkeypatch.setattr(vigencia, "ATIVA", True)
    vigencia._conferidos.clear()
    auth = uuid4()
    with psycopg.connect(banco_migrado, autocommit=True) as pg:
        loja = pg.execute(
            "INSERT INTO loja (codigo, nome, ativa) VALUES (%s, 'Loja Vigencia', true) "
            "RETURNING id_loja",
            (f"V{uuid4().hex[:8]}",),
        ).fetchone()[0]
        pg.execute(
            "INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email) VALUES "
            "((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = 'gerente_loja'), "
            "%s, %s, 'Gerente Vigencia', %s)",
            (loja, auth, f"vigencia-{auth.hex[:8]}@teste.local"),
        )
        par = ParDeChaves()
        app = criar_app(
            Settings(_env_file=None, database_url=banco_migrado, supabase_url=SUPABASE_URL)
        )
        app.state.provedor_chaves = provedor_para(par)
        token = par.emitir(sub=str(auth), papel="gerente_loja", loja_id=str(loja))
        yield pg, auth, TestClient(app), {"Authorization": f"Bearer {token}"}
        pg.execute("DELETE FROM usuario WHERE auth_user_id = %s", (auth,))
        pg.execute("DELETE FROM loja WHERE id_loja = %s", (loja,))
    vigencia._conferidos.clear()


def test_token_de_conta_ativa_funciona(cena):
    _, _, cliente, cabecalho = cena
    assert cliente.get(ROTA, headers=cabecalho).status_code == 200


def test_desativar_a_conta_derruba_o_token_ja_emitido(cena):
    pg, auth, cliente, cabecalho = cena
    assert cliente.get(ROTA, headers=cabecalho).status_code == 200
    pg.execute("UPDATE usuario SET ativo = false WHERE auth_user_id = %s", (auth,))
    vigencia.esquecer(auth)
    assert cliente.get(ROTA, headers=cabecalho).status_code == 401


def test_cargo_rebaixado_derruba_o_token_com_o_cargo_antigo(cena):
    pg, auth, cliente, cabecalho = cena
    pg.execute(
        "UPDATE usuario SET id_tipo_usuario = (SELECT id_tipo_usuario FROM tipo_usuario "
        "WHERE codigo = 'atendente') WHERE auth_user_id = %s",
        (auth,),
    )
    vigencia.esquecer(auth)
    assert cliente.get(ROTA, headers=cabecalho).status_code == 401
