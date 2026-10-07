import httpx
import pytest

from app.core.erros_auth import AutenticacaoIndisponivel, NaoAutenticado
from app.core.jwks import ProvedorChaves
from tests.auth_util import URL_JWKS, ParDeChaves


class Relogio:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


def provedor_com(buscar, relogio=None) -> ProvedorChaves:
    return ProvedorChaves(URL_JWKS, buscar=buscar, relogio=relogio or Relogio())


def test_busca_a_chave_uma_vez_e_guarda_em_cache():
    par = ParDeChaves()
    chamadas = []

    def buscar():
        chamadas.append(1)
        return {"keys": [par.jwk]}

    provedor = provedor_com(buscar)
    assert provedor.obter_chave(par.kid) is not None
    assert provedor.obter_chave(par.kid) is not None
    assert len(chamadas) == 1


def test_kid_desconhecido_respeita_o_intervalo_minimo_entre_buscas():
    par = ParDeChaves()
    relogio = Relogio()
    chamadas = []

    def buscar():
        chamadas.append(1)
        return {"keys": [par.jwk]}

    provedor = provedor_com(buscar, relogio)
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("desconhecida")
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("desconhecida")
    assert len(chamadas) == 1

    relogio.agora += 61
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("desconhecida")
    assert len(chamadas) == 2


def test_chave_nova_aparece_depois_da_rotacao():
    antiga, nova = ParDeChaves("antiga"), ParDeChaves("nova")
    relogio = Relogio()
    respostas = [{"keys": [antiga.jwk]}, {"keys": [antiga.jwk, nova.jwk]}]

    provedor = provedor_com(lambda: respostas.pop(0), relogio)
    assert provedor.obter_chave("antiga") is not None
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("nova")

    relogio.agora += 61
    assert provedor.obter_chave("nova") is not None


def test_falha_de_rede_vira_autenticacao_indisponivel():
    def buscar():
        raise httpx.ConnectError("sem rede")

    with pytest.raises(AutenticacaoIndisponivel):
        provedor_com(buscar).obter_chave("qualquer")


def test_cache_vazio_apos_falha_de_rede_continua_indisponivel_dentro_do_intervalo():
    chamadas = []

    def buscar():
        chamadas.append(1)
        raise httpx.ConnectError("sem rede")

    provedor = provedor_com(buscar)
    with pytest.raises(AutenticacaoIndisponivel):
        provedor.obter_chave("qualquer")
    with pytest.raises(AutenticacaoIndisponivel):
        provedor.obter_chave("qualquer")
    assert len(chamadas) == 1


@pytest.mark.parametrize("corpo", [{"keys": []}, {}, {"keys": "lixo"}, []])
def test_resposta_sem_chaves_validas_vira_autenticacao_indisponivel(corpo):
    with pytest.raises(AutenticacaoIndisponivel):
        provedor_com(lambda: corpo).obter_chave("qualquer")


@pytest.mark.parametrize("kid", [None, "", 123, ["x"]])
def test_kid_ausente_ou_invalido_e_recusado_sem_buscar(kid):
    def buscar():
        raise AssertionError("nao deveria buscar")

    with pytest.raises(NaoAutenticado):
        provedor_com(buscar).obter_chave(kid)


def test_ignora_chaves_que_nao_sao_es256():
    par = ParDeChaves()
    simetrica = {"kty": "oct", "kid": "hmac", "k": "YWJj"}
    provedor = provedor_com(lambda: {"keys": [simetrica, par.jwk]})
    assert provedor.obter_chave(par.kid) is not None
    with pytest.raises(NaoAutenticado):
        provedor.obter_chave("hmac")
