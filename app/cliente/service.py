"""Regras da area do cliente."""

from uuid import UUID

from app.cliente import repositorio
from app.core.erros_auth import SemPermissao
from app.core.papeis import UsuarioAtual


def _garantir_cliente(usuario: UsuarioAtual) -> None:
    if usuario.papel is not None:
        raise SemPermissao()


def _id_cliente(conexao, usuario: UsuarioAtual) -> UUID:
    _garantir_cliente(usuario)
    return repositorio.id_cliente_ativo(conexao, usuario.id_auth)


def listar_lojas(conexao, usuario: UsuarioAtual):
    _garantir_cliente(usuario)
    return repositorio.listar_lojas(conexao)


def obter_perfil(conexao, usuario: UsuarioAtual):
    id_cliente = _id_cliente(conexao, usuario)
    return repositorio.perfil_cliente(conexao, id_cliente)


def listar_pedidos(conexao, usuario: UsuarioAtual, *, limit: int, offset: int):
    id_cliente = _id_cliente(conexao, usuario)
    return repositorio.listar_pedidos_cliente(conexao, id_cliente, limit=limit, offset=offset)


def obter_pedido(conexao, usuario: UsuarioAtual, id_pedido: UUID):
    id_cliente = _id_cliente(conexao, usuario)
    return repositorio.obter_pedido_cliente(conexao, id_cliente, id_pedido)


def opcoes_chamado(conexao, usuario: UsuarioAtual):
    _garantir_cliente(usuario)
    return repositorio.opcoes_chamado(conexao)


def listar_chamados(conexao, usuario: UsuarioAtual, *, limit: int, offset: int):
    id_cliente = _id_cliente(conexao, usuario)
    return repositorio.listar_chamados_cliente(conexao, id_cliente, limit=limit, offset=offset)


def obter_chamado(conexao, usuario: UsuarioAtual, id_atendimento: UUID):
    id_cliente = _id_cliente(conexao, usuario)
    return repositorio.obter_chamado_cliente(conexao, id_cliente, id_atendimento)


def listar_mensagens_chamado(conexao, usuario: UsuarioAtual, id_atendimento: UUID):
    id_cliente = _id_cliente(conexao, usuario)
    return repositorio.listar_mensagens_chamado_cliente(conexao, id_cliente, id_atendimento)


def criar_chamado(conexao, usuario: UsuarioAtual, dados: dict[str, object]):
    id_cliente = _id_cliente(conexao, usuario)
    return repositorio.criar_chamado_cliente(conexao, id_cliente, dados)


def enviar_mensagem_chamado(
    conexao,
    usuario: UsuarioAtual,
    id_atendimento: UUID,
    texto: str,
):
    id_cliente = _id_cliente(conexao, usuario)
    return repositorio.enviar_mensagem_chamado_cliente(
        conexao,
        id_cliente,
        id_atendimento,
        texto,
    )


def criar_checkout(
    conexao,
    usuario: UsuarioAtual,
    dados: dict[str, object],
    *,
    chave_idempotencia: str | None,
):
    id_cliente = _id_cliente(conexao, usuario)
    return repositorio.criar_checkout(
        conexao,
        id_cliente,
        dados,
        chave_idempotencia=chave_idempotencia,
    )
