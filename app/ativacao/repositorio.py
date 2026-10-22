"""Consultas SQL da ativacao de conta."""

from uuid import UUID

from sqlalchemy.engine import Connection

from app.core.repositorio import buscar_um, executar_sql


def cliente_pendente(conexao: Connection, cpf: str, *, travar: bool = False) -> dict | None:
    """Cliente ativo com este CPF que ainda nao tem login (importado do Vulto+)."""
    return buscar_um(
        conexao,
        f"""
        SELECT u.id_usuario, u.email
        FROM public.usuario u
        JOIN public.tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
        WHERE u.documento = %s
          AND t.codigo = 'cliente'
          AND u.ativo IS TRUE
          AND u.auth_user_id IS NULL
        {"FOR UPDATE OF u" if travar else ""}
        """,  # noqa: S608 - so o sufixo fixo acima muda; o CPF vai como parametro
        (cpf,),
    )


def email_em_uso_por_outro(conexao: Connection, email: str, id_usuario: UUID) -> bool:
    return (
        buscar_um(
            conexao,
            "SELECT 1 AS usado FROM public.usuario "
            "WHERE lower(email) = lower(%s) AND id_usuario <> %s",
            (email, id_usuario),
        )
        is not None
    )


def ligar_login(conexao: Connection, id_usuario: UUID, id_auth: UUID, email: str) -> bool:
    """Liga a conta do Auth ao cliente. False se alguem ligou antes (corrida)."""
    resultado = executar_sql(
        conexao,
        """
        UPDATE public.usuario
        SET auth_user_id = %s, email = COALESCE(email, %s), atualizado_em = now()
        WHERE id_usuario = %s AND auth_user_id IS NULL
        """,
        (id_auth, email, id_usuario),
    )
    return resultado.rowcount == 1
