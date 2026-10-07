"""Regras transacionais simples do modulo de atendimento."""

from app.atendimento import repositorio
from app.core.repositorio import limpar_nulos, normalizar_id, normalizar_ids_no_dicionario


TABELAS_OPCOES = {
    "status": "status_atendimento",
    "categorias": "categoria_atendimento",
    "canais": "canal_atendimento",
    "prioridades": "prioridade_atendimento",
}


def preparar_dados(dados: dict[str, object]) -> dict[str, object]:
    return normalizar_ids_no_dicionario(limpar_nulos(dados))


def garantir_dados(dados: dict[str, object]) -> dict[str, object]:
    dados = preparar_dados(dados)
    if not dados:
        raise ValueError("Informe ao menos um campo para atualizar")
    return dados


def listar_opcoes(conexao, nome_opcao: str, *, limit: int, offset: int):
    return repositorio.listar_opcoes(conexao, TABELAS_OPCOES[nome_opcao], limit=limit, offset=offset)


def listar_atendimentos(conexao, *, limit: int, offset: int):
    return repositorio.listar_atendimentos(conexao, limit=limit, offset=offset)


def obter_atendimento(conexao, id_atendimento: str):
    return repositorio.obter_atendimento(conexao, normalizar_id(id_atendimento))


def criar_atendimento(conexao, dados: dict[str, object]):
    return repositorio.criar_atendimento(conexao, preparar_dados(dados))


def atualizar_atendimento(conexao, id_atendimento: str, dados: dict[str, object]):
    return repositorio.atualizar_atendimento(
        conexao,
        normalizar_id(id_atendimento),
        garantir_dados(dados),
    )


def atualizar_status(conexao, id_atendimento: str, dados: dict[str, object]):
    return repositorio.atualizar_atendimento(
        conexao,
        normalizar_id(id_atendimento),
        garantir_dados(dados),
    )


def atualizar_responsavel(conexao, id_atendimento: str, id_usuario_responsavel: str | int | None):
    dados: dict[str, object] = {"id_usuario_responsavel": None}
    if id_usuario_responsavel is not None:
        dados["id_usuario_responsavel"] = normalizar_id(id_usuario_responsavel)
    return repositorio.atualizar_atendimento(conexao, normalizar_id(id_atendimento), dados)


def listar_mensagens(conexao, id_atendimento: str):
    return repositorio.listar_mensagens(conexao, normalizar_id(id_atendimento))


def criar_mensagem(conexao, id_atendimento: str, dados: dict[str, object]):
    return repositorio.criar_mensagem(
        conexao,
        normalizar_id(id_atendimento),
        preparar_dados(dados),
    )


def listar_itens(conexao, id_atendimento: str):
    return repositorio.listar_itens_atendimento(conexao, normalizar_id(id_atendimento))


def vincular_item(conexao, id_atendimento: str, dados: dict[str, object]):
    return repositorio.vincular_item_atendimento(
        conexao,
        normalizar_id(id_atendimento),
        preparar_dados(dados),
    )


def criar_avaliacao(conexao, id_atendimento: str, dados: dict[str, object]):
    return repositorio.criar_avaliacao(
        conexao,
        normalizar_id(id_atendimento),
        limpar_nulos(dados),
    )
