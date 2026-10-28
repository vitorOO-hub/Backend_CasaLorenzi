"""Rotas do assistente do vendedor (`/api/v1/assistente/vendedor`).

Sempre exigem token valido e o papel `vendedor` (`requer_papel`). Quem e a pessoa, a loja e o dono
da conversa vem do token; o corpo so traz o texto da pergunta. Conversa de outra pessoa e 404.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.assistente.vendedor import service as vendedor
from app.assistente.vendedor.provedores import provedor_para
from app.assistente.vendedor.schemas import (
    AlteracaoDaConversa,
    AvaliacaoDaResposta,
    Conversa,
    ListaDeConversas,
    MensagensDaConversa,
    NovaMensagem,
    RespostaDoAssistente,
)
from app.core.config import Settings, get_settings
from app.core.db import ExecutarDep
from app.core.papeis import UsuarioAtual
from app.core.security import requer_papel

router = APIRouter(prefix="/assistente/vendedor", tags=["assistente-vendedor"])

UsuarioDep = Annotated[UsuarioAtual, Depends(requer_papel(*vendedor.PAPEIS_DO_ASSISTENTE))]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_fabrica_de_provedor() -> vendedor.FabricaDeProvedor:
    """Trocada nos testes por um provedor falso: os testes nunca chamam Groq nem Gemini."""
    return provedor_para


FabricaDep = Annotated[vendedor.FabricaDeProvedor, Depends(get_fabrica_de_provedor)]


@router.post(
    "/conversas",
    response_model=Conversa,
    status_code=status.HTTP_201_CREATED,
    summary="Novo chat",
)
def criar_conversa(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: vendedor.criar_conversa(conexao, usuario))


@router.get("/conversas", response_model=ListaDeConversas, summary="Conversas do vendedor")
def listar_conversas(usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: vendedor.listar_conversas(conexao, usuario))


@router.get(
    "/conversas/{id_conversa}/mensagens",
    response_model=MensagensDaConversa,
    summary="Mensagens de uma conversa",
)
def mensagens(id_conversa: UUID, usuario: UsuarioDep, executar: ExecutarDep):
    return executar(lambda conexao: vendedor.mensagens(conexao, usuario, id_conversa))


@router.post(
    "/conversas/{id_conversa}/mensagens",
    response_model=RespostaDoAssistente,
    summary="Perguntar ao assistente",
)
def perguntar(
    id_conversa: UUID,
    dados: NovaMensagem,
    usuario: UsuarioDep,
    executar: ExecutarDep,
    configuracoes: SettingsDep,
    fabrica: FabricaDep,
):
    return executar(
        lambda conexao: vendedor.enviar_mensagem(
            conexao,
            usuario,
            id_conversa,
            dados.texto,
            configuracoes=configuracoes,
            fabrica=fabrica,
        )
    )


@router.put(
    "/conversas/{id_conversa}/mensagens/{id_mensagem}/avaliacao",
    response_model=AvaliacaoDaResposta,
    summary="Avaliar uma resposta (util ou nao)",
)
def avaliar_resposta(
    id_conversa: UUID,
    id_mensagem: UUID,
    dados: AvaliacaoDaResposta,
    usuario: UsuarioDep,
    executar: ExecutarDep,
):
    executar(
        lambda conexao: vendedor.avaliar_resposta(
            conexao, usuario, id_conversa, id_mensagem, dados.avaliacao
        )
    )
    return dados


@router.patch(
    "/conversas/{id_conversa}", response_model=Conversa, summary="Arquivar ou desarquivar"
)
def alterar_conversa(
    id_conversa: UUID, dados: AlteracaoDaConversa, usuario: UsuarioDep, executar: ExecutarDep
):
    return executar(
        lambda conexao: vendedor.alterar_conversa(
            conexao, usuario, id_conversa, arquivada=dados.arquivada
        )
    )
