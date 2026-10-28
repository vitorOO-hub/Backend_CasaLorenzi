"""Nenhum teste do assistente chama o Gemini de verdade para gerar embedding."""

import pytest

from app.assistente.cliente import embeddings


@pytest.fixture(autouse=True)
def _sem_embedding_real(monkeypatch):
    monkeypatch.setattr(embeddings, "vetorizador", lambda configuracoes: None)
