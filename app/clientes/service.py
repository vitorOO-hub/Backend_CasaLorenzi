"""Regras da area de clientes: escopo de loja e quem pode ver compras e valores."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.chamados.repositorio import Escopo
from app.chamados.service import GESTAO, PAPEIS_DO_PAINEL, montar_escopo, resolver_loja
from app.cliente import repositorio as repositorio_do_cliente
from app.cliente.vencimento_pontos import lancar_vencimentos
from app.clientes import repositorio
from app.clientes.erros import ClienteNaoEncontrado
from app.core.papeis import UsuarioAtual

__all__ = [
    "PAPEIS_DO_PAINEL",
    "ficha",
    "listar",
    "montar_escopo",
    "resolver_loja",
    "vulto_mais",
]


def pode_ver_compras(usuario: UsuarioAtual) -> bool:
    """Compras e valores gastos: gerente e admin. O atendente ve contato e chamados."""
    return usuario.papel in GESTAO


def listar(
    conexao: Connection,
    usuario: UsuarioAtual,
    escopo: Escopo,
    *,
    busca: str | None,
    secao: str,
    limit: int,
    offset: int,
    categoria: str | None = None,
    id_loja_cadastro: UUID | None = None,
    marca: str | None = None,
) -> dict[str, Any]:
    total, itens = repositorio.listar(
        conexao,
        escopo,
        ver_compras=pode_ver_compras(usuario),
        busca=busca,
        secao=secao,
        limit=limit,
        offset=offset,
        categoria=categoria,
        id_loja_cadastro=id_loja_cadastro,
        marca=marca,
    )
    return {"total": total, "itens": itens}


def opcoes(conexao: Connection) -> dict[str, Any]:
    """Opcoes dos filtros da lista: lojas em que ha cliente cadastrado e as categorias Vulto+."""
    return {
        "lojas_cadastro": repositorio.lojas_de_cadastro(conexao),
        "marcas": [
            {"codigo": "casa_lorenzi", "nome": "Casa Lorenzi"},
            {"codigo": "vulto", "nome": "Vulto"},
        ],
        "categorias": [
            {"codigo": c, "nome": n}
            for c, n in (
                ("ouro", "Ouro"),
                ("prata", "Prata"),
                ("bronze", "Bronze"),
                ("sem_pontos", "Sem pontos"),
            )
        ],
    }


def ficha(
    conexao: Connection, usuario: UsuarioAtual, escopo: Escopo, id_cliente: UUID
) -> dict[str, Any]:
    ver = pode_ver_compras(usuario)
    achada = repositorio.ficha(conexao, escopo, id_cliente, ver_compras=ver)
    if achada is None:
        raise ClienteNaoEncontrado()
    base = achada["base"]

    compras = base["compras"] if ver else None
    total_gasto = base["total_gasto"] if ver else None
    ticket = None
    if ver:
        ticket = (total_gasto / compras).quantize(Decimal("0.01")) if compras else Decimal("0.00")

    return {
        "cliente": {
            "id_cliente": base["id_cliente"],
            "nome": base["nome"],
            "email": base["email"],
            "telefone": base["telefone"],
            "cidade": base["cidade"],
            "cliente_desde": base["cliente_desde"],
        },
        "resumo": {
            "chamados": base["total_chamados"],
            "chamados_em_aberto": base["chamados_em_aberto"],
            "compras": compras,
            "total_gasto": total_gasto,
            "ticket_medio": ticket,
        },
        "chamados": [
            {
                "id_atendimento": c["id_atendimento"],
                "protocolo": c["protocolo"],
                "assunto": c["assunto"],
                "categoria": {"codigo": c["categoria_codigo"], "nome": c["categoria_nome"]},
                "status": {"codigo": c["status_codigo"], "nome": c["status_nome"]},
                "aberto_em": c["aberto_em"],
                "historico_vulto": c["historico_vulto"],
            }
            for c in achada["chamados"]
        ],
        "compras": (
            [
                {
                    "id_pedido": p["id_pedido"],
                    "numero_pedido": p["numero_pedido"],
                    "criado_em": p["criado_em"],
                    "loja_nome": p["loja_nome"],
                    "valor_total": p["valor_total"],
                    "status": {"codigo": p["status_codigo"], "nome": p["status_nome"]},
                }
                for p in achada["compras"]
            ]
            if ver and achada["compras"] is not None
            else None
        ),
    }


def vulto_mais(
    conexao: Connection, usuario: UsuarioAtual, escopo: Escopo, id_cliente: UUID
) -> dict[str, Any]:
    """Pontos Vulto+ do cliente para a equipe. Mesma regra da ficha: quem nao ve o cliente no seu
    escopo nao ve os pontos dele. O valor dos resgates segue a regra das compras."""
    if repositorio.ficha(conexao, escopo, id_cliente, ver_compras=False) is None:
        raise ClienteNaoEncontrado()
    aviso = lancar_vencimentos(conexao, id_cliente)
    pontos = repositorio_do_cliente.vulto_mais_cliente(conexao, id_cliente)
    extra = repositorio.resgates_e_loja_de_cadastro(conexao, id_cliente)
    ver = pode_ver_compras(usuario)
    return {
        **pontos,
        **aviso,
        "loja_cadastro": extra["loja_cadastro"],
        "resgates": [{**r, "desconto": r["desconto"] if ver else None} for r in extra["resgates"]],
    }
