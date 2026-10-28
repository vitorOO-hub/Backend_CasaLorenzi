"""Rota PUBLICA do login por CPF (quem chama ainda nao tem token).

Excecao a "toda rota exige token" (ver tests/api/test_todas_as_rotas_exigem_login.py), com limite
sensivel por IP e resposta unica para CPF desconhecido ou senha errada.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends

from app.acesso import service
from app.acesso.erros import LoginIndisponivel
from app.acesso.schemas import EntradaCpf, SessaoSupabase
from app.core.config import Settings, get_settings
from app.core.db import ExecutarDep

router = APIRouter(prefix="/acesso", tags=["acesso"])


def get_login_auth(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[service.LoginAuth]:
    """Um cliente HTTP por requisicao, fechado no fim. A chave nunca sai do servidor."""
    chave = settings.supabase_service_role_key
    if not settings.supabase_url or chave is None:
        raise LoginIndisponivel
    login = service.LoginSupabase(settings.supabase_url, chave.get_secret_value())
    try:
        yield login
    finally:
        login.fechar()


LoginDep = Annotated[service.LoginAuth, Depends(get_login_auth)]


@router.post(
    "/entrar-cpf",
    response_model=SessaoSupabase,
    summary="Publica: cliente entra com CPF e senha (devolve a sessao do Supabase)",
)
def entrar_cpf(corpo: EntradaCpf, executar: ExecutarDep, login: LoginDep):
    return executar(lambda conexao: service.entrar_por_cpf(conexao, login, corpo.cpf, corpo.senha))
