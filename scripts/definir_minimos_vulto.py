"""Define estoque minimo 1 nas pecas das lojas fisicas da Vulto (hoje sem minimo nenhum).

Padroniza com a Casa Lorenzi pela regra, nao pelo numero: na Lorenzi o minimo fica em torno de
dois tercos do saldo medio por peca (saldo medio 5 a 8, minimo 2 a 5). Na Vulto o saldo medio e
1,8 a 2,4 por cor e tamanho, entao a mesma regra da minimo 1: o alerta sai na ultima peca.

- So as 4 lojas fisicas da Vulto; CD, e-commerce e app nao tem balcao para repor.
- So onde o minimo ainda e 0: nao troca minimo que alguem ja definiu pela tela.
- Fica de fora a categoria `pendente_identificacao` (peca sem cadastro identificado, saldo zero).
- Registra na auditoria, como a tela de estoque minimo faz.

    PYTHONPATH=. python scripts/definir_minimos_vulto.py              # simula
    PYTHONPATH=. python scripts/definir_minimos_vulto.py --aplicar    # grava
"""

import argparse

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import Settings
from app.core.db import abrir_conexao

MINIMO = 1
LOJAS = (
    "LOJA-VULTO-BATEL",
    "LOJA-VULTO-PINHEIROS",
    "LOJA-VULTO-SAVASSI",
    "LOJA-VULTO-SHOPPING-ELDORADO",
)
FORA = "pendente_identificacao"

DEFINIR = text(
    """
    WITH alterados AS (
        UPDATE estoque e
        SET estoque_minimo = :minimo, atualizado_em = now()
        FROM loja l, variacao_produto v, produto p
        WHERE l.id_loja = e.id_loja AND l.codigo = ANY(:lojas) AND l.ativa
          AND v.id_variacao = e.id_variacao AND v.ativa
          AND p.id_produto = v.id_produto AND p.ativo
          AND p.categoria IS DISTINCT FROM :fora
          AND e.estoque_minimo = 0
        RETURNING l.nome AS loja, e.quantidade
    )
    SELECT loja, count(*) AS pecas, count(*) FILTER (WHERE quantidade <= :minimo) AS em_alerta
    FROM alterados GROUP BY loja ORDER BY loja
    """
)

AUDITAR = text(
    """
    INSERT INTO auditoria (id_usuario, autor_nome, acao, detalhe)
    VALUES (NULL, 'Sistema', 'Definiu estoque mínimo', :detalhe)
    """
)


def definir(conexao: Connection) -> list[dict]:
    """Grava na transacao aberta (quem chama faz o commit) e devolve, por loja, quantas pecas
    receberam o minimo e quantas ja nascem em alerta (saldo <= minimo)."""
    linhas = [
        dict(linha)
        for linha in conexao.execute(
            DEFINIR, {"minimo": MINIMO, "lojas": list(LOJAS), "fora": FORA}
        ).mappings()
    ]
    for linha in linhas:
        conexao.execute(
            AUDITAR,
            {"detalhe": f"Minimo {MINIMO} em {linha['pecas']} peça(s) de {linha['loja']} (script)"},
        )
    return linhas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aplicar", action="store_true", help="grava (sem isso, desfaz no fim)")
    args = parser.parse_args()

    with abrir_conexao(Settings()) as conexao:
        linhas = definir(conexao)
        for linha in linhas:
            print(f"{linha['loja']}: {linha['pecas']} pecas, {linha['em_alerta']} ja em alerta")
        if not linhas:
            print("nada a alterar (as pecas ja tem minimo ou as lojas nao existem)")
        if args.aplicar:
            conexao.commit()
        else:
            conexao.rollback()
            print("(simulacao: nada foi gravado)")


if __name__ == "__main__":
    main()
