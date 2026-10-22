"""Importa a tabela `funcionarios` do vulto.db (SQLite legado) para `public.usuario`.

Uso (a partir da pasta do backend, com DATABASE_URL no ambiente ou no .env):
    python scripts/importar_funcionarios_vulto.py CAMINHO/vulto.db            # so mostra o plano
    python scripts/importar_funcionarios_vulto.py CAMINHO/vulto.db --ensaio   # grava e desfaz
    python scripts/importar_funcionarios_vulto.py CAMINHO/vulto.db --aplicar  # grava

Campos: nome -> nome; loja_id (1 a 7) -> id_loja; perfil -> id_tipo_usuario; ativo -> ativo.
`codigo` (cracha) e `senha` nao vao: a senha e do Supabase Auth e o tipo substitui o codigo.
O legado nao tem e-mail (obrigatorio e unico em `usuario`): usa-se nome@vulto.example, que o
Supabase Auth pode trocar depois. Repetir o script nao duplica (chave: e-mail).
"""

import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import psycopg

from vulto_integracao.lojas import CODIGO_LOJA_POR_ID_VULTO, resolver_id_loja_vulto

TIPO_DO_PERFIL = {
    "vendedor": "vendedor",
    "gerente": "gerente_loja",
    "operador": "operador_estoque",
    "admin": "diretor",
}
DOMINIO = "vulto.example"
IGNORAR = {"TESTE TI"}  # conta de teste do legado: nao entra


def email_de(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", ".", sem_acento.lower()).strip(".") + "@" + DOMINIO


def ler_funcionarios(caminho: str) -> list[dict]:
    con = sqlite3.connect(f"file:{Path(caminho).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    linhas = con.execute(
        "SELECT id, nome, loja_id, perfil, ativo FROM funcionarios ORDER BY id"
    ).fetchall()
    return [dict(linha) for linha in linhas if linha["nome"] not in IGNORAR]


def url_do_banco() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    for linha in Path(".env").read_text(encoding="utf-8").splitlines():
        if linha.startswith("DATABASE_URL="):
            return linha.split("=", 1)[1].strip().strip("\"'")
    sys.exit("Defina DATABASE_URL.")


def main() -> None:
    caminho = next(a for a in sys.argv[1:] if not a.startswith("--"))
    funcionarios = ler_funcionarios(caminho)
    emails = [email_de(f["nome"]) for f in funcionarios]
    if len(set(emails)) != len(emails):
        sys.exit("E-mails repetidos depois de gerar nome@" + DOMINIO)
    for f in funcionarios:
        if f["perfil"] not in TIPO_DO_PERFIL:
            sys.exit(f"Perfil sem regra: {f['perfil']!r} ({f['nome']})")
        if f["loja_id"] is not None and f["loja_id"] not in LOJA_DO_LEGADO:
            sys.exit(f"loja_id sem regra: {f['loja_id']} ({f['nome']})")

    with psycopg.connect(url_do_banco(), prepare_threshold=None) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT codigo, id_loja FROM loja WHERE codigo = ANY(%s)",
            (list(CODIGO_LOJA_POR_ID_VULTO.values()),),
        )
        loja = dict(cur.fetchall())
        cur.execute("SELECT codigo, id_tipo_usuario FROM tipo_usuario")
        tipo = dict(cur.fetchall())
        novos = existentes = 0
        for f, email in zip(funcionarios, emails, strict=True):
            id_loja = (
                resolver_id_loja_vulto(f["loja_id"], loja) if f["loja_id"] is not None else None
            )
            id_tipo = tipo[TIPO_DO_PERFIL[f["perfil"]]]
            print(
                f"{f['id']:>2} {f['nome']:<22} {f['perfil']:<9} -> "
                f"{TIPO_DO_PERFIL[f['perfil']]:<16} "
                f"loja={CODIGO_LOJA_POR_ID_VULTO.get(f['loja_id'])} "
                f"ativo={bool(f['ativo'])} {email}"
            )
            if "--aplicar" in sys.argv or "--ensaio" in sys.argv:
                cur.execute(
                    "INSERT INTO usuario (nome, email, ativo, id_tipo_usuario, id_loja) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (email) DO NOTHING",
                    (f["nome"], email, bool(f["ativo"]), id_tipo, id_loja),
                )
                novos += cur.rowcount
                existentes += 1 - cur.rowcount
        if "--ensaio" in sys.argv:
            conn.rollback()
            print(f"ENSAIO (desfeito): {novos} inseriria, {existentes} ja existiam")
        elif "--aplicar" in sys.argv:
            conn.commit()
            print(f"GRAVADO: {novos} novos, {existentes} ja existiam")
        else:
            print(f"{len(funcionarios)} funcionarios (plano; nada gravado)")


if __name__ == "__main__":
    main()
