"""Protecoes de borda da API: limite de requisicoes e cabecalhos de seguranca.

Sao middlewares ASGI puros (sem dependencia nova). O limite e em memoria e vale por instancia do
servidor; se o backend passar a rodar em varias instancias, o armazenamento precisa ir para um
Redis (CLAUDE.md, secao 12.5).
"""

import hashlib
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

JANELA_SEGUNDOS = 60.0
ISENTOS = frozenset({"/health"})
# Escritas que criam coisas caras ou irreversiveis: limite bem menor.
ESCRITAS_SENSIVEIS = frozenset(
    {
        "/api/v1/cliente/pedidos",
        "/api/v1/cliente/chamados",
        "/api/v1/cliente/agendamentos",
    }
)
MENSAGEM_429 = "Muitas requisicoes em pouco tempo. Aguarde um instante e tente de novo."


class LimitadorDeRequisicoes:
    """Janela deslizante de 60 s por pessoa (hash do token) e por tipo de operacao.

    - leitura (GET/HEAD): `leitura` por minuto;
    - escrita (POST/PUT/PATCH/DELETE): `escrita` por minuto;
    - escrita sensivel (checkout, abrir chamado, agendar): `sensivel` por minuto;
    - sem token: `anonimo` por minuto no total (so o catalogo publico responde sem login).

    O chaveamento por token (e nao por IP) evita que todas as pessoas atras do proxy do Render
    pareçam um IP so. A pessoa renova o token a cada hora, e o contador recomeca junto.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        leitura: int = 120,
        escrita: int = 30,
        sensivel: int = 10,
        anonimo: int = 300,
        ativo: bool = True,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.limites = {"leitura": leitura, "escrita": escrita, "sensivel": sensivel}
        self.anonimo = anonimo
        self.ativo = ativo
        self.relogio = relogio
        self._janelas: dict[str, deque[float]] = {}
        self._chamadas = 0

    # ---------------------------------------------------------------- regra

    def _tipo(self, metodo: str, caminho: str) -> str:
        if metodo in ("GET", "HEAD"):
            return "leitura"
        if metodo == "POST" and caminho.rstrip("/") in ESCRITAS_SENSIVEIS:
            return "sensivel"
        return "escrita"

    @staticmethod
    def _quem(scope: Scope) -> str | None:
        for nome, valor in scope.get("headers", []):
            if nome == b"authorization":
                token = valor.decode("latin-1").strip()
                if token.lower().startswith("bearer ") and len(token) > 7:
                    return "t:" + hashlib.sha256(token[7:].encode()).hexdigest()[:24]
        return None

    def _permitir(self, chave: str, limite: int) -> float | None:
        """None = pode passar; senao, segundos ate liberar."""
        agora = self.relogio()
        janela = self._janelas.setdefault(chave, deque())
        while janela and agora - janela[0] >= JANELA_SEGUNDOS:
            janela.popleft()
        if len(janela) >= limite:
            return max(1.0, JANELA_SEGUNDOS - (agora - janela[0]))
        janela.append(agora)
        self._chamadas += 1
        if self._chamadas % 2000 == 0:
            self._limpar(agora)
        return None

    def _limpar(self, agora: float) -> None:
        vazias = [k for k, j in self._janelas.items() if not j or agora - j[-1] >= JANELA_SEGUNDOS]
        for chave in vazias:
            self._janelas.pop(chave, None)

    # ---------------------------------------------------------------- ASGI

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.ativo:
            await self.app(scope, receive, send)
            return
        metodo, caminho = scope["method"], scope["path"]
        if metodo == "OPTIONS" or caminho in ISENTOS:
            await self.app(scope, receive, send)
            return
        tipo = self._tipo(metodo, caminho)
        quem = self._quem(scope)
        if quem is None:
            espera = self._permitir("anonimo", self.anonimo)
        else:
            espera = self._permitir(f"{quem}:{tipo}", self.limites[tipo])
        if espera is None:
            await self.app(scope, receive, send)
            return
        corpo = json.dumps({"detail": MENSAGEM_429}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(corpo)).encode()),
                    (b"retry-after", str(int(espera) + 1).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": corpo})


CABECALHOS_DE_SEGURANCA: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
]


class CabecalhosDeSeguranca:
    """Acrescenta os cabecalhos de seguranca a toda resposta (a API so devolve JSON privado)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def com_cabecalhos(mensagem: MutableMapping[str, Any]) -> None:
            if mensagem["type"] == "http.response.start":
                existentes = {nome for nome, _ in mensagem.get("headers", [])}
                extras = [h for h in CABECALHOS_DE_SEGURANCA if h[0] not in existentes]
                mensagem["headers"] = [*mensagem.get("headers", []), *extras]
            await send(mensagem)

        await self.app(scope, receive, com_cabecalhos)
