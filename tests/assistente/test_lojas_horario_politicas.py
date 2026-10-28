"""Loja citada na conversa, horario de atendimento e politicas oficiais do assistente do cliente."""

import re
from datetime import datetime
from uuid import uuid4

import pytest

from app.assistente.cliente import ferramentas, lojas, politicas
from app.assistente.cliente.ferramentas import Ferramentas
from app.cliente import beneficios, resgate_pontos
from app.cliente.repositorio import CATEGORIAS_VULTO_MAIS
from app.cliente.vencimento_pontos import SP
from app.core.horario import aberta, descrever, proxima_abertura
from app.core.papeis import UsuarioAtual

SEMANA = {
    d: {"abre": "10:00", "fecha": "19:00"} for d in ("seg", "ter", "qua", "qui", "sex", "sab")
}


def _loja(nome, horario=None):
    return {"id_loja": uuid4(), "nome": nome, "horario_funcionamento": horario}


REDE = [
    _loja("vulto batel", SEMANA),
    _loja("casa lorenzi batel", SEMANA),
    _loja("casa lorenzi ibirapuera", SEMANA),
    _loja("e-commerce casa lorenzi", SEMANA),
    _loja("cd curitiba"),
    _loja("vulto e-commerce"),
    _loja("vulto app"),
    _loja("casa lorenzi"),
]


def _nome(achada):
    return achada.nome if achada else None


# ------------------------------------------------------------------ loja citada pelo cliente


@pytest.mark.parametrize(
    ("falas", "esperada"),
    [
        (["comprei na loja do Ibirapuera e veio com defeito"], "casa lorenzi ibirapuera"),
        (["fui na Vulto do Batel ontem"], "vulto batel"),
        (["a casa lorenzi do batel abre domingo?"], "casa lorenzi batel"),
        (["meu pedido do site nao chegou"], "e-commerce casa lorenzi"),
        (["comprei pelo e-commerce"], "e-commerce casa lorenzi"),
        # Batel tem duas lojas e o cliente nao disse a marca: fila geral.
        (["vou passar no batel"], None),
        # Duas lojas diferentes na mesma conversa: fila geral.
        (["comprei no ibirapuera", "mas quero trocar na vulto batel"], None),
        # Nenhuma loja citada.
        (["quero falar com uma pessoa"], None),
        (["sou cliente da casa lorenzi"], None),
    ],
)
def test_identifica_a_loja_so_quando_o_cliente_aponta_uma(falas, esperada):
    assert _nome(lojas.identificar(falas, REDE)) == esperada


def test_cd_e_canais_antigos_nunca_recebem_chamado():
    nomes = {c.nome for c in lojas.candidatas(REDE)}
    assert nomes == {
        "vulto batel",
        "casa lorenzi batel",
        "casa lorenzi ibirapuera",
        "e-commerce casa lorenzi",
    }


# ------------------------------------------------------------------ horario


def test_descrever_aberta_e_proxima_abertura():
    assert descrever(SEMANA).endswith("sab 10:00-19:00, dom fechada")
    assert descrever(None) is None
    quarta_meio_dia = datetime(2026, 10, 28, 12, 0, tzinfo=SP)
    assert aberta(SEMANA, quarta_meio_dia)
    assert not aberta(SEMANA, quarta_meio_dia.replace(hour=19))
    assert proxima_abertura(SEMANA, quarta_meio_dia.replace(hour=8)) == quarta_meio_dia.replace(
        hour=10
    )
    sabado_noite = datetime(2026, 10, 31, 20, 0, tzinfo=SP)
    assert proxima_abertura(SEMANA, sabado_noite) == datetime(2026, 11, 2, 10, 0, tzinfo=SP)


@pytest.mark.parametrize(
    ("agora", "esperado"),
    [
        (datetime(2026, 10, 28, 12, 0, tzinfo=SP), None),  # quarta, aberta
        (datetime(2026, 10, 28, 8, 0, tzinfo=SP), "responde hoje a partir das 10:00"),
        (datetime(2026, 10, 28, 21, 0, tzinfo=SP), "responde amanhã a partir das 10:00"),
        (datetime(2026, 10, 31, 20, 0, tzinfo=SP), "responde na segunda a partir das 10:00"),
    ],
)
def test_aviso_fora_do_horario(agora, esperado):
    aviso = lojas.aviso_fora_do_horario(REDE, agora)
    assert (aviso is None) if esperado is None else esperado in aviso


