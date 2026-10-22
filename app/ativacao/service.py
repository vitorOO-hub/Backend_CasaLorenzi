"""Ativacao da conta de cliente importado (Vulto+): acha o cadastro pelo CPF e cria a senha.

Decisao do time: o CPF e o que identifica o cadastro. Quem ja tem e-mail no cadastro so cria a
senha (e entra com aquele e-mail, que a tela nao revela); quem nao tem informa o e-mail junto.
Isso e menos seguro do que confirmar por e-mail, e foi aceito para ninguem perder a conta.
"""

from uuid import UUID

from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.ativacao import repositorio
from app.ativacao.auth_admin import AuthAdmin
from app.ativacao.erros import AtivacaoNegada, EmailJaNoAuth, EmailObrigatorio


def mascarar_email(email: str) -> str:
    usuario, _, dominio = email.partition("@")
    return f"{usuario[:1]}***@{dominio}"


def consultar(conexao: Connection, cpf: str) -> dict[str, bool]:
    """Se a tela precisa pedir o e-mail. CPF sem cadastro, ou ja ativo, tambem pede: assim a
    resposta nao diz quais CPFs existem."""
    linha = repositorio.cliente_pendente(conexao, cpf)
    return {"pede_email": linha is None or not linha["email"]}


def ativar(
    conexao: Connection, auth_admin: AuthAdmin, *, cpf: str, senha: str, email: str | None
) -> dict[str, str]:
    linha = repositorio.cliente_pendente(conexao, cpf, travar=True)
    email_final = (linha["email"] if linha else None) or (email.strip().lower() if email else None)
    if not email_final:
        conexao.rollback()
        raise EmailObrigatorio
    if linha is None:
        conexao.rollback()
        raise AtivacaoNegada
    id_usuario: UUID = linha["id_usuario"]
    if not linha["email"] and repositorio.email_em_uso_por_outro(conexao, email_final, id_usuario):
        conexao.rollback()
        raise AtivacaoNegada

    try:
        id_auth = auth_admin.criar_usuario(email_final, senha)
    except EmailJaNoAuth:
        conexao.rollback()
        raise AtivacaoNegada from None
    except Exception:
        conexao.rollback()
        raise
    try:
        ligado = repositorio.ligar_login(conexao, id_usuario, id_auth, email_final)
        if ligado:
            conexao.commit()
    except IntegrityError as erro:
        # Ex.: o mesmo e-mail gravado por outra ativacao ao mesmo tempo. Nada fica pela metade.
        conexao.rollback()
        auth_admin.apagar_usuario(id_auth)
        raise AtivacaoNegada from erro
    except Exception:
        conexao.rollback()
        auth_admin.apagar_usuario(id_auth)
        raise
    if not ligado:
        conexao.rollback()
        auth_admin.apagar_usuario(id_auth)
        raise AtivacaoNegada
    return {"email": mascarar_email(email_final)}
