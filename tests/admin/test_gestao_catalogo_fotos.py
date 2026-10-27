import pytest
from pydantic import ValidationError

from app.gestao.schemas import PecaAlterada, PecaDoCatalogo


def test_edicao_aceita_url_de_foto_e_texto_alternativo():
    dados = PecaAlterada(
        imagem_url="https://projeto.supabase.co/storage/v1/object/public/catalogo-produtos/p/foto.webp",
        imagem_alt="Camisa azul",
    )
    assert str(dados.imagem_url).endswith("foto.webp")
    assert dados.imagem_alt == "Camisa azul"


def test_edicao_permite_limpar_foto_explicitamente():
    dados = PecaAlterada(imagem_url=None, imagem_alt=None)
    assert "imagem_url" in dados.model_fields_set
    assert "imagem_alt" in dados.model_fields_set


def test_edicao_rejeita_url_sem_http_ou_https():
    with pytest.raises(ValidationError):
        PecaAlterada(imagem_url="javascript:alert(1)")


def test_resposta_do_catalogo_inclui_foto():
    peca = PecaDoCatalogo(
        id_produto="a3c37560-8c52-4b91-a4b4-cb71c43fd5e0",
        nome="camisa azul",
        categoria="camisaria",
        imagem_url="https://projeto.supabase.co/storage/v1/object/public/catalogo-produtos/p/foto.webp",
        imagem_alt="Camisa azul",
        preco=300,
        skus=["CL-1"],
        variacoes=1,
        estoque_rede=1,
    )
    assert str(peca.imagem_url).endswith("foto.webp")
