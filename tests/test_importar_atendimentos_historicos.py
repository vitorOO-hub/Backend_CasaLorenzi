from scripts.importar_atendimentos_historicos import (
    NAMESPACE_ATENDIMENTOS,
    categoria_origem,
    classificar,
    telefone_nacional,
    uuid5,
)


def test_categorias_historicas_vindas_das_tags():
    assert categoria_origem("entrega;atraso") == "entrega"
    assert categoria_origem("pagamento;financeiro") == "pagamento"
    assert categoria_origem("troca;tamanho") == "troca_devolucao"
    assert categoria_origem("pr�-venda") == "produto"
    assert categoria_origem("vulto+;pontos") == "outro"
    assert categoria_origem("") == "outro"


def test_telefone_exige_numero_nacional_completo():
    assert telefone_nacional("+55 (11) 98765-4321") == "11987654321"
    assert telefone_nacional("98765-4321") == ""


def test_classificacao_deixa_cliente_sem_match_pendente():
    registros = [
        {
            "id": "101",
            "canal": "e-mail",
            "status": "aguardando cliente",
            "tags": "pagamento;financeiro",
            "mensagem": "Solicitacao historica",
        }
    ]
    referencias = {
        "canal_atendimento": {"email": "email-id"},
        "categoria_atendimento": {"pagamento": "pagamento-id"},
        "status_atendimento": {"aguardando_cliente": "status-id"},
    }
    prontos, pendencias = classificar(registros, {}, referencias)
    assert prontos == []
    assert pendencias == {"cliente_sem_correspondencia_exata": 1}


def test_id_de_origem_e_repetivel():
    assert uuid5(NAMESPACE_ATENDIMENTOS, "atendimento:101") == uuid5(
        NAMESPACE_ATENDIMENTOS, "atendimento:101"
    )
