import json
import subprocess
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.vulto_integracao.importador import (
    ImportacaoVultoError,
    gravar_plano,
    validar_dsn_local_teste,
    validar_dsn_producao_supabase,
    validar_plano,
)


def _plano():
    return {
        "codigo_lote": "VULTO-VENDAS-ABC123",
        "pendencias": [],
        "pedidos": [
            {
                "numero_pedido": "VULTO-1",
                "id_loja": "loja-1",
                "id_cliente": "cliente-1",
                "id_status_pedido": "status-pago",
                "valor_total": Decimal("105.00"),
                "valor_frete": Decimal("15.00"),
                "canal_venda": "loja",
                "criado_em": "2025-01-01T10:00:00-03:00",
                "observacao": "Importado do Vulto; venda de origem 1.",
            }
        ],
        "itens_pedido": [
            {
                "numero_pedido": "VULTO-1",
                "id_variacao": "variacao-1",
                "quantidade": 1,
                "preco_unitario": Decimal("90.00"),
            }
        ],
    }


class CursorFalso:
    def __init__(self, existentes=(), falhar_itens=False):
        self.existentes = existentes
        self.falhar_itens = falhar_itens
        self.comandos = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, parametros=None):
        self.comandos.append((sql, parametros))
        if self.falhar_itens and "INSERT INTO public.item_pedido" in sql:
            raise RuntimeError("falha simulada no insert de itens")

    def fetchall(self):
        ultima_consulta = self.comandos[-1][0]
        if "SELECT numero_pedido FROM public.pedido" in ultima_consulta:
            return [(numero,) for numero in self.existentes]
        if "SELECT venda_id_origem, estado" in ultima_consulta:
            return []
        return []

    def fetchone(self):
        return (9001,)

    def executemany(self, sql, parametros):
        self.comandos.append((sql, parametros))


class ConexaoFalsa:
    def __init__(self, existentes=(), falhar_itens=False):
        self.cursor_falso = CursorFalso(existentes, falhar_itens)
        self.committed = False
        self.rolled_back = False

    @contextmanager
    def transaction(self):
        try:
            yield
            self.committed = True
        except Exception:
            self.rolled_back = True
            raise

    def cursor(self):
        return self.cursor_falso


def test_grava_pedido_e_itens_na_mesma_transacao():
    conexao = ConexaoFalsa()

    assert gravar_plano(conexao, _plano()) == {"pedidos": 1, "itens": 1, "pendencias": 0}
    assert conexao.committed is True
    assert conexao.rolled_back is False
    assert any("INSERT INTO public.importacao_lote" in sql for sql, _ in conexao.cursor_falso.comandos)


def test_recusa_pedido_ja_existente_e_faz_rollback():
    conexao = ConexaoFalsa(existentes=["VULTO-1"])

    with pytest.raises(ImportacaoVultoError, match="ja existem"):
        gravar_plano(conexao, _plano())

    assert conexao.rolled_back is True
    assert not any("INSERT INTO public.pedido" in sql for sql, _ in conexao.cursor_falso.comandos)


def test_falha_ao_inserir_item_reverte_pedido():
    conexao = ConexaoFalsa(falhar_itens=True)

    with pytest.raises(RuntimeError, match="falha simulada"):
        gravar_plano(conexao, _plano())

    assert conexao.rolled_back is True
    assert conexao.committed is False


def test_validacao_impede_total_que_nao_fecha_antes_da_transacao():
    plano = _plano()
    plano["pedidos"][0]["valor_total"] = Decimal("106.00")
    conexao = ConexaoFalsa()

    with pytest.raises(ImportacaoVultoError, match="nao fecham"):
        gravar_plano(conexao, plano)

    assert conexao.rolled_back is False
    assert conexao.cursor_falso.comandos == []


def test_valida_plano_sem_itens():
    plano = _plano()
    plano["itens_pedido"] = []

    with pytest.raises(ImportacaoVultoError, match="Pedido sem itens"):
        validar_plano(plano)


