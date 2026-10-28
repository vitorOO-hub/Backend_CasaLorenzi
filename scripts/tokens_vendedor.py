"""Estimativa de tokens de ENTRADA por pergunta de cliente, antes x depois (sem chamar modelo).

Mede o que vai em cada chamada (prompt de sistema + ferramentas + pergunta) com a regra de ~4
caracteres por token, e multiplica pelo numero de chamadas de cada caminho. O numero real de cada
pergunta feita no chat fica em `mensagem_assistente.tokens_entrada` / `tokens_saida`.

Uso (na raiz do backend):
    .venv/Scripts/python.exe scripts/tokens_vendedor.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.assistente.vendedor import (
    consulta_cliente,  # noqa: E402
    service,  # noqa: E402
)
from app.assistente.vendedor import ferramentas as f  # noqa: E402

# Resultado tipico de uma ferramenta devolvido ao modelo (estimado pelos formatos reais).
RESULTADO_ANTIGO = 180  # buscar_clientes / buscar_vendas / detalhe_venda
RESULTADO_NOVO = 60  # buscar_cliente compacto
RESULTADO_COMPRAS = 120  # busca + compras emendadas
HISTORICO_ANTIGO = 11 * 60  # ate 11 mensagens anteriores de ~60 tokens


def tokens(texto: str) -> int:
    return round(len(texto) / 4)


def _ferramentas(lista) -> int:
    return tokens(json.dumps([[x.nome, x.descricao, x.parametros] for x in lista]))


antes_base = tokens(service.SISTEMA) + _ferramentas(f.FERRAMENTAS) + HISTORICO_ANTIGO
depois_base = tokens(consulta_cliente.SISTEMA) + _ferramentas(f.FERRAMENTAS_DE_CLIENTE)

# (pergunta, chamadas e resultados antes, chamadas e resultados depois)
CASOS = [
    # Antes: busca de clientes + resposta (e o CPF nem vinha). Depois: 0 chamadas.
    ("qual o e-mail do cliente 123.456.789-01?", [0, RESULTADO_ANTIGO], []),
    # Nome: antes 2 chamadas; depois 1 (template responde apos a ferramenta).
    ("qual o CPF da Marina Lacerda?", [0, RESULTADO_ANTIGO], [0]),
    ("qual o telefone do Joao Araujo?", [0, RESULTADO_ANTIGO], [0]),
    # Compras: antes buscar_vendas + detalhe_venda + resposta; depois busca com compras + resposta.
    (
        "o que a Marina comprou no dia 15?",
        [0, RESULTADO_ANTIGO, 2 * RESULTADO_ANTIGO],
        [0, RESULTADO_COMPRAS],
    ),
    # Compras com CPF na pergunta: depois, 1 chamada sem ferramentas so para apresentar.
    (
        "o que o 123.456.789-01 comprou ontem?",
        [0, RESULTADO_ANTIGO, 2 * RESULTADO_ANTIGO],
        ["apresentar"],
    ),
    # Falta o dia: depois nao chama o modelo.
    ("o que a Marina comprou?", [0, RESULTADO_ANTIGO], []),
]


def depois(pergunta: str, chamadas: list) -> int:
    total = 0
    for extra in chamadas:
        if extra == "apresentar":
            total += tokens(consulta_cliente.SISTEMA) + tokens(pergunta) + RESULTADO_COMPRAS
        else:
            total += depois_base + tokens(pergunta) + extra
    return total


def main() -> None:
    print(f"Prompt + ferramentas por chamada: antes ~{antes_base} tokens, depois ~{depois_base}")
    print("| Pergunta | Chamadas antes | Entrada antes | Chamadas depois | Entrada depois |")
    print("|---|---|---|---|---|")
    soma_antes = soma_depois = 0
    for pergunta, antes_chamadas, depois_chamadas in CASOS:
        antes = sum(antes_base + tokens(pergunta) + extra for extra in antes_chamadas)
        agora = depois(pergunta, depois_chamadas)
        soma_antes, soma_depois = soma_antes + antes, soma_depois + agora
        print(
            f"| {pergunta} | {len(antes_chamadas)} | ~{antes} | {len(depois_chamadas)} | ~{agora} |"
        )
    economia = 100 * (1 - soma_depois / soma_antes)
    print(f"\nTotal: ~{soma_antes} -> ~{soma_depois} tokens de entrada ({economia:.0f}% a menos).")


if __name__ == "__main__":
    main()
