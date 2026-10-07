"""Cria uma conta de acesso para cada tipo de usuario, pelo Supabase Auth.

Para cada tipo (cliente, atendente, operador de estoque, gerente e administrador):
  1. cria a conta pela API publica do Supabase Auth (`/auth/v1/signup`, a mesma funcao do
     `supabase.auth.signUp`), com uma senha aleatoria gerada agora;
  2. liga a conta a uma linha da tabela `usuario` (tipo, loja e `auth_user_id`), que e de onde o
     hook `public.hook_claims_token` tira o papel e a loja que vao dentro do token.

Uso, a partir da raiz do backend (le o .env; nada e gravado em disco):

    python scripts/criar_contas.py             # mostra o plano e nao altera nada
    python scripts/criar_contas.py --aplicar   # cria as contas e imprime e-mail e senha UMA vez

As senhas aparecem so na saida deste comando. Quem ja tem conta no Auth e pulado: sem a service
role key nao ha como ler nem trocar a senha de outra conta, e este script nunca a usa.
"""

import argparse
import secrets
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[1]
DOMINIO_PADRAO = "casalorenzi.com.br"
LOJA_PADRAO = "LOJA-CENTRO"


@dataclass(frozen=True)
class Conta:
    tipo: str  # codigo em tipo_usuario
    papel: str  # o que vai no token (o hook traduz 'diretor' para 'admin')
    usuario: str  # parte local do e-mail
    nome: str
    precisa_loja: bool


CONTAS = (
    Conta("cliente", "cliente", "cliente", "Cliente Casa Lorenzi", False),
    Conta("atendente", "atendente", "atendente", "Atendente Casa Lorenzi", True),
    Conta("operador_estoque", "operador_estoque", "operador", "Operador de Estoque", True),
    Conta("gerente_loja", "gerente_loja", "gerente", "Gerente da Loja", True),
    Conta("diretor", "admin", "admin", "Administrador Casa Lorenzi", False),
)


def email_da(conta: Conta, dominio: str) -> str:
    return f"{conta.usuario}@{dominio}"


def gerar_senha(tamanho: int = 16) -> str:
    """Senha aleatoria com maiuscula, minuscula, digito e simbolo (geracao criptografica)."""
    grupos = (string.ascii_uppercase, string.ascii_lowercase, string.digits, "!#$%*?")
    todos = "".join(grupos)
    caracteres = [secrets.choice(grupo) for grupo in grupos]
    caracteres += [secrets.choice(todos) for _ in range(tamanho - len(caracteres))]
    secrets.SystemRandom().shuffle(caracteres)
    return "".join(caracteres)


@dataclass(frozen=True)
class ResultadoCadastro:
    id_auth: str | None
    ja_existia: bool = False
    confirmado: bool = True


def interpretar_cadastro(status: int, corpo: dict) -> ResultadoCadastro:
    """Entende a resposta do /signup nos formatos que o Supabase usa."""
    if (
        status in (400, 422)
        and "already" in str(corpo.get("msg") or corpo.get("message") or "").lower()
    ):
        return ResultadoCadastro(None, ja_existia=True)
    if status >= 400:
        mensagem = (
            corpo.get("msg") or corpo.get("message") or corpo.get("error_description") or status
        )
        raise RuntimeError(f"o Supabase recusou o cadastro: {mensagem}")
    usuario = corpo.get("user") or corpo
    id_auth = usuario.get("id")
    if not id_auth:
        raise RuntimeError("resposta do cadastro sem id de usuario")
    # Com a confirmacao de e-mail ligada, um e-mail repetido volta como usuario sem identidades.
    if usuario.get("identities") == []:
        return ResultadoCadastro(None, ja_existia=True)
    confirmado = bool(
        corpo.get("access_token")
        or usuario.get("email_confirmed_at")
        or usuario.get("confirmed_at")
    )
    return ResultadoCadastro(id_auth, confirmado=confirmado)


def cadastrar(
    http: httpx.Client, url_supabase: str, chave_publica: str, email: str, senha: str, nome: str
):
    resposta = http.post(
        f"{url_supabase}/auth/v1/signup",
        headers={"apikey": chave_publica, "Content-Type": "application/json"},
        json={"email": email, "password": senha, "data": {"nome": nome}},
        timeout=20,
    )
    try:
        corpo = resposta.json()
    except ValueError:
        corpo = {}
    return interpretar_cadastro(resposta.status_code, corpo if isinstance(corpo, dict) else {})


