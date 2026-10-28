"""A API nao usa consultas preparadas no servidor (o pooler do Supabase reveza as conexoes)."""

from app.core import db


def test_engine_desliga_o_preparo_de_consultas(monkeypatch):
    recebidos = {}

    def criar(url, **kwargs):
        recebidos.update(kwargs)
        return object()

    monkeypatch.setattr(db, "create_engine", criar)
    db.criar_engine.cache_clear()
    try:
        db.criar_engine("postgresql://usuario:senha@localhost:6543/postgres")
    finally:
        db.criar_engine.cache_clear()
    assert recebidos["connect_args"] == {"prepare_threshold": None}
    assert recebidos["pool_pre_ping"] is True
