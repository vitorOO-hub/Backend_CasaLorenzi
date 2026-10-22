"""Consulta segura das vendas Vulto aguardando resolucao administrativa."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual

CONTAR = text(
    "SELECT count(*) FROM venda_importacao_pendente WHERE origem = 'vulto' AND estado = 'pendente'"
)

# Nao selecionar dados_origem: o JSON interno pode conter CPF, telefone ou e-mail.
LISTAR = text(
    """
    SELECT id_venda_pendente, venda_id_origem, status_origem, motivos,
           quantidade_itens, criada_em
    FROM venda_importacao_pendente
    WHERE origem = 'vulto' AND estado = 'pendente'
    ORDER BY criada_em, venda_id_origem
    LIMIT :limite OFFSET :offset
    """
)


def listar(
    conexao: Connection, usuario: UsuarioAtual, *, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao()
    total = int(conexao.execute(CONTAR).scalar_one())
    linhas = conexao.execute(LISTAR, {"limite": limit, "offset": offset}).mappings()
    return {
        "total": total,
        "itens": [
            {
                "id_venda_pendente": linha["id_venda_pendente"],
                "venda_id_origem": linha["venda_id_origem"],
                "status_origem": linha["status_origem"],
                "motivos": list(linha["motivos"]),
                "quantidade_itens": int(linha["quantidade_itens"]),
                "criada_em": linha["criada_em"],
            }
            for linha in linhas
        ],
    }
