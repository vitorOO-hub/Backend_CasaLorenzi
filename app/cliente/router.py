"""Rotas da area do cliente.

Estas rotas sempre usam o cliente do JWT. O navegador nunca informa `id_cliente`.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status

from app.cliente import service
from app.cliente.schemas import (
    CarrinhoCliente,
    ChamadoCliente,
    ChamadoCriacao,
    CheckoutCriacao,
    DetalheChamadoCliente,
    EstoqueVariacaoCliente,
    ItemCarrinhoAtualizacao,
    ItemCarrinhoCriacao,
    LojaCliente,
    MensagemChamadoCliente,
    MensagemChamadoCriacao,
    OpcoesChamadoCliente,
    PerfilCliente,
    PedidoCliente,
)
from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.security import get_current_user

router = APIRouter(prefix="/cliente", tags=["cliente"])

UsuarioDep = Annotated[UsuarioAtual, Depends(get_current_user)]
ChaveIdempotencia = Annotated[str | None, Header(alias="Idempotency-Key", max_length=160)]


@router.get("/lojas", response_model=list[LojaCliente], summary="Lojas disponiveis")
def listar_lojas(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.listar_lojas(conexao, usuario))


@router.get(
    "/catalogo/estoque",
    response_model=list[EstoqueVariacaoCliente],
    summary="Estoque disponivel para o catalogo do cliente",
)
def listar_estoque_catalogo(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.listar_estoque_catalogo(conexao, usuario))


@router.get("/perfil", response_model=PerfilCliente, summary="Perfil do cliente logado")
def obter_perfil(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_perfil(conexao, usuario))


@router.get("/pedidos", response_model=list[PedidoCliente], summary="Pedidos do cliente logado")
def listar_pedidos(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return executar(
        lambda conexao: service.listar_pedidos(conexao, usuario, limit=limit, offset=offset)
    )


@router.get(
    "/pedidos/{id_pedido}",
    response_model=PedidoCliente,
    summary="Detalhe de um pedido do cliente logado",
)
def obter_pedido(id_pedido: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_pedido(conexao, usuario, id_pedido))


@router.get("/carrinho", response_model=CarrinhoCliente, summary="Carrinho do cliente logado")
def obter_carrinho(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_carrinho(conexao, usuario))


@router.post(
    "/carrinho/itens",
    response_model=CarrinhoCliente,
    status_code=status.HTTP_201_CREATED,
    summary="Adicionar item ao carrinho do cliente logado",
)
def adicionar_item_carrinho(
    dados: ItemCarrinhoCriacao,
    usuario: UsuarioDep,
    executar: ExecutarDep,
):
    return executar(
        lambda conexao: service.adicionar_item_carrinho(
            conexao,
            usuario,
            dados.model_dump(),
        )
    )


@router.patch(
    "/carrinho/itens/{id_variacao}",
    response_model=CarrinhoCliente,
    summary="Alterar quantidade de um item do carrinho",
)
def atualizar_item_carrinho(
    id_variacao: UUID,
    dados: ItemCarrinhoAtualizacao,
    usuario: UsuarioDep,
    executar: ExecutarDep,
):
    return executar(
        lambda conexao: service.atualizar_item_carrinho(
            conexao,
            usuario,
            id_variacao,
            dados.model_dump(),
        )
    )


@router.delete(
    "/carrinho/itens/{id_variacao}",
    response_model=CarrinhoCliente,
    summary="Remover item do carrinho",
)
def remover_item_carrinho(id_variacao: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.remover_item_carrinho(conexao, usuario, id_variacao))


@router.delete("/carrinho", response_model=CarrinhoCliente, summary="Limpar carrinho")
def limpar_carrinho(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.limpar_carrinho(conexao, usuario))


@router.get(
    "/chamados/opcoes",
    response_model=OpcoesChamadoCliente,
    summary="Opcoes para chamados do cliente",
)
def opcoes_chamado(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.opcoes_chamado(conexao, usuario))


@router.get(
    "/chamados",
    response_model=list[ChamadoCliente],
    summary="Chamados do cliente logado",
)
def listar_chamados(
    usuario: UsuarioDep,
    executar: ExecutarDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return executar(
        lambda conexao: service.listar_chamados(conexao, usuario, limit=limit, offset=offset)
    )


@router.post(
    "/chamados",
    response_model=DetalheChamadoCliente,
    status_code=status.HTTP_201_CREATED,
    summary="Abrir chamado do cliente logado",
)
def criar_chamado(dados: ChamadoCriacao, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(
        lambda conexao: service.criar_chamado(conexao, usuario, dados.model_dump())
    )


@router.get(
    "/chamados/{id_atendimento}",
    response_model=DetalheChamadoCliente,
    summary="Detalhe de um chamado do cliente logado",
)
def obter_chamado(id_atendimento: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_chamado(conexao, usuario, id_atendimento))


@router.get(
    "/chamados/{id_atendimento}/mensagens",
    response_model=list[MensagemChamadoCliente],
    summary="Conversa de um chamado do cliente logado",
)
def listar_mensagens_chamado(id_atendimento: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(
        lambda conexao: service.listar_mensagens_chamado(conexao, usuario, id_atendimento)
    )


@router.post(
    "/chamados/{id_atendimento}/mensagens",
    response_model=MensagemChamadoCliente,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar mensagem em um chamado do cliente logado",
)
def enviar_mensagem_chamado(
    id_atendimento: UUID,
    dados: MensagemChamadoCriacao,
    usuario: UsuarioDep,
    executar: ExecutarDep,
):
    return executar(
        lambda conexao: service.enviar_mensagem_chamado(
            conexao,
            usuario,
            id_atendimento,
            dados.texto,
        )
    )


@router.post(
    "/pedidos",
    response_model=PedidoCliente,
    status_code=status.HTTP_201_CREATED,
    summary="Fechar pedido do cliente logado",
)
def criar_pedido(
    dados: CheckoutCriacao,
    usuario: UsuarioDep,
    executar: ExecutarDep,
    chave_idempotencia: ChaveIdempotencia = None,
):
    payload = dados.model_dump()
    return executar(
        lambda conexao: service.criar_checkout(
            conexao,
            usuario,
            payload,
            chave_idempotencia=chave_idempotencia,
        )
    )
