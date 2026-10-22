import pytest

from scripts.vulto_integracao.clientes_vendas import (
    cpf_valido,
    indexar_compras_por_id,
    indexar_clientes_por_cpf,
    listar_vendas_pendentes_cliente,
    resolver_id_cliente_venda,
    resolver_cpf_venda,
)

CPF_VALIDO = "52998224725"


@pytest.mark.parametrize("cpf", [CPF_VALIDO, "529.982.247-25"])
def test_valida_cpf_com_e_sem_mascara(cpf):
    assert cpf_valido(cpf)


@pytest.mark.parametrize("cpf", ["", "00000000000", "52998224724", "1234567890"])
def test_rejeita_cpf_invalido(cpf):
    assert not cpf_valido(cpf)


def test_normaliza_cpf_numerico_do_excel_sem_tratar_decimal_zero_como_digito():
    assert cpf_valido(52998224725.0)


def test_resolve_cpf_da_compra_somente_com_vinculo_confirmado():
    indice = indexar_compras_por_id(
        [{"id": 42, "cpf_cliente_quando_identificavel": "529.982.247-25"}]
    )

    resultado = resolver_cpf_venda(
        {
            "cpf_padronizado": None,
            "compra_id_resolvida": 42,
            "situacao_vinculo_compra": "vinculado_confirmado",
        },
        indice,
    )

    assert resultado.cpf == CPF_VALIDO
    assert resultado.motivo == "cpf_de_compra_com_vinculo_confirmado"


def test_preserva_cpf_valido_da_venda_sem_substituir_pelo_da_compra():
    resultado = resolver_cpf_venda(
        {
            "cpf_padronizado": CPF_VALIDO,
            "compra_id_resolvida": "42",
            "situacao_vinculo_compra": "vinculado_confirmado",
        },
        {"42": "11144477735"},
    )

    assert resultado.cpf == CPF_VALIDO
    assert resultado.motivo == "cpf_da_venda"


def test_nao_usa_cpf_de_compra_com_vinculo_pendente():
    resultado = resolver_cpf_venda(
        {
            "compra_id_resolvida": "42",
            "situacao_vinculo_compra": "pendente_sem_compra_em_30s",
        },
        {"42": CPF_VALIDO},
    )

    assert resultado.cpf is None
    assert resultado.motivo == "vinculo_compra_pendente"


def test_nao_usa_compra_duplicada_ou_com_cpf_invalido():
    duplicada = indexar_compras_por_id(
        [
            {"id": "42", "cpf_cliente_quando_identificavel": CPF_VALIDO},
            {"id": "42", "cpf_cliente_quando_identificavel": CPF_VALIDO},
        ]
    )
    invalida = indexar_compras_por_id(
        [{"id": "43", "cpf_cliente_quando_identificavel": "52998224724"}]
    )

    assert duplicada["42"] is None
    assert invalida["43"] is None


def test_nao_resolve_sem_compra_ou_sem_id():
    sem_id = resolver_cpf_venda(
        {"situacao_vinculo_compra": "preexistente_nao_alterado"}, {"42": CPF_VALIDO}
    )
    nao_encontrada = resolver_cpf_venda(
        {
            "compra_id_resolvida": "99",
            "situacao_vinculo_compra": "preexistente_nao_alterado",
        },
        {"42": CPF_VALIDO},
    )

    assert sem_id.motivo == "sem_compra_id_resolvida"
    assert nao_encontrada.motivo == "compra_nao_encontrada"


def test_resolve_id_cliente_por_cpf_unico_cadastrado():
    clientes = indexar_clientes_por_cpf(
        [{"id_usuario": "cliente-1", "documento": CPF_VALIDO}]
    )

    id_cliente, resolucao = resolver_id_cliente_venda(
        {
            "compra_id_resolvida": "42",
            "situacao_vinculo_compra": "preexistente_nao_alterado",
        },
        {"42": CPF_VALIDO},
        clientes,
    )

    assert id_cliente == "cliente-1"
    assert resolucao.cpf == CPF_VALIDO


@pytest.mark.parametrize(
    ("clientes", "motivo"),
    [
        ([], "cliente_nao_encontrado_por_cpf"),
        (
            [
                {"id_usuario": "cliente-1", "documento": CPF_VALIDO},
                {"id_usuario": "cliente-2", "documento": CPF_VALIDO},
            ],
            "cpf_ambiguo_no_cadastro_de_clientes",
        ),
    ],
)
def test_nao_escolhe_cliente_ausente_ou_duplicado(clientes, motivo):
    indice = indexar_clientes_por_cpf(clientes)
    id_cliente, resolucao = resolver_id_cliente_venda(
        {
            "compra_id_resolvida": "42",
            "situacao_vinculo_compra": "vinculado_confirmado",
        },
        {"42": CPF_VALIDO},
        indice,
    )

    assert id_cliente is None
    assert resolucao.motivo == motivo


def test_indexa_somente_cliente_ativo_quando_mapeia_tipos():
    indice = indexar_clientes_por_cpf(
        [
            {
                "id_usuario": "cliente-1",
                "id_tipo_usuario": "tipo-cliente",
                "documento": CPF_VALIDO,
                "ativo": "true",
            },
            {
                "id_usuario": "atendente-1",
                "id_tipo_usuario": "tipo-atendente",
                "documento": "11144477735",
                "ativo": "true",
            },
            {
                "id_usuario": "cliente-inativo",
                "id_tipo_usuario": "tipo-cliente",
                "documento": "93541134780",
                "ativo": "false",
            },
        ],
        {"tipo-cliente": "cliente", "tipo-atendente": "atendente"},
    )

    assert indice == {CPF_VALIDO: "cliente-1"}


def test_lista_pendencias_nao_expoe_cpf():
    pendencias = listar_vendas_pendentes_cliente(
        [{"id": 123, "cpf_padronizado": "12345678900"}], {}, {}
    )

    assert pendencias == [
        {"venda_id": "123", "pendencia_cliente": "cpf_da_venda_invalido"}
    ]
