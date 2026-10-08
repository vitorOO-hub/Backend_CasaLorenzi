"""Vigencia do token: a conta do JWT ainda existe, esta ativa e tem o mesmo cargo e loja.

O JWT e assinado e vale ate expirar, mas o cargo e a loja dele foram gravados na emissao. Sem esta
conferencia, quem foi desativado (ou rebaixado, ou trocou de loja) continuaria com o acesso antigo
por ate uma hora. Aqui o backend confere no banco, com um cache curto para nao pesar em toda
requisicao. Qualquer divergencia vira 401: o front renova a sessao e recebe as claims atuais (ou
nenhum cargo, se a conta nao vale mais).
"""

import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.erros_auth import NaoAutenticado
from app.core.papeis import Papel, UsuarioAtual

# Desligavel so nos testes que simulam o banco (tests/conftest.py); em producao fica sempre ligada.
ATIVA = True

TTL_SEGUNDOS = 20.0
LIMITE_DO_CACHE = 5000

CONSULTA = text(
    """
    SELECT CASE t.codigo WHEN 'diretor' THEN 'admin' ELSE t.codigo END AS papel,
           u.id_loja, u.ativo AND t.ativo AS vigente
    FROM usuario u
    JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
    WHERE u.auth_user_id = CAST(:sub AS uuid)
    """
)

Executar = Callable[[Callable[[Connection], Any]], Any]

# (sub, papel, loja) -> instante em que a conferencia deixa de valer
_conferidos: dict[tuple[UUID, str, UUID | None], float] = {}


def esquecer(id_auth: UUID) -> None:
    """Chamado quando uma conta muda (cargo, loja, acesso): a proxima requisicao reconfere."""
    for chave in [k for k in _conferidos if k[0] == id_auth]:
        _conferidos.pop(chave, None)


def conferir(usuario: UsuarioAtual, executar: Executar) -> None:
    """Levanta 401 se a conta do token nao vale mais ou nao bate com as claims."""
    if not ATIVA or usuario.papel is None:
        return
    chave = (usuario.id_auth, usuario.papel.value, usuario.id_loja)
    agora = time.monotonic()
    if _conferidos.get(chave, 0.0) > agora:
        return
    linha = executar(
        lambda conexao: conexao.execute(CONSULTA, {"sub": str(usuario.id_auth)}).first()
    )
    if linha is None or not linha[2] or linha[0] != usuario.papel.value:
        raise NaoAutenticado()
    if usuario.papel is not Papel.ADMIN and linha[1] != usuario.id_loja:
        raise NaoAutenticado()
    if len(_conferidos) >= LIMITE_DO_CACHE:
        _conferidos.clear()
    _conferidos[chave] = agora + TTL_SEGUNDOS
