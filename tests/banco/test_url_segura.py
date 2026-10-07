import pytest

from tests.banco.conftest import VARIAVEL_URL, url_de_teste_segura

URL_LOCAL = "postgresql://postgres:senha-local@127.0.0.1:5432/lorenzi_teste"


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    monkeypatch.delenv(VARIAVEL_URL, raising=False)


def test_sem_variavel_devolve_none():
    assert url_de_teste_segura(arquivo_env=None) is None


@pytest.mark.parametrize(
    "url",
    [
        URL_LOCAL,
        "postgresql://postgres:senha-local@localhost:5432/outro_teste",
        "postgresql://postgres:senha-local@[::1]:5432/lorenzi_teste",
    ],
)
def test_aceita_host_local_e_banco_de_teste(monkeypatch, url):
    monkeypatch.setenv(VARIAVEL_URL, url)
    assert url_de_teste_segura(arquivo_env=None) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:segredo@db.abcdefghijkl.supabase.co:5432/lorenzi_teste",
        "postgresql://postgres.abc:segredo@aws-0-sa-east-1.pooler.supabase.com:6543/postgres",
        "postgresql://postgres:segredo@10.0.0.5:5432/lorenzi_teste",
    ],
)
def test_recusa_host_que_nao_e_local_sem_vazar_a_senha(monkeypatch, url):
    monkeypatch.setenv(VARIAVEL_URL, url)
    with pytest.raises(RuntimeError) as erro:
        url_de_teste_segura(arquivo_env=None)
    assert "segredo" not in str(erro.value)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:segredo@127.0.0.1:5432/postgres",
        "postgresql://postgres:segredo@localhost:5432/lorenzi",
    ],
)
def test_recusa_banco_cujo_nome_nao_termina_em_teste(monkeypatch, url):
    monkeypatch.setenv(VARIAVEL_URL, url)
    with pytest.raises(RuntimeError) as erro:
        url_de_teste_segura(arquivo_env=None)
    assert "segredo" not in str(erro.value)


def test_le_do_arquivo_env_quando_a_variavel_nao_existe(tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text(f"OUTRA=1\n{VARIAVEL_URL}={URL_LOCAL}\n", encoding="utf-8")
    assert url_de_teste_segura(arquivo_env=arquivo) == URL_LOCAL


def test_ambiente_tem_precedencia_sobre_o_arquivo_env(monkeypatch, tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text(f"{VARIAVEL_URL}={URL_LOCAL}\n", encoding="utf-8")
    do_ambiente = "postgresql://postgres:senha-local@127.0.0.1:5432/ambiente_teste"
    monkeypatch.setenv(VARIAVEL_URL, do_ambiente)
    assert url_de_teste_segura(arquivo_env=arquivo) == do_ambiente


def test_arquivo_env_apontando_para_banco_remoto_tambem_e_recusado(tmp_path):
    arquivo = tmp_path / ".env"
    remoto = "postgresql://postgres:segredo@db.abc.supabase.co:5432/lorenzi_teste"
    arquivo.write_text(f"{VARIAVEL_URL}={remoto}\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        url_de_teste_segura(arquivo_env=arquivo)
