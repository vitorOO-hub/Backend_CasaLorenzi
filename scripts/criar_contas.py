"""Cria uma conta de acesso para cada tipo de usuario, pelo Supabase Auth.

Para cada tipo (cliente, atendente, operador de estoque, gerente e administrador):
  1. cria a conta pela API publica do Supabase Auth (`/auth/v1/signup`, a mesma funcao do
     `supabase.auth.signUp`), com uma senha aleatoria gerada agora;
  2. liga a conta a uma linha da tabela `usuario` (tipo, loja e `auth_user_id`), que e de onde o
     hook `public.hook_claims_token` tira o papel e a loja que vao dentro do token.

Uso, a partir da raiz do backend (le o .env; nada e gravado em disco):

    python scripts/criar_contas.py             # mostra o plano e nao altera nada
    python scripts/criar_contas.py --aplicar   # cria as contas e imprime e-mail e senha UMA vez

Com a variavel de ambiente SUPABASE_SERVICE_ROLE_KEY definida so para esta execucao, as contas
sao criadas pela Admin API (necessario quando o cadastro publico esta desligado). Com
--so-vincular, o script nao cria nada: liga ao `usuario` as contas que voce ja criou no painel.

As senhas aparecem so na saida deste comando. Quem ja tem conta no Auth e pulado: sem a service
role key nao ha como ler nem trocar a senha de outra conta, e este script nunca a usa.
"""

import argparse
import os
import re
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
DICA_CADASTRO_DESLIGADO = (
    "\nO cadastro publico esta desligado neste projeto (o que e bom para a seguranca). Escolha:\n"
    "  1. Rode com a service role key SO nesta execucao (nao grave no .env):\n"
    "       $env:SUPABASE_SERVICE_ROLE_KEY = '<chave secreta do painel>'\n"
    "       python scripts/criar_contas.py --email-base voce@gmail.com --aplicar\n"
    "       Remove-Item Env:SUPABASE_SERVICE_ROLE_KEY\n"
    "  2. Ou crie as contas no painel (Authentication > Users > Add user, Auto Confirm) e rode\n"
    "       python scripts/criar_contas.py --email-base voce@gmail.com --so-vincular --aplicar"
)
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
    Conta("operador_estoque", "operador_estoque", "operadorestoque", "Operador de Estoque", True),
    Conta("gerente_loja", "gerente_loja", "gerente", "Gerente da Loja", True),
    Conta("diretor", "admin", "admin", "Administrador Casa Lorenzi", False),
)


def email_da(conta: Conta, dominio: str, email_base: str | None = None) -> str:
    """E-mail da conta. Com `email_base` (voce@gmail.com) vira voce+atendente@gmail.com."""
    if email_base:
        local, _, host = email_base.partition("@")
        return f"{local}+{conta.usuario}@{host}"
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


def cadastrar_admin(
    http: httpx.Client, url_supabase: str, chave_servico: str, email: str, senha: str, nome: str
):
    """Cria a conta pela Admin API do Supabase, ja confirmada. A chave nunca e impressa."""
    resposta = http.post(
        f"{url_supabase}/auth/v1/admin/users",
        headers={
            "apikey": chave_servico,
            "Authorization": f"Bearer {chave_servico}",
            "Content-Type": "application/json",
        },
        json={
            "email": email,
            "password": senha,
            "email_confirm": True,
            "user_metadata": {"nome": nome},
        },
        timeout=20,
    )
    try:
        corpo = resposta.json()
    except ValueError:
        corpo = {}
    return interpretar_cadastro(resposta.status_code, corpo if isinstance(corpo, dict) else {})


def id_auth_por_email(conexao: psycopg.Connection, email: str) -> str | None:
    """Id da conta no Supabase Auth (leitura de auth.users), ou None se ainda nao existe."""
    linha = conexao.execute(
        "SELECT id FROM auth.users WHERE lower(email) = lower(%s) AND deleted_at IS NULL",
        (email,),
    ).fetchone()
    return str(linha[0]) if linha else None


