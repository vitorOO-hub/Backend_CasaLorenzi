"""Rotas administrativas: lojas, usuarios, catalogo e tabelas de opcoes."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.admin.erros import ReferenciaAdminInvalida, RegistroAdminDuplicado
from app.admin.schemas import (
    LojaAtualizacao,
    LojaCriacao,
    OpcaoComDescricaoAtualizacao,
    OpcaoComDescricaoCriacao,
    OpcaoSimplesAtualizacao,
    OpcaoSimplesCriacao,
    ProdutoAtualizacao,
    ProdutoCriacao,
    RegistroAdminLeitura,
    TipoMovimentacaoAtualizacao,
    TipoMovimentacaoCriacao,
    UsuarioAtualizacao,
    UsuarioCriacao,
    VariacaoProdutoAtualizacao,
    VariacaoProdutoCriacao,
)
from app.admin.service import TABELAS_OPCOES
from app.admin import service
from app.core.db import (
    ExecutarDep,
    eh_violacao_chave_estrangeira,
    eh_violacao_unicidade,
)

router = APIRouter(prefix="/admin", tags=["admin"])

Pagina = Query(default=20, ge=1, le=100)
Deslocamento = Query(default=0, ge=0)


def _dados(modelo) -> dict[str, object]:
    return modelo.model_dump(exclude_none=True)


def _tratar_erro_banco(erro: IntegrityError, recurso: str) -> None:
    if eh_violacao_unicidade(erro):
        raise RegistroAdminDuplicado(recurso) from erro
    if eh_violacao_chave_estrangeira(erro):
        raise ReferenciaAdminInvalida from erro
    raise erro


def _executar_com_tratamento(executar: ExecutarDep, operacao, recurso: str) -> Any:
    try:
        return executar(operacao)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except IntegrityError as erro:
        _tratar_erro_banco(erro, recurso)


@router.get("/lojas", response_model=list[RegistroAdminLeitura])
def listar_lojas(executar: ExecutarDep, limit: int = Pagina, offset: int = Deslocamento):
    return executar(lambda conexao: service.listar_lojas(conexao, limit=limit, offset=offset))


@router.get("/lojas/{id_loja}", response_model=RegistroAdminLeitura)
def obter_loja(id_loja: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_loja(conexao, id_loja))


@router.post("/lojas", status_code=status.HTTP_201_CREATED, response_model=RegistroAdminLeitura)
def criar_loja(dados: LojaCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_loja(conexao, _dados(dados)),
        "Loja",
    )


@router.patch("/lojas/{id_loja}", response_model=RegistroAdminLeitura)
def atualizar_loja(id_loja: str, dados: LojaAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_loja(conexao, id_loja, _dados(dados)),
        "Loja",
    )


@router.delete("/lojas/{id_loja}", response_model=RegistroAdminLeitura)
def desativar_loja(id_loja: str, executar: ExecutarDep):
    return executar(lambda conexao: service.desativar_loja(conexao, id_loja))


@router.get("/usuarios", response_model=list[RegistroAdminLeitura])
def listar_usuarios(executar: ExecutarDep, limit: int = Pagina, offset: int = Deslocamento):
    return executar(lambda conexao: service.listar_usuarios(conexao, limit=limit, offset=offset))


@router.get("/usuarios/{id_usuario}", response_model=RegistroAdminLeitura)
def obter_usuario(id_usuario: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_usuario(conexao, id_usuario))


@router.post("/usuarios", status_code=status.HTTP_201_CREATED, response_model=RegistroAdminLeitura)
def criar_usuario(dados: UsuarioCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_usuario(conexao, _dados(dados)),
        "Usuario",
    )


@router.patch("/usuarios/{id_usuario}", response_model=RegistroAdminLeitura)
def atualizar_usuario(id_usuario: str, dados: UsuarioAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_usuario(conexao, id_usuario, _dados(dados)),
        "Usuario",
    )


@router.delete("/usuarios/{id_usuario}", response_model=RegistroAdminLeitura)
def desativar_usuario(id_usuario: str, executar: ExecutarDep):
    return executar(lambda conexao: service.desativar_usuario(conexao, id_usuario))


@router.get("/produtos", response_model=list[RegistroAdminLeitura])
def listar_produtos(executar: ExecutarDep, limit: int = Pagina, offset: int = Deslocamento):
    return executar(lambda conexao: service.listar_produtos(conexao, limit=limit, offset=offset))


@router.get("/produtos/{id_produto}", response_model=RegistroAdminLeitura)
def obter_produto(id_produto: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_produto(conexao, id_produto))


@router.post("/produtos", status_code=status.HTTP_201_CREATED, response_model=RegistroAdminLeitura)
def criar_produto(dados: ProdutoCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_produto(conexao, _dados(dados)),
        "Produto",
    )


@router.patch("/produtos/{id_produto}", response_model=RegistroAdminLeitura)
def atualizar_produto(id_produto: str, dados: ProdutoAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_produto(conexao, id_produto, _dados(dados)),
        "Produto",
    )


@router.delete("/produtos/{id_produto}", response_model=RegistroAdminLeitura)
def desativar_produto(id_produto: str, executar: ExecutarDep):
    return executar(lambda conexao: service.desativar_produto(conexao, id_produto))


@router.get("/variacoes", response_model=list[RegistroAdminLeitura])
def listar_variacoes(executar: ExecutarDep, limit: int = Pagina, offset: int = Deslocamento):
    return executar(lambda conexao: service.listar_variacoes(conexao, limit=limit, offset=offset))


@router.get("/variacoes/{id_variacao}", response_model=RegistroAdminLeitura)
def obter_variacao(id_variacao: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_variacao(conexao, id_variacao))


@router.post("/variacoes", status_code=status.HTTP_201_CREATED, response_model=RegistroAdminLeitura)
def criar_variacao(dados: VariacaoProdutoCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_variacao(conexao, _dados(dados)),
        "Variacao",
    )


@router.patch("/variacoes/{id_variacao}", response_model=RegistroAdminLeitura)
def atualizar_variacao(id_variacao: str, dados: VariacaoProdutoAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_variacao(conexao, id_variacao, _dados(dados)),
        "Variacao",
    )


@router.delete("/variacoes/{id_variacao}", response_model=RegistroAdminLeitura)
def desativar_variacao(id_variacao: str, executar: ExecutarDep):
    return executar(lambda conexao: service.desativar_variacao(conexao, id_variacao))


@router.get("/{nome_opcao}", response_model=list[RegistroAdminLeitura])
def listar_opcoes(
    nome_opcao: str,
    executar: ExecutarDep,
    limit: int = Pagina,
    offset: int = Deslocamento,
):
    if nome_opcao not in TABELAS_OPCOES:
        raise HTTPException(status_code=404, detail="Opcao nao encontrada")
    return executar(
        lambda conexao: service.listar_opcoes(conexao, nome_opcao, limit=limit, offset=offset)
    )


@router.get("/{nome_opcao}/{id_registro}", response_model=RegistroAdminLeitura)
def obter_opcao(nome_opcao: str, id_registro: str, executar: ExecutarDep):
    return executar(lambda conexao: service.obter_opcao(conexao, nome_opcao, id_registro))


@router.post(
    "/tipos-usuario",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroAdminLeitura,
)
def criar_tipo_usuario(dados: OpcaoComDescricaoCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_opcao(conexao, "tipos-usuario", _dados(dados)),
        "Tipo de usuario",
    )


@router.patch("/tipos-usuario/{id_registro}", response_model=RegistroAdminLeitura)
def atualizar_tipo_usuario(id_registro: str, dados: OpcaoComDescricaoAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_opcao(conexao, "tipos-usuario", id_registro, _dados(dados)),
        "Tipo de usuario",
    )


@router.post(
    "/status-pedido",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroAdminLeitura,
)
def criar_status_pedido(dados: OpcaoComDescricaoCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_opcao(conexao, "status-pedido", _dados(dados)),
        "Status de pedido",
    )


@router.patch("/status-pedido/{id_registro}", response_model=RegistroAdminLeitura)
def atualizar_status_pedido(
    id_registro: str,
    dados: OpcaoComDescricaoAtualizacao,
    executar: ExecutarDep,
):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_opcao(conexao, "status-pedido", id_registro, _dados(dados)),
        "Status de pedido",
    )


@router.post(
    "/metodos-pagamento",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroAdminLeitura,
)
def criar_metodo_pagamento(dados: OpcaoSimplesCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_opcao(conexao, "metodos-pagamento", _dados(dados)),
        "Metodo de pagamento",
    )


@router.patch("/metodos-pagamento/{id_registro}", response_model=RegistroAdminLeitura)
def atualizar_metodo_pagamento(id_registro: str, dados: OpcaoSimplesAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_opcao(
            conexao,
            "metodos-pagamento",
            id_registro,
            _dados(dados),
        ),
        "Metodo de pagamento",
    )


@router.post(
    "/status-pagamento",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroAdminLeitura,
)
def criar_status_pagamento(dados: OpcaoSimplesCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_opcao(conexao, "status-pagamento", _dados(dados)),
        "Status de pagamento",
    )


@router.patch("/status-pagamento/{id_registro}", response_model=RegistroAdminLeitura)
def atualizar_status_pagamento(id_registro: str, dados: OpcaoSimplesAtualizacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_opcao(
            conexao,
            "status-pagamento",
            id_registro,
            _dados(dados),
        ),
        "Status de pagamento",
    )


@router.post(
    "/tipos-movimentacao-estoque",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistroAdminLeitura,
)
def criar_tipo_movimentacao(dados: TipoMovimentacaoCriacao, executar: ExecutarDep):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.criar_opcao(
            conexao,
            "tipos-movimentacao-estoque",
            _dados(dados),
        ),
        "Tipo de movimentacao de estoque",
    )


@router.patch("/tipos-movimentacao-estoque/{id_registro}", response_model=RegistroAdminLeitura)
def atualizar_tipo_movimentacao(
    id_registro: str,
    dados: TipoMovimentacaoAtualizacao,
    executar: ExecutarDep,
):
    return _executar_com_tratamento(
        executar,
        lambda conexao: service.atualizar_opcao(
            conexao,
            "tipos-movimentacao-estoque",
            id_registro,
            _dados(dados),
        ),
        "Tipo de movimentacao de estoque",
    )


@router.delete("/{nome_opcao}/{id_registro}", response_model=RegistroAdminLeitura)
def desativar_opcao(nome_opcao: str, id_registro: str, executar: ExecutarDep):
    return executar(lambda conexao: service.desativar_opcao(conexao, nome_opcao, id_registro))
