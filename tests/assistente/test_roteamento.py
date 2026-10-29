import pytest

from app.assistente.roteamento import classificar_pergunta, decidir_roteamento, planejar_pergunta

MODELOS = {
    "rapida": "groq:modelo-rapido-teste",
    "precisa": "gemini:modelo-preciso-teste",
}


def test_pergunta_direta_seleciona_modelo_rapido_sem_chamar_api():
    plano = decidir_roteamento(
        "Qual o horario da loja Savassi?",
        modelos_por_rota=MODELOS,
        chaves_disponiveis={"gemini": True, "groq": True},
    )

    assert plano.estado == "pronto"
    assert plano.classificacao.rota == "rapida"
    assert plano.destino is not None
    assert (plano.destino.provedor, plano.destino.modelo) == ("groq", "modelo-rapido-teste")


@pytest.mark.parametrize(
    "pergunta",
    [
        "Quais produtos indexados são de linho?",
        "Procure uma peça de linho leve.",
        "Quais cores existem no catálogo?",
    ],
)
def test_consulta_de_catalogo_exige_chamada_de_ferramenta(pergunta):
    assert classificar_pergunta(pergunta).requer_ferramenta


def test_pergunta_analitica_seleciona_modelo_preciso():
    plano = decidir_roteamento(
        "Compare as vendas dos meses e explique a diferenca.",
        modelos_por_rota=MODELOS,
        chaves_disponiveis={"gemini": True, "groq": True},
    )

    assert plano.estado == "pronto"
    assert plano.classificacao.rota == "precisa"
    assert plano.destino is not None
    assert (plano.destino.provedor, plano.destino.modelo) == ("gemini", "modelo-preciso-teste")


def test_pergunta_incompleta_nao_seleciona_modelo():
    plano = decidir_roteamento(
        "Tem essa peca na loja?",
        modelos_por_rota=MODELOS,
        chaves_disponiveis={"gemini": True, "groq": True},
    )

    assert plano.estado == "esclarecer"
    assert plano.destino is None


def test_rota_sem_modelo_configurado_nao_seleciona_destino():
    plano = decidir_roteamento(
        "Oi",
        modelos_por_rota={},
        chaves_disponiveis={"gemini": True, "groq": True},
    )

    assert plano.estado == "modelo_nao_configurado"
    assert plano.destino is None


def test_rota_sem_chave_do_provedor_nao_faz_fallback():
    plano = decidir_roteamento(
        "Oi",
        modelos_por_rota=MODELOS,
        chaves_disponiveis={"gemini": True, "groq": False},
    )

    assert plano.estado == "provedor_sem_chave"
    assert plano.destino is None


def test_destino_com_formato_invalido_nao_seleciona_modelo():
    plano = decidir_roteamento(
        "Oi",
        modelos_por_rota={"rapida": "openai:modelo"},
        chaves_disponiveis={"gemini": True, "groq": True},
    )

    assert plano.estado == "configuracao_invalida"
    assert plano.destino is None


def test_planejamento_usa_destinos_e_chaves_do_servidor():
    from app.core.config import Settings

    configuracoes = Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        assistente_modelo_rapido="groq:modelo-rapido",
        assistente_modelo_preciso="gemini:modelo-preciso",
        groq_api_key="chave-ficticia-groq",
        gemini_api_key="chave-ficticia-gemini",
    )

    plano = planejar_pergunta("Oi", configuracoes)

    assert plano.estado == "pronto"
    assert plano.destino is not None
    assert (plano.destino.provedor, plano.destino.modelo) == ("groq", "modelo-rapido")


@pytest.mark.parametrize(
    ("pergunta", "provedor", "modelo"),
    [
        ("Oi", "groq", "openai/gpt-oss-20b"),
        ("Compare as vendas dos meses e explique a diferenca.", "gemini", "gemini-3.5-flash-lite"),
    ],
)
def test_destinos_padrao_seguem_a_decisao_dos_provedores(pergunta, provedor, modelo):
    from app.core.config import Settings

    configuracoes = Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        groq_api_key="chave-ficticia-groq",
        gemini_api_key="chave-ficticia-gemini",
    )

    plano = planejar_pergunta(pergunta, configuracoes)

    assert plano.estado == "pronto"
    assert plano.destino is not None
    assert (plano.destino.provedor, plano.destino.modelo) == (provedor, modelo)


def test_chave_vazia_na_configuracao_nao_habilita_provedor():
    from app.core.config import Settings

    configuracoes = Settings(
        _env_file=None,
        database_url="postgresql://localhost/teste",
        assistente_modelo_rapido="groq:modelo-rapido",
        groq_api_key="   ",
    )

    plano = planejar_pergunta("Oi", configuracoes)

    assert plano.estado == "provedor_sem_chave"
    assert plano.destino is None


@pytest.mark.parametrize("campo", ["assistente_modelo_rapido", "assistente_modelo_preciso"])
def test_config_rejeita_destino_de_modelo_invalido(campo):
    from app.core.config import Settings

    with pytest.raises(ValueError, match="formato gemini:modelo ou groq:modelo"):
        Settings(
            _env_file=None,
            database_url="postgresql://localhost/teste",
            **{campo: "modelo-sem-provedor"},
        )
