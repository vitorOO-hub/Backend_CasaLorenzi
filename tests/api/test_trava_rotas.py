"""A trava ligada em app/api/router.py, sem banco: o executor devolve lista vazia."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_executar
from app.core.papeis import Papel
from app.main import criar_app
from tests.auth_util import SUPABASE_URL, ParDeChaves, provedor_para
from tests.conftest import DATABASE_URL_TESTE

EQUIPE_DE_ESTOQUE = {Papel.OPERADOR_ESTOQUE, Papel.GERENTE_LOJA, Papel.ADMIN}
TODOS = {None, *Papel}

# (caminho, quem pode)
ROTAS = [
    ("/admin/lojas", {Papel.ADMIN}),
    ("/estoques", EQUIPE_DE_ESTOQUE),
    ("/movimentacoes-estoque", EQUIPE_DE_ESTOQUE),
    ("/atendimentos", TODOS),
    ("/compras/pedidos", TODOS),
]
CASOS = [(caminho, papel) for caminho, _quem in ROTAS for papel in (None, *Papel)]


def montar(obrigatoria: bool):
    par = ParDeChaves()
    app = criar_app(
        Settings(
            _env_file=None,
            database_url=DATABASE_URL_TESTE,
            supabase_url=SUPABASE_URL,
            autenticacao_obrigatoria=obrigatoria,
        )
    )
    app.state.provedor_chaves = provedor_para(par)
    app.dependency_overrides[get_executar] = lambda: (lambda _operacao: [])
    return TestClient(app), par


def token_do_papel(par: ParDeChaves, papel: Papel | None) -> str:
    if papel is None:
        return par.emitir()
    if papel is Papel.ADMIN:
        return par.emitir(papel="admin")
    return par.emitir(papel=papel.value, loja_id=str(uuid4()))


@pytest.mark.parametrize("caminho", [caminho for caminho, _ in ROTAS])
def test_com_a_flag_desligada_nada_exige_token(caminho):
    cliente, _par = montar(obrigatoria=False)
    assert cliente.get(caminho).status_code == 200


@pytest.mark.parametrize("caminho", [caminho for caminho, _ in ROTAS])
def test_com_a_flag_ligada_sem_token_responde_401(caminho):
    cliente, _par = montar(obrigatoria=True)
    assert cliente.get(caminho).status_code == 401


@pytest.mark.parametrize(("caminho", "papel"), CASOS)
def test_matriz_de_papeis_com_a_flag_ligada(caminho, papel):
    permitidos = dict(ROTAS)[caminho]
    cliente, par = montar(obrigatoria=True)
    resposta = cliente.get(
        caminho, headers={"Authorization": f"Bearer {token_do_papel(par, papel)}"}
    )
    assert resposta.status_code == (200 if papel in permitidos else 403)


def test_health_nunca_e_travado():
    cliente, _par = montar(obrigatoria=True)
    assert cliente.get("/health").status_code == 200