def test_aviso_da_loja_do_chamado_usa_o_horario_dela():
    so_domingo = {"dom": {"abre": "12:00", "fecha": "18:00"}}
    rede = [*REDE, _loja("vulto curitiba", so_domingo)]
    domingo = datetime(2026, 11, 1, 14, 0, tzinfo=SP)
    # Fila geral: a loja de domingo esta aberta, entao ha equipe.
    assert lojas.aviso_fora_do_horario(rede, domingo) is None
    # Chamado da Vulto Batel: fechada no domingo.
    batel = next(c for c in lojas.candidatas(rede) if c.nome == "vulto batel")
    assert "amanhã a partir das 10:00" in lojas.aviso_fora_do_horario(rede, domingo, batel.id_loja)


def test_sem_horario_cadastrado_nao_ha_aviso():
    rede = [_loja("vulto batel"), _loja("casa lorenzi ibirapuera")]
    assert lojas.aviso_fora_do_horario(rede, datetime(2026, 10, 28, 3, 0, tzinfo=SP)) is None


# ------------------------------------------------------------------ politicas oficiais

TEMAS = {
    "trocas",
    "devolucao",
    "defeito",
    "reembolso",
    "cancelamento",
    "frete",
    "prazo_entrega",
    "retirada",
    "pagamento",
    "ajustes",
    "lorenzi_mais",
}


def test_documento_tem_todos_os_temas_e_marca_os_pendentes():
    todas = politicas.todas()
    assert set(todas) == TEMAS
    assert {c for c, p in todas.items() if p.pendente} == {"prazo_entrega", "ajustes"}
    assert all(p.texto for p in todas.values())


def test_cabecalho_fora_do_formato_quebra_na_leitura():
    with pytest.raises(ValueError):
        politicas.ler("## Trocas sem codigo\ntexto")


def _reais(valor) -> str:
    return f"R$ {int(valor):,}".replace(",", ".")


def test_numeros_do_documento_batem_com_o_codigo():
    texto = "\n".join(p.texto for p in politicas.todas().values())
    assert f"a partir de {_reais(beneficios.FRETE_GRATIS_DA_LOJA)} em peças" in texto
    assert f"a partir de {_reais(beneficios.frete_gratis_a_partir('prata'))} em peças" in texto
    assert (
        beneficios.frete_gratis_a_partir("ouro") == beneficios.frete_gratis_a_partir("black") == 0
    )
    assert (
        f"Cada 100 pontos valem {_reais(resgate_pontos.REAIS_A_CADA_100_PONTOS)} de desconto"
        in texto
    )
    assert f"múltiplos de {resgate_pontos.MULTIPLO_DE_RESGATE} pontos" in texto
    loja, online = resgate_pontos.PONTOS_POR_REAL["loja"], resgate_pontos.PONTOS_POR_REAL["online"]
    assert f"rende {loja} ponto nas lojas físicas e {online} pontos nas compras pelo site" in texto
    for categoria, minimo in CATEGORIAS_VULTO_MAIS:
        if minimo:
            assert re.search(rf"{categoria} a partir de {minimo:,}".replace(",", "."), texto)
    assert "valem 365 dias" in texto


def test_ferramenta_devolve_o_texto_e_orienta_nos_pendentes():
    f = Ferramentas(None, UsuarioAtual(id_auth=uuid4()))
    trocas = f.executar("consultar_politica", {"tema": "trocas"})
    assert "30 dias" in trocas["texto"] and "orientacao" not in trocas
    prazo = f.executar("consultar_politica", {"tema": "prazo_entrega"})
    assert "transferir_para_atendente" in prazo["orientacao"]
    assert f.executar("consultar_politica", {"tema": "inventado"}) == {
        "erro": "argumentos_invalidos"
    }
    assert (
        set(
            next(d for d in ferramentas.DECLARACOES if d.nome == "consultar_politica").parametros[
                "properties"
            ]["tema"]["enum"]
        )
        == TEMAS
    )
