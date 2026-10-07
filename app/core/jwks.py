"""Cache das chaves publicas (JWKS) com que o Supabase assina os tokens (ES256)."""

import threading
import time
from collections.abc import Callable

import httpx
from jwt import PyJWK, PyJWTError

from app.core.erros_auth import AutenticacaoIndisponivel, NaoAutenticado

TIMEOUT_BUSCA_SEGUNDOS = 5.0


class ProvedorChaves:
    """Guarda as chaves por `kid` e so rebusca o JWKS quando aparece um `kid` desconhecido.

    A rebusca acontece no maximo uma vez por `intervalo_minimo` (mesmo que a busca falhe),
    para um token com `kid` forjado nao virar uma enxurrada de requisicoes ao Supabase.
    """

    def __init__(
        self,
        url_jwks: str,
        *,
        buscar: Callable[[], object] | None = None,
        relogio: Callable[[], float] = time.monotonic,
        intervalo_minimo: float = 60.0,
    ) -> None:
        self._url = url_jwks
        self._buscar = buscar or self._buscar_http
        self._relogio = relogio
        self._intervalo_minimo = intervalo_minimo
        self._chaves: dict[str, PyJWK] = {}
        self._ultima_busca: float | None = None
        self._trava = threading.Lock()

    def obter_chave(self, kid: object) -> object:
        if not isinstance(kid, str) or not kid:
            raise NaoAutenticado()
        chave = self._chaves.get(kid)
        if chave is None:
            with self._trava:
                chave = self._chaves.get(kid)
                if chave is None and self._pode_buscar():
                    self._atualizar()
                    chave = self._chaves.get(kid)
        if chave is None:
            if not self._chaves:
                # Sem nenhuma chave em cache nao da para dizer que o token e invalido.
                raise AutenticacaoIndisponivel()
            raise NaoAutenticado()
        return chave.key

    def _pode_buscar(self) -> bool:
        if self._ultima_busca is None:
            return True
        return self._relogio() - self._ultima_busca >= self._intervalo_minimo

    def _atualizar(self) -> None:
        self._ultima_busca = self._relogio()
        try:
            brutas = self._buscar()["keys"]
            iterator = iter(brutas)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as erro:
            raise AutenticacaoIndisponivel() from erro

        novas: dict[str, PyJWK] = {}
        for bruta in iterator:
            if not isinstance(bruta, dict):
                continue
            if bruta.get("kty") != "EC" or bruta.get("alg", "ES256") != "ES256":
                continue
            kid = bruta.get("kid")
            if not isinstance(kid, str) or not kid:
                continue
            try:
                novas[kid] = PyJWK.from_dict(bruta, algorithm="ES256")
            except (PyJWTError, ValueError, TypeError):
                continue
        if not novas:
            raise AutenticacaoIndisponivel()
        self._chaves = novas

    def _buscar_http(self) -> object:
        resposta = httpx.get(self._url, timeout=TIMEOUT_BUSCA_SEGUNDOS)
        resposta.raise_for_status()
        return resposta.json()
