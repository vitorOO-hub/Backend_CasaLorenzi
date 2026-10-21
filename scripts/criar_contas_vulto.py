"""Cria a conta no Supabase Auth de cada funcionario da Vulto importado em `usuario`.

Pega os `usuario` com e-mail @vulto.example, ativos e ainda sem `auth_user_id`; cria a conta pela
Admin API (ja confirmada, senha aleatoria) e grava o `auth_user_id` na linha. O papel e a loja do
token continuam vindo de `usuario` (hook_claims_token). Quem ja tem conta no Auth so e ligado,
sem trocar a senha.

Uso, a partir da raiz do backend (le o .env; nada e gravado em disco):

    python scripts/criar_contas_vulto.py             # mostra o plano e nao altera nada
    $env:SUPABASE_SERVICE_ROLE_KEY = '<chave secreta do painel>'
    python scripts/criar_contas_vulto.py --aplicar   # cria e imprime e-mail e senha UMA vez
    Remove-Item Env:SUPABASE_SERVICE_ROLE_KEY

As senhas aparecem so na saida deste comando. A chave de servico nunca e impressa nem gravada.
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg
from criar_contas import _tabela, cadastrar_admin, gerar_senha, id_auth_por_email
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[1]
CONTAS = """
SELECT u.id_usuario, u.nome, u.email, t.codigo, coalesce(l.nome, '(sem loja)')
FROM usuario u
JOIN tipo_usuario t USING (id_tipo_usuario)
LEFT JOIN loja l USING (id_loja)
WHERE u.email LIKE '%@vulto.example' AND u.ativo AND u.auth_user_id IS NULL
ORDER BY l.nome NULLS LAST, t.codigo, u.nome
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--aplicar", action="store_true", help="cria as contas")
    args = parser.parse_args(argv)

    env = dotenv_values(RAIZ / ".env")
    url = (env.get("SUPABASE_URL") or "").rstrip("/")
    banco = env.get("DATABASE_URL") or ""
    if not (url and banco):
        print("Faltam SUPABASE_URL ou DATABASE_URL no .env.", file=sys.stderr)
        return 2

    with psycopg.connect(banco, connect_timeout=15) as conexao:
        contas = conexao.execute(CONTAS).fetchall()
        print(f"Projeto Supabase: {urlsplit(url).hostname}\n")
        print(_tabela([("TIPO", "E-MAIL", "LOJA"), *[(c[3], c[2], c[4]) for c in contas]]))
        print(f"\n{len(contas)} conta(s) a criar.")
        if not args.aplicar:
            print("Nada foi alterado. Rode de novo com --aplicar para criar as contas.")
            return 0

        chave_servico = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not chave_servico:
            print(
                "\nDefina SUPABASE_SERVICE_ROLE_KEY so nesta execucao (o cadastro publico esta "
                "desligado).",
                file=sys.stderr,
            )
            return 2
        entregues: list[tuple[str, str, str]] = []
        avisos: list[str] = []
        with httpx.Client() as http:
            for id_usuario, nome, email, tipo, _loja in contas:
                senha = gerar_senha()
                try:
                    resultado = cadastrar_admin(http, url, chave_servico, email, senha, nome)
                except RuntimeError as erro:
                    print(f"\n{email}: {erro}", file=sys.stderr)
                    return 1
                id_auth = resultado.id_auth
                if id_auth is None:  # ja tinha conta: so liga, sem mexer na senha
                    id_auth = id_auth_por_email(conexao, email)
                    if id_auth is None:
                        avisos.append(f"{email}: conta existente nao encontrada no Auth")
                        continue
                    avisos.append(f"{email}: ja tinha conta no Auth; ligada, senha nao alterada")
                else:
                    entregues.append((tipo, email, senha))
                conexao.execute(
                    "UPDATE usuario SET auth_user_id = %s::uuid, atualizado_em = now() "
                    "WHERE id_usuario = %s AND auth_user_id IS NULL",
                    (id_auth, id_usuario),
                )
                conexao.commit()

    if entregues:
        print("\nContas criadas (guarde agora: as senhas nao ficam salvas em lugar nenhum):\n")
        print(_tabela([("TIPO", "E-MAIL", "SENHA"), *entregues]))
    for aviso in avisos:
        print(f"\nAtencao - {aviso}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
