from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import vendas_pendentes


class ResultadoContagem:
    def scalar_one(self):
        return 1


class ResultadoLinhas:
    def mappings(self):
        return [
            {
                "id_venda_pendente": uuid4(),
                "venda_id_origem": "123",
                "status_origem": "concluida",
                "motivos": ["cliente:cpf_ausente"],
                "quantidade_itens": 2,
                "criada_em": datetime(2026, 10, 22, tzinfo=timezone.utc),
            }
        ]


class ConexaoFalsa:
    def __init__(self):
        self.projecoes = []

    def execute(self, consulta, parametros=None):
        sql = str(consulta)
        if "count(*)" in sql:
            return ResultadoContagem()
        self.projecoes.append(sql.split("FROM", 1)[0])
        return ResultadoLinhas()


def test_resumo_de_pendencias_nao_consulta_payload_com_dados_pessoais():
    conexao = ConexaoFalsa()
    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.ADMIN)

    resposta = vendas_pendentes.listar(conexao, usuario)

    assert resposta["total"] == 1
    assert resposta["itens"][0]["venda_id_origem"] == "123"
    assert "dados_origem" not in str(resposta)
    assert all("dados_origem" not in projecao for projecao in conexao.projecoes)


def test_nao_admin_nao_lista_vendas_pendentes():
    usuario = UsuarioAtual(id_auth=uuid4(), papel=Papel.GERENTE_LOJA)

    with pytest.raises(SemPermissao):
        vendas_pendentes.listar(ConexaoFalsa(), usuario)
