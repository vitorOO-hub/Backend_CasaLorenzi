"""Assistente para quem navega sem login.

Mesmo roteador (`planejar_pergunta`) e mesmos provedores do assistente do cliente, mas so com dados
publicos do catalogo: busca de peca, estoque e lojas. Pontos, pedidos, sacola e equipe dependem da
conta; nesses casos a resposta pede o login (o site mostra o formulario no proprio chat) e, depois
de entrar, a conversa segue pelo assistente do cliente com o mesmo historico.

Nada e gravado no banco (a conversa nao tem dono). O historico vem do navegador, limitado, e e
tratado como dado. Como a rota e publica, alem do limite por minuto da borda (app/core/protecoes.py)
ha um teto diario por IP, em memoria de cada instancia do servidor.
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from typing import Any

from sqlalchemy.engine import Connection

from app.assistente.cliente.erros import LimiteDiarioDoAssistente
from app.assistente.cliente.ferramentas import DECLARACOES, FerramentasVisitante
from app.assistente.cliente.provedor import ErroProvedor, criar_provedor
from app.assistente.cliente.service import (
    LIMITE_CARACTERES_RESPOSTA,
    LIMITE_HISTORICO,
    MAX_RODADAS_FERRAMENTA,
    MAX_TOKENS_SAIDA,
    PROMPT_SISTEMA,
    TEXTO_ESCLARECER,
    TEXTO_INDISPONIVEL,
    FabricaProvedor,
    _motivo_para_passar,
)
from app.assistente.roteamento import planejar_pergunta
from app.core.config import Settings

log = logging.getLogger(__name__)

LIMITE_DIARIO_POR_IP = 20

PROMPT_VISITANTE = (
    PROMPT_SISTEMA
    + """
Esta pessoa NAO entrou na conta. Voce pode buscar pecas, ver estoque e informar as lojas. Pontos, \
pedidos, sacola e falar com a equipe precisam de login: se a ferramenta devolver precisa_login, \
diga que ela pode entrar ali mesmo no chat, com e-mail ou CPF e senha.
"""
)

TEXTO_PRECISA_LOGIN = (
    "Para isso eu preciso que você entre na sua conta. Use seu e-mail ou CPF e sua senha aqui "
    "mesmo, e eu continuo de onde paramos."
)
TEXTO_SEM_RESPOSTA = (
    "Não consegui responder isso com segurança. Entre na sua conta aqui mesmo (e-mail ou CPF e "
    "senha) que eu passo a conversa para a nossa equipe, com o resumo do que falamos."
)


class ContadorDiario:
    """Mensagens de visitante por IP no dia. Em memoria: vale por instancia do servidor."""

    def __init__(self, limite: int = LIMITE_DIARIO_POR_IP) -> None:
        self.limite = limite
        self._dia = date.today()
        self._contagem: dict[str, int] = {}
        self._trava = threading.Lock()

    def registrar(self, ip: str, hoje: date | None = None) -> None:
        hoje = hoje or date.today()
        with self._trava:
            if hoje != self._dia:
                self._dia, self._contagem = hoje, {}
            if self._contagem.get(ip, 0) >= self.limite:
                raise LimiteDiarioDoAssistente()
            self._contagem[ip] = self._contagem.get(ip, 0) + 1


CONTADOR = ContadorDiario()


def responder(
    conexao: Connection,
    texto: str,
    historico: list[dict[str, str]],
    *,
    configuracoes: Settings,
    fabrica: FabricaProvedor = criar_provedor,
) -> dict[str, Any]:
    plano = planejar_pergunta(texto, configuracoes)
    if plano.estado == "esclarecer":
        return _resposta(TEXTO_ESCLARECER)
    if plano.estado != "pronto" or plano.destino is None:
        log.warning("assistente do visitante sem modelo utilizavel: %s", plano.estado)
        return _resposta(TEXTO_INDISPONIVEL, sem_resposta=True)

    destino = plano.destino
    mensagens = [{"papel": m["autor"], "texto": m["texto"]} for m in historico[-LIMITE_HISTORICO:]]
    ferramentas = FerramentasVisitante(conexao)
    try:
        resposta = fabrica(destino, configuracoes).responder(
            modelo=destino.modelo,
            sistema=PROMPT_VISITANTE,
            historico=[*mensagens, {"papel": "usuario", "texto": texto}],
            ferramentas=DECLARACOES,
            executar=ferramentas.executar,
            max_rodadas=MAX_RODADAS_FERRAMENTA,
            max_tokens=MAX_TOKENS_SAIDA,
        )
    except ErroProvedor as erro:
        log.warning("provedor do assistente do visitante falhou: %s", erro)
        if erro.motivo == "chave ausente":
            return _resposta(TEXTO_INDISPONIVEL, sem_resposta=True)
        return _resposta(TEXTO_SEM_RESPOSTA, sem_resposta=True, precisa_login=True)

    # Pedido da conta: texto fixo, para o site sempre mostrar o login (nao depende do modelo).
    if ferramentas.precisa_login:
        return _resposta(TEXTO_PRECISA_LOGIN, precisa_login=True)
    texto_final = resposta.texto.strip()[:LIMITE_CARACTERES_RESPOSTA]
    if _motivo_para_passar(resposta, texto_final, plano):
        # Sem conta nao ha chamado: depois do login, o assistente do cliente passa para a equipe.
        return _resposta(TEXTO_SEM_RESPOSTA, sem_resposta=True, precisa_login=True)
    return _resposta(texto_final)


def _resposta(texto: str, *, sem_resposta: bool = False, precisa_login: bool = False) -> dict:
    return {"resposta": texto, "sem_resposta": sem_resposta, "precisa_login": precisa_login}
