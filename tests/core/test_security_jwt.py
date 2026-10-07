import base64
import json
import time
from uuid import UUID, uuid4

import jwt
import pytest

from app.core.erros_auth import NaoAutenticado
from app.core.papeis import Papel, UsuarioAtual
from app.core.security import TAMANHO_MAXIMO_TOKEN, decodificar_token
from tests.auth_util import ISSUER, REMOVER, ParDeChaves, provedor_para


@pytest.fixture
def par() -> ParDeChaves:
    return ParDeChaves()


@pytest.fixture
def provedor(par):
    return provedor_para(par)


def validar(token, provedor) -> UsuarioAtual:
    return decodificar_token(token, provedor=provedor, issuer=ISSUER)


def adulterar(token: str, **claims) -> str:
    cabecalho, corpo, assinatura = token.split(".")
    dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
    dados.update(claims)
    novo = base64.urlsafe_b64encode(json.dumps(dados).encode()).rstrip(b"=").decode()
    return ".".join([cabecalho, novo, assinatura])


# ---- tokens validos ----------------------------------------------------------------------


def test_cliente_nao_tem_papel_nem_loja(par, provedor):
    sub = uuid4()
    usuario = validar(par.emitir(sub=str(sub)), provedor)
    assert usuario == UsuarioAtual(id_auth=sub)


def test_gerente_traz_papel_e_loja(par, provedor):
    sub, loja = uuid4(), uuid4()
    token = par.emitir(sub=str(sub), papel="gerente_loja", loja_id=str(loja))
    usuario = validar(token, provedor)
    assert usuario == UsuarioAtual(id_auth=sub, papel=Papel.GERENTE_LOJA, id_loja=loja)


def test_admin_nao_tem_loja(par, provedor):
    usuario = validar(par.emitir(papel="admin"), provedor)
    assert usuario.papel is Papel.ADMIN
    assert usuario.id_loja is None


# ---- ataques e tokens quebrados ----------------------------------------------------------


def test_token_expirado(par, provedor):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(exp=int(time.time()) - 10), provedor)


def test_audience_errada(par, provedor):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(aud="outro-publico"), provedor)


def test_issuer_errado(par, provedor):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(iss="https://invasor.example/auth/v1"), provedor)


@pytest.mark.parametrize("claim", ["exp", "sub", "aud", "iss"])
def test_claim_obrigatoria_ausente(par, provedor, claim):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(**{claim: REMOVER}), provedor)


def test_algoritmo_none_e_recusado(par, provedor):
    payload = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 900,
    }
    token = jwt.encode(payload, key=None, algorithm="none", headers={"kid": par.kid})
    with pytest.raises(NaoAutenticado):
        validar(token, provedor)


def test_algoritmo_hs256_e_recusado(par, provedor):
    payload = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "iss": ISSUER,
        "role": "authenticated",
        "exp": int(time.time()) + 900,
    }
    segredo = "um-segredo-qualquer-com-mais-de-trinta-e-dois-bytes"
    token = jwt.encode(payload, segredo, algorithm="HS256", headers={"kid": par.kid})
    with pytest.raises(NaoAutenticado):
        validar(token, provedor)


def test_payload_adulterado_invalida_a_assinatura(par, provedor):
    token = par.emitir(papel="atendente", loja_id=str(uuid4()))
    with pytest.raises(NaoAutenticado):
        validar(adulterar(token, papel="admin", loja_id=None), provedor)


def test_assinado_por_outra_chave_com_o_mesmo_kid(par, provedor):
    impostor = ParDeChaves(kid=par.kid)
    with pytest.raises(NaoAutenticado):
        validar(impostor.emitir(), provedor)


def test_kid_desconhecido(provedor):
    desconhecida = ParDeChaves(kid="outra-chave")
    with pytest.raises(NaoAutenticado):
        validar(desconhecida.emitir(), provedor)


def test_lixo_nao_e_token(provedor):
    with pytest.raises(NaoAutenticado):
        validar("isto-nao-e-um-jwt", provedor)


def test_token_grande_demais_e_recusado_sem_decodificar(provedor):
    with pytest.raises(NaoAutenticado):
        validar("a" * (TAMANHO_MAXIMO_TOKEN + 1), provedor)


# ---- claims incoerentes ------------------------------------------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        {"papel": "gerente_loja"},
        {"papel": "atendente"},
        {"papel": "operador_estoque"},
        {"papel": "admin", "loja_id": str(uuid4())},
        {"loja_id": str(uuid4())},
        {"papel": "superusuario", "loja_id": str(uuid4())},
        {"papel": ["admin"]},
        {"papel": "gerente_loja", "loja_id": "isto-nao-e-uuid"},
        {"role": "anon"},
        {"role": REMOVER},
        {"is_anonymous": True},
        {"sub": "nao-e-uuid"},
    ],
    ids=[
        "gerente-sem-loja",
        "atendente-sem-loja",
        "operador-sem-loja",
        "admin-com-loja",
        "cliente-com-loja",
        "papel-desconhecido",
        "papel-nao-string",
        "loja-invalida",
        "role-anon",
        "sem-role",
        "anonimo",
        "sub-invalido",
    ],
)
def test_claims_incoerentes_dao_401(par, provedor, claims):
    with pytest.raises(NaoAutenticado):
        validar(par.emitir(**claims), provedor)


def test_sub_e_devolvido_como_uuid(par, provedor):
    sub = uuid4()
    assert isinstance(validar(par.emitir(sub=str(sub)), provedor).id_auth, UUID)