def test_aceita_e_grava_lote_so_com_vendas_pendentes():
    plano = {
        "codigo_lote": "VULTO-VENDAS-PENDENTE",
        "pedidos": [],
        "itens_pedido": [],
        "pendencias": [
            {
                "venda_id": "17",
                "status_origem": "concluida",
                "motivos": ["cliente:cpf_ausente"],
                "dados_origem": {"venda": {"id": 17}, "itens": []},
            }
        ],
    }
    conexao = ConexaoFalsa()

    assert gravar_plano(conexao, plano) == {"pedidos": 0, "itens": 0, "pendencias": 1}
    assert conexao.committed is True
    assert any(
        "INSERT INTO public.venda_importacao_pendente" in sql
        for sql, _ in conexao.cursor_falso.comandos
    )


def test_recusa_pendencia_sem_dados_de_origem():
    plano = {
        "codigo_lote": "VULTO-VENDAS-INVALIDO",
        "pedidos": [],
        "itens_pedido": [],
        "pendencias": [{"venda_id": "17", "motivos": ["sem cliente"]}],
    }

    with pytest.raises(ImportacaoVultoError, match="dados de origem"):
        validar_plano(plano)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u:p@supabase.co:5432/lorenzi_teste",
        "postgresql://u:p@localhost:5432/postgres",
        "mysql://u:p@localhost:5432/lorenzi_teste",
    ],
)
def test_recusa_dsn_remoto_ou_fora_de_teste(dsn):
    with pytest.raises(ImportacaoVultoError):
        validar_dsn_local_teste(dsn)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u:p@localhost:5432/lorenzi_teste",
        "postgres://u:p@127.0.0.1:5432/lorenzi_teste",
        "postgresql://u:p@[::1]:5432/lorenzi_teste",
    ],
)
def test_aceita_postgres_local_com_sufixo_teste(dsn):
    validar_dsn_local_teste(dsn)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u:p@db.projeto.supabase.co:5432/postgres",
        "postgresql://u:p@aws-0-sa-east-1.pooler.supabase.com:6543/postgres",
    ],
)
def test_aceita_dsn_remota_supabase_para_modo_producao(dsn):
    validar_dsn_producao_supabase(dsn)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u:p@localhost:5432/postgres",
        "postgresql://u:p@outro-host.example:5432/postgres",
        "postgresql://u:p@db.projeto.supabase.co:5432/lorenzi_teste",
    ],
)
def test_recusa_dsn_nao_produtiva_no_modo_producao(dsn):
    with pytest.raises(ImportacaoVultoError):
        validar_dsn_producao_supabase(dsn)


def test_cli_simula_sem_carregar_ambiente_ou_conectar(tmp_path):
    arquivo = tmp_path / "plano.json"
    arquivo.write_text(json.dumps(_plano(), default=str), encoding="utf-8")
    raiz = Path(__file__).resolve().parents[2]
    resultado = subprocess.run(
        [sys.executable, "scripts/importar_plano_vendas_vulto.py", str(arquivo)],
        cwd=raiz,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultado.returncode == 0
    assert "Nenhuma conexao ou gravacao realizada" in resultado.stdout


def test_cli_exige_confirmacao_antes_de_conectar(tmp_path):
    arquivo = tmp_path / "plano.json"
    arquivo.write_text(json.dumps(_plano(), default=str), encoding="utf-8")
    raiz = Path(__file__).resolve().parents[2]
    resultado = subprocess.run(
        [
            sys.executable,
            "scripts/importar_plano_vendas_vulto.py",
            str(arquivo),
            "--aplicar",
        ],
        cwd=raiz,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultado.returncode == 2
    assert "informe --aplicar e --confirmar-vulto" in resultado.stderr


def test_cli_producao_exige_confirmacao_dupla_antes_de_conectar(tmp_path):
    arquivo = tmp_path / "plano.json"
    arquivo.write_text(json.dumps(_plano(), default=str), encoding="utf-8")
    raiz = Path(__file__).resolve().parents[2]
    resultado = subprocess.run(
        [
            sys.executable,
            "scripts/importar_plano_vendas_vulto.py",
            str(arquivo),
            "--aplicar-producao",
        ],
        cwd=raiz,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultado.returncode == 2
    assert "informe --aplicar-producao e --confirmar-producao" in resultado.stderr
