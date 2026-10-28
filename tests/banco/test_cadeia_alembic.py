from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.banco.conftest import RAIZ

NOVAS = [
    "20261007000000",
    "20261007000100",
    "20261007000200",
    "20261007000300",
    "20261007000400",
    "20261007000500",
    "20261007000600",
    "20261007103000",
    "20261007110000",
    "20261007120000",
    "20261007130000",
    "20261007143000",
    "20261007162000",
    "20261007170000",
    "20261007180000",
    "20261007190000",
    "20261007200000",
    "20261007210000",
    "20261008100000",
    "20261008110000",
    "20261014120000",
    "20261019120000",
    "20261020120000",
    "20261020130000",
    "20261021120000",
    "20261021130000",
    "20261021140000",
    "20261021150000",
    "20261022160000",
    "20261022170000",
    "20261022180000",
    "20261022190000",
    "20261022200000",
    "20261022210000",
    "20261023100000",
    "20261023110000",
    "20261023120000",
    "20261024100000",
    "20261024110000",
    "20261024120000",
    "20261027100000",
    "20261027120000",
]


def pasta_de_revisoes() -> ScriptDirectory:
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    return ScriptDirectory.from_config(config)


def test_ha_uma_unica_cabeca_e_e_a_ultima_revisao_nova():
    assert pasta_de_revisoes().get_heads() == [NOVAS[-1]]


def test_as_revisoes_novas_formam_uma_cadeia_linear_sobre_a_do_atendimento():
    pasta = pasta_de_revisoes()
    anterior = "20261006213000"
    for revisao in NOVAS:
        assert pasta.get_revision(revisao).down_revision == anterior
        anterior = revisao