def vincular_usuario(
    conexao: psycopg.Connection, conta: Conta, email: str, id_auth: str, codigo_loja: str
) -> None:
    """Cria ou atualiza a linha de `usuario` que o hook usa para montar papel e loja do token."""
    conexao.execute(
        """
        INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email, ativo)
        SELECT
            t.id_tipo_usuario,
            CASE WHEN %(precisa_loja)s THEN (SELECT id_loja FROM loja WHERE codigo = %(loja)s) END,
            %(auth)s::uuid, %(nome)s, %(email)s, true
        FROM tipo_usuario t
        WHERE t.codigo = %(tipo)s
        ON CONFLICT (email) DO UPDATE
        SET auth_user_id = EXCLUDED.auth_user_id,
            id_tipo_usuario = EXCLUDED.id_tipo_usuario,
            id_loja = EXCLUDED.id_loja,
            ativo = true
        """,
        {
            "precisa_loja": conta.precisa_loja,
            "loja": codigo_loja,
            "auth": id_auth,
            "nome": conta.nome,
            "email": email,
            "tipo": conta.tipo,
        },
    )


def _tabela(linhas: list[tuple[str, str, str]]) -> str:
    larguras = [max(len(linha[i]) for linha in linhas) for i in range(3)]
    return "\n".join(
        "  ".join(valor.ljust(larguras[i]) for i, valor in enumerate(linha)).rstrip()
        for linha in linhas
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--aplicar", action="store_true", help="cria as contas (sem isso so mostra o plano)"
    )
    parser.add_argument(
        "--dominio", default=DOMINIO_PADRAO, help=f"dominio dos e-mails (padrao {DOMINIO_PADRAO})"
    )
    parser.add_argument(
        "--loja", default=LOJA_PADRAO, help=f"codigo da loja da equipe (padrao {LOJA_PADRAO})"
    )
    args = parser.parse_args(argv)

    env = dotenv_values(RAIZ / ".env")
    url = (env.get("SUPABASE_URL") or "").rstrip("/")
    chave = env.get("SUPABASE_PUBLISHABLE_KEY") or ""
    banco = env.get("DATABASE_URL") or ""
    if not (url and chave and banco):
        print(
            "Faltam SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY ou DATABASE_URL no .env.",
            file=sys.stderr,
        )
        return 2

    print(f"Projeto Supabase: {urlsplit(url).hostname}")
    print(f"Loja da equipe:   {args.loja}\n")
    plano = [(c.papel, email_da(c, args.dominio), c.nome) for c in CONTAS]
    print(_tabela([("PAPEL NO TOKEN", "E-MAIL", "NOME"), *plano]))
    if not args.aplicar:
        print("\nNada foi alterado. Rode de novo com --aplicar para criar as contas.")
        return 0

    entregues: list[tuple[str, str, str]] = []
    avisos: list[str] = []
    with httpx.Client() as http, psycopg.connect(banco, connect_timeout=15) as conexao:
        existe = conexao.execute("SELECT 1 FROM loja WHERE codigo = %s", (args.loja,)).fetchone()
        if not existe:
            print(f"\nLoja {args.loja!r} nao existe no banco.", file=sys.stderr)
            return 2
        for conta in CONTAS:
            email = email_da(conta, args.dominio)
            senha = gerar_senha()
            resultado = cadastrar(http, url, chave, email, senha, conta.nome)
            if resultado.ja_existia or resultado.id_auth is None:
                avisos.append(
                    f"{email}: ja tem conta no Auth; mantida como esta (a senha nao e alterada)"
                )
                continue
            vincular_usuario(conexao, conta, email, resultado.id_auth, args.loja)
            conexao.commit()
            entregues.append((conta.papel, email, senha))
            if not resultado.confirmado:
                avisos.append(
                    f"{email}: e-mail NAO confirmado; "
                    "desligue 'Confirm email' no Auth ou confirme a conta"
                )

    if entregues:
        print("\nContas criadas (guarde agora: as senhas nao ficam salvas em lugar nenhum):\n")
        print(_tabela([("PAPEL", "E-MAIL", "SENHA"), *entregues]))
    for aviso in avisos:
        print(f"\nAtencao - {aviso}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