def vincular_usuario(
    conexao: psycopg.Connection, conta: Conta, email: str, id_auth: str, codigo_loja: str
) -> None:
    """Cria ou atualiza a linha de `usuario` que o hook usa para montar papel e loja do token."""
    conexao.execute(
        """
        INSERT INTO usuario (
            id_tipo_usuario, id_loja, auth_user_id, nome, email, ativo,
            rua, bairro, numero_endereco, cep)
        SELECT
            t.id_tipo_usuario,
            CASE WHEN %(precisa_loja)s THEN (SELECT id_loja FROM loja WHERE codigo = %(loja)s) END,
            %(auth)s::uuid, %(nome)s, %(email)s, true,
            -- Todo cliente tem endereco; a conta de demonstracao recebe um de exemplo.
            CASE WHEN t.codigo = 'cliente' THEN 'Rua das Flores' END,
            CASE WHEN t.codigo = 'cliente' THEN 'Centro' END,
            CASE WHEN t.codigo = 'cliente' THEN '100' END,
            CASE WHEN t.codigo = 'cliente' THEN '01001000' END
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
        "--so-vincular",
        action="store_true",
        help="nao cria contas: liga ao usuario as que ja existem no Auth (criadas no painel)",
    )
    parser.add_argument(
        "--email-base",
        help="e-mail seu com caixa real; as contas viram voce+atendente@..., voce+gerente@... "
        "(o Supabase recusa dominios sem servidor de e-mail)",
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
    if args.email_base and not re.fullmatch(r"[^@\s+]+@[^@\s]+\.[^@\s]+", args.email_base):
        print(
            "--email-base precisa ser um e-mail simples, sem '+' (ex.: voce@gmail.com).",
            file=sys.stderr,
        )
        return 2
    plano = [(c.papel, email_da(c, args.dominio, args.email_base), c.nome) for c in CONTAS]
    print(_tabela([("PAPEL NO TOKEN", "E-MAIL", "NOME"), *plano]))
    if not args.aplicar:
        print("\nNada foi alterado. Rode de novo com --aplicar para criar as contas.")
        return 0

    chave_servico = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    entregues: list[tuple[str, str, str]] = []
    ligadas: list[tuple[str, str, str]] = []
    avisos: list[str] = []
    with httpx.Client() as http, psycopg.connect(banco, connect_timeout=15) as conexao:
        existe = conexao.execute("SELECT 1 FROM loja WHERE codigo = %s", (args.loja,)).fetchone()
        if not existe:
            print(f"\nLoja {args.loja!r} nao existe no banco.", file=sys.stderr)
            return 2
        for conta in CONTAS:
            email = email_da(conta, args.dominio, args.email_base)
            if args.so_vincular:
                id_auth = id_auth_por_email(conexao, email)
                if id_auth is None:
                    avisos.append(
                        f"{email}: ainda nao existe no Auth; crie no painel e rode de novo"
                    )
                    continue
                vincular_usuario(conexao, conta, email, id_auth, args.loja)
                conexao.commit()
                ligadas.append((conta.papel, email, "(a que voce definiu no painel)"))
                continue
            senha = gerar_senha()
            try:
                if chave_servico:
                    resultado = cadastrar_admin(http, url, chave_servico, email, senha, conta.nome)
                else:
                    resultado = cadastrar(http, url, chave, email, senha, conta.nome)
            except RuntimeError as erro:
                print(f"\n{erro}", file=sys.stderr)
                if "signups are disabled" in str(erro).lower():
                    print(DICA_CADASTRO_DESLIGADO, file=sys.stderr)
                return 1
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

    if ligadas:
        print("\nContas ligadas ao usuario (papel e loja agora vao no token):\n")
        print(_tabela([("PAPEL", "E-MAIL", "SENHA"), *ligadas]))
    if entregues:
        print("\nContas criadas (guarde agora: as senhas nao ficam salvas em lugar nenhum):\n")
        print(_tabela([("PAPEL", "E-MAIL", "SENHA"), *entregues]))
    for aviso in avisos:
        print(f"\nAtencao - {aviso}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
