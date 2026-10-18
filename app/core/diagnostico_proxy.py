"""TEMPORARIO: registra os cabecalhos de proxy que a Render entrega ao app (so em GET /health).

Serve para descobrir como o proxy monta o X-Forwarded-For e quantos saltos existem antes do app,
para o limite por IP confiar so no que o proxy escreve. Nao guarda token nem corpo. Remover depois.
"""

import logging
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

log = logging.getLogger("uvicorn.error")
CABECALHOS = frozenset(
    {
        b"x-forwarded-for",
        b"x-forwarded-proto",
        b"x-real-ip",
        b"true-client-ip",
        b"cf-connecting-ip",
        b"forwarded",
        b"via",
    }
)


class DiagnosticoDeProxy:
    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == "/health":
            vistos = [
                (nome.decode(), valor.decode("latin-1")[:200])
                for nome, valor in scope.get("headers", [])
                if nome in CABECALHOS
            ]
            log.warning("DIAG-PROXY client=%s cabecalhos=%s", scope.get("client"), vistos)
        await self.app(scope, receive, send)
