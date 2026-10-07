"""Cria chamados de exemplo para a area de atendimento (so ambiente de desenvolvimento).

Sem isto a fila fica vazia e nao da para ver as telas funcionando. Os chamados usam os clientes e
a equipe que ja existem no banco (veja scripts/criar_contas.py) e a loja indicada.

    python scripts/semear_chamados.py             # mostra o que seria criado, sem alterar nada
    python scripts/semear_chamados.py --aplicar   # cria os chamados

So semeia se a tabela `atendimento` estiver vazia (use --forcar para semear mesmo assim). Nunca
rode em producao com clientes reais: os chamados sao ficticios.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[1]
LOJA_PADRAO = "LOJA-CENTRO"


@dataclass(frozen=True)
class Exemplo:
    assunto: str
    categoria: str
    canal: str
    prioridade: str
    status: str
    horas_atras: int
    assumido: bool
    mensagens: tuple[tuple[str, str], ...]  # (quem, texto): "cliente" ou "equipe"


EXEMPLOS = (
    Exemplo(
        "Costura do paletó se soltou",
        "troca_devolucao",
        "whatsapp",
        "urgente",
        "aberto",
        1,
        False,
        (("cliente", "Comprei o paletó semana passada e a costura da manga já abriu."),),
    ),
    Exemplo(
        "Pedido não chegou no prazo",
        "entrega",
        "site",
        "alta",
        "aberto",
        5,
        False,
        (("cliente", "Meu pedido estava previsto para ontem e o rastreio não atualiza."),),
    ),
    Exemplo(
        "Dúvida sobre o tamanho da camisa",
        "produto",
        "email",
        "baixa",
        "aberto",
        20,
        False,
        (
            (
                "cliente",
                "Costumo usar M, mas essa modelagem parece mais justa. Qual tamanho vocês indicam?",
            ),
        ),
    ),
    Exemplo(
        "Cobrança em duplicidade no cartão",
        "pagamento",
        "telefone",
        "alta",
        "em_andamento",
        30,
        True,
        (
            ("cliente", "Apareceram duas cobranças iguais na minha fatura."),
            (
                "equipe",
                "Oi! Já localizei o pedido e vou conferir com o financeiro. Retorno ainda hoje.",
            ),
        ),
    ),
    Exemplo(
        "Troca de cor da blusa",
        "troca_devolucao",
        "presencial",
        "media",
        "em_andamento",
        48,
        True,
        (
            ("cliente", "Gostaria de trocar a blusa azul pela verde."),
            ("equipe", "Claro! Pode trazer a peça com a etiqueta que fazemos a troca na loja."),
            ("cliente", "Perfeito, passo aí amanhã."),
        ),
    ),
    Exemplo(
        "Segunda via da nota fiscal",
        "pedido",
        "site",
        "baixa",
        "resolvido",
        120,
        True,
        (
            ("cliente", "Preciso da nota fiscal do meu último pedido."),
            ("equipe", "Enviamos a nota para o seu e-mail agora mesmo."),
        ),
    ),
    Exemplo(
        "Pedido sem item na embalagem",
        "pedido",
        "whatsapp",
        "media",
        "aguardando_cliente",
        72,
        True,
        (
            ("cliente", "Veio só uma das duas camisas que comprei."),
            (
                "equipe",
                "Sentimos muito! Pode enviar uma foto da embalagem para abrirmos o envio do item?",
            ),
        ),
    ),
)


def semear(conexao: psycopg.Connection, codigo_loja: str, *, forcar: bool = False) -> int:
    """Cria os exemplos numa transacao. Devolve quantos chamados foram criados (0 se pulou)."""
    if not conexao.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'atendimento' "
        "AND column_name = 'protocolo'"
    ).fetchone():
        raise RuntimeError("falta a revisao 20261007000600 (rode: alembic upgrade head)")
    if not forcar and conexao.execute("SELECT 1 FROM atendimento LIMIT 1").fetchone():
        return 0

    loja = conexao.execute("SELECT id_loja FROM loja WHERE codigo = %s", (codigo_loja,)).fetchone()
    if not loja:
        raise RuntimeError(f"loja {codigo_loja!r} nao existe")
    clientes = [
        r[0]
        for r in conexao.execute(
            "SELECT u.id_usuario FROM usuario u JOIN tipo_usuario t USING (id_tipo_usuario) "
            "WHERE t.codigo = 'cliente' AND u.ativo ORDER BY u.criado_em"
        )
    ]
    if not clientes:
        raise RuntimeError("nao ha cliente ativo no banco")
    equipe = conexao.execute(
        "SELECT u.id_usuario FROM usuario u JOIN tipo_usuario t USING (id_tipo_usuario) "
        "WHERE t.codigo = 'atendente' AND u.ativo AND u.id_loja = %s ORDER BY u.criado_em LIMIT 1",
        (loja[0],),
    ).fetchone()
    if not equipe:
        raise RuntimeError("nao ha atendente ativo nessa loja (rode scripts/criar_contas.py)")

    for i, ex in enumerate(EXEMPLOS):
        cliente = clientes[i % len(clientes)]
        id_chamado = conexao.execute(
            """
            INSERT INTO atendimento (
                id_cliente, id_loja, id_usuario_responsavel, assunto, aberto_em,
                id_canal_atendimento, id_categoria_atendimento,
                id_prioridade_atendimento, id_status_atendimento, encerrado_em
            )
            VALUES (
                %(cliente)s, %(loja)s, %(resp)s, %(assunto)s, now() - make_interval(hours => %(h)s),
                (SELECT id_canal_atendimento FROM canal_atendimento WHERE codigo = %(canal)s),
                (SELECT id_categoria_atendimento FROM categoria_atendimento WHERE codigo = %(cat)s),
                (SELECT id_prioridade_atendimento FROM prioridade_atendimento
                 WHERE codigo = %(pri)s),
                (SELECT id_status_atendimento FROM status_atendimento WHERE codigo = %(st)s),
                CASE WHEN %(st)s IN ('resolvido', 'encerrado')
                     THEN now() - make_interval(hours => %(h)s) + interval '3 hours' END
            )
            RETURNING id_atendimento
            """,
            {
                "cliente": cliente,
                "loja": loja[0],
                "resp": equipe[0] if ex.assumido else None,
                "assunto": ex.assunto,
                "h": ex.horas_atras,
                "canal": ex.canal,
                "cat": ex.categoria,
                "pri": ex.prioridade,
                "st": ex.status,
            },
        ).fetchone()[0]
        for ordem, (quem, texto) in enumerate(ex.mensagens):
            conexao.execute(
                """
                INSERT INTO mensagem (id_atendimento, id_usuario_remetente, texto, enviada_em)
                VALUES (%s, %s, %s, now() - make_interval(hours => %s) + make_interval(mins => %s))
                """,
                (
                    id_chamado,
                    cliente if quem == "cliente" else equipe[0],
                    texto,
                    ex.horas_atras,
                    ordem * 20,
                ),
            )
    return len(EXEMPLOS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--aplicar", action="store_true", help="cria os chamados (sem isso so mostra o plano)"
    )
    parser.add_argument(
        "--forcar", action="store_true", help="semeia mesmo com chamados ja existentes"
    )
    parser.add_argument(
        "--loja", default=LOJA_PADRAO, help=f"codigo da loja (padrao {LOJA_PADRAO})"
    )
    args = parser.parse_args(argv)

    banco = (dotenv_values(RAIZ / ".env").get("DATABASE_URL") or "").strip()
    if not banco:
        print("Falta DATABASE_URL no .env.", file=sys.stderr)
        return 2

    print(f"Banco: {urlsplit(banco).hostname}  |  loja: {args.loja}\n")
    for ex in EXEMPLOS:
        print(f"  [{ex.status:18}] [{ex.prioridade:7}] {ex.assunto}")
    if not args.aplicar:
        print("\nNada foi alterado. Rode de novo com --aplicar para criar os chamados.")
        return 0

    with psycopg.connect(banco, connect_timeout=15) as conexao:
        try:
            criados = semear(conexao, args.loja, forcar=args.forcar)
        except RuntimeError as erro:
            print(f"\nNao foi possivel semear: {erro}", file=sys.stderr)
            return 1
        conexao.commit()
    print(
        f"\n{criados} chamados criados."
        if criados
        else "\nJa existem chamados; nada foi criado (use --forcar)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
