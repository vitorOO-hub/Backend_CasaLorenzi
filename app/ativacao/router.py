"""Rotas PUBLICAS da ativacao de conta do cliente importado (quem chama ainda nao tem login).

Unica excecao a "toda rota exige token" (ver tests/api/test_todas_as_rotas_exigem_login.py).
Protecao: limite sensivel por IP (app/core/protecoes.py), resposta que nao revela quais CPFs
existem e conta so para cliente ativo, sem login, importado.
"""

from fastapi import APIRouter

from app.ativacao import service
from app.ativacao.auth_admin import AuthAdminDep
from app.ativacao.schemas import (
    AtivacaoConta,
    ConsultaAtivacao,
    RespostaAtivacao,
    RespostaConsulta,
)
from app.core.db import ExecutarDep

router = APIRouter(prefix="/ativacao-conta", tags=["ativacao-conta"])


@router.post(
    "/consultar",
    response_model=RespostaConsulta,
    summary="Publica: o CPF precisa de e-mail para ativar a conta?",
)
def consultar(corpo: ConsultaAtivacao, executar: ExecutarDep):
    return executar(lambda conexao: service.consultar(conexao, corpo.cpf))


@router.post(
    "",
    response_model=RespostaAtivacao,
    summary="Publica: cria o login do cliente importado a partir do CPF",
)
def ativar(corpo: AtivacaoConta, executar: ExecutarDep, auth_admin: AuthAdminDep):
    return executar(
        lambda conexao: service.ativar(
            conexao, auth_admin, cpf=corpo.cpf, senha=corpo.senha, email=corpo.email
        )
    )
