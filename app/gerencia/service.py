"""Regras do inicio do gerente: escopo de loja, periodos e montagem das respostas."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.dashboard import repositorio as repositorio_de_chamados
from app.dashboard.repositorio import Filtro as FiltroDeChamados
from app.dashboard.service import periodo_anterior, resolver_loja, validar_periodo
from app.gerencia import repositorio
from app.gerencia.repositorio import CANAIS_DE_VENDA, Filtro

PAPEIS_DA_GERENCIA = (Papel.GERENTE_LOJA, Papel.ADMIN)
PECAS_NO_RANKING = 6

__all__ = ["PAPEIS_DA_GERENCIA", "loja_do_escopo", "validar_periodo"]


def loja_do_escopo(usuario: UsuarioAtual, id_loja_pedida: UUID | None) -> UUID | None:
    """Gerente so enxerga a propria loja (a do token); o admin escolhe uma ou ve a rede."""
    if usuario.papel not in PAPEIS_DA_GERENCIA:
        raise SemPermissao()
    return resolver_loja(usuario, id_loja_pedida)


def _dinheiro(valor: Any) -> float:
    return round(float(valor), 2)


def _resumo(linha: dict[str, Any]) -> dict[str, Any]:
    faturamento = _dinheiro(linha["faturamento"])
    pedidos = int(linha["pedidos"])
    online = _dinheiro(linha["faturamento_online"])
    return {
        "faturamento": faturamento,
        "pedidos": pedidos,
        "pecas": int(linha["pecas"]),
        "ticket_medio": round(faturamento / pedidos, 2) if pedidos else 0.0,
        "faturamento_online": online,
        "pedidos_online": int(linha["pedidos_online"]),
        "participacao_online": round(online / faturamento, 4) if faturamento else 0.0,
    }


def montar_dashboard(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    inicio: date,
    fim: date,
    filtro: Filtro,
) -> dict[str, Any]:
    ant_inicio, ant_fim = periodo_anterior(inicio, fim)
    admin = usuario.papel is Papel.ADMIN
    loja = repositorio.loja_por_id(conexao, filtro.id_loja) if filtro.id_loja else None
    lojas = repositorio_de_chamados.opcoes_de_loja(conexao, None if admin else usuario.id_loja)
    return {
        "periodo": {"inicio": inicio, "fim": fim},
        "periodo_anterior": {"inicio": ant_inicio, "fim": ant_fim},
        "atual": _resumo(repositorio.resumo(conexao, filtro, inicio, fim)),
        "anterior": _resumo(repositorio.resumo(conexao, filtro, ant_inicio, ant_fim)),
        "serie_diaria": [
            {
                "data": linha["data"],
                "faturamento": _dinheiro(linha["faturamento"]),
                "pedidos": int(linha["pedidos"]),
                "pecas": int(linha["pecas"]),
            }
            for linha in repositorio.serie_diaria(conexao, filtro, inicio, fim)
        ],
        "movimento_semana": [
            {
                "dia_semana": int(linha["dia_semana"]),
                "pedidos": int(linha["pedidos"]),
                "dias": int(linha["dias"]),
                "pedidos_por_dia": (
                    round(int(linha["pedidos"]) / int(linha["dias"]), 2) if linha["dias"] else 0.0
                ),
            }
            for linha in repositorio.movimento_semana(conexao, filtro, inicio, fim)
        ],
        "pecas_mais_vendidas": [
            {
                **linha,
                "unidades": int(linha["unidades"]),
                "faturamento": _dinheiro(linha["faturamento"]),
            }
            for linha in repositorio.pecas_mais_vendidas(
                conexao, filtro, inicio, fim, limite=PECAS_NO_RANKING
            )
        ],
        "opcoes": {
            "lojas": lojas,
            "canais": [{"codigo": c, "nome": n} for c, n in CANAIS_DE_VENDA],
            "categorias": repositorio.categorias_de_produto(conexao),
        },
        "escopo": {
            "papel": usuario.papel.value if usuario.papel else "",
            "id_loja": usuario.id_loja,
            "loja_nome": loja["nome"] if loja else None,
            "pode_escolher_loja": admin,
        },
    }


def montar_reposicao(conexao: Connection, filtro: Filtro, *, limite: int) -> dict[str, Any]:
    total, itens = repositorio.reposicao(conexao, filtro, limite=limite)
    return {
        "total": total,
        "itens": [
            {
                **item,
                "giro_diario": (
                    round(float(item["giro_diario"]), 3)
                    if item["giro_diario"] is not None
                    else None
                ),
                "dias_cobertura": (
                    round(float(item["dias_cobertura"]), 1)
                    if item["dias_cobertura"] is not None
                    else None
                ),
            }
            for item in itens
        ],
    }


def montar_lojas(conexao: Connection, filtro: Filtro) -> dict[str, Any]:
    """O gerente ve so a propria loja; o admin, a rede. O escopo vem do filtro (do token)."""
    return {
        "itens": [
            {
                **linha,
                "equipe": int(linha["equipe"]),
                "unidades_em_estoque": int(linha["unidades_em_estoque"]),
                "pecas_em_alerta": int(linha["pecas_em_alerta"]),
                "vendas_30_dias": _dinheiro(linha["vendas_30_dias"]),
                "chamados_abertos": int(linha["chamados_abertos"]),
            }
            for linha in repositorio.lojas_da_rede(conexao, filtro.id_loja)
        ]
    }


def montar_pendencias(
    conexao: Connection, filtro: Filtro, *, incluir_chamados_sem_loja: bool
) -> dict[str, int]:
    ajustes = repositorio.ajustes_para_aprovar(conexao, filtro)
    transferencias = repositorio.transferencias_aguardando(conexao, filtro)
    chamados = repositorio_de_chamados.contadores_da_fila(
        conexao,
        FiltroDeChamados(filtro.id_loja, incluir_sem_loja=incluir_chamados_sem_loja),
    )["sem_resposta"]
    return {
        "ajustes_para_aprovar": int(ajustes),
        "transferencias_aguardando": int(transferencias),
        "chamados_sem_resposta": int(chamados),
        "total": int(ajustes) + int(transferencias) + int(chamados),
    }


def _horas(valor: Any) -> float | None:
    return round(float(valor), 2) if valor is not None else None


def _resumo_atendimento(linha: dict[str, Any]) -> dict[str, Any]:
    total = int(linha["total"])
    resolvidos = int(linha["resolvidos"])
    return {
        "total": total,
        "resolvidos": resolvidos,
        "taxa_resolucao": round(resolvidos / total, 4) if total else 0.0,
        "resposta_media_horas": _horas(linha["resposta_media_horas"]),
    }


def _grupo(
    conexao: Connection,
    *,
    id_grupo: str,
    nome: str,
    id_loja: UUID | None,
    ids: tuple[UUID, ...],
    inicio: date,
    fim: date,
    categoria: str | None,
    canal: str | None,
) -> dict[str, Any]:
    vendas = Filtro(categoria=categoria, canal=canal, ids_loja=ids)
    return {
        "id": id_grupo,
        "nome": nome,
        "id_loja": id_loja,
        "serie_diaria": [
            {
                "data": linha["data"],
                "faturamento": _dinheiro(linha["faturamento"]),
                "pedidos": int(linha["pedidos"]),
                "pecas": int(linha["pecas"]),
            }
            for linha in repositorio.serie_diaria(conexao, vendas, inicio, fim)
        ],
        "categorias": [
            {"categoria": c["categoria"], "faturamento": _dinheiro(c["faturamento"])}
            for c in repositorio.vendas_por_categoria(conexao, vendas, inicio, fim)
        ],
        "motivos": [
            {"codigo": m["codigo"], "nome": m["nome"], "total": int(m["total"])}
            for m in repositorio_de_chamados.por_categoria(
                conexao, FiltroDeChamados(ids_loja=ids), inicio, fim
            )
        ],
    }


def _unidades(
    conexao: Connection,
    lojas: list[dict[str, Any]],
    selecao: Filtro,
    *,
    inicio: date,
    fim: date,
    ant_inicio: date,
    ant_fim: date,
    abertos_por_loja: dict[Any, int],
) -> list[dict[str, Any]]:
    atual = {x["id_loja"]: x for x in repositorio.vendas_por_loja(conexao, selecao, inicio, fim)}
    anterior = {
        x["id_loja"]: x for x in repositorio.vendas_por_loja(conexao, selecao, ant_inicio, ant_fim)
    }
    estoque = {x["id_loja"]: x for x in repositorio.estoque_por_loja(conexao, selecao)}
    respostas = {
        x["id_loja"]: x
        for x in repositorio_de_chamados.resumo_por_loja(
            conexao, FiltroDeChamados(ids_loja=selecao.ids_loja), inicio, fim
        )
    }
    linhas = []
    for loja in lojas:
        venda = atual.get(loja["id_loja"])
        faturamento = _dinheiro(venda["faturamento"]) if venda else 0.0
        pedidos = int(venda["pedidos"]) if venda else 0
        online = _dinheiro(venda["faturamento_online"]) if venda else 0.0
        antes = anterior.get(loja["id_loja"])
        saldo = estoque.get(loja["id_loja"])
        resposta = respostas.get(loja["id_loja"])
        linhas.append(
            {
                "id_loja": loja["id_loja"],
                "codigo": loja["codigo"],
                "nome": loja["nome"],
                "cidade": loja["cidade"],
                "faturamento": faturamento,
                "faturamento_anterior": _dinheiro(antes["faturamento"]) if antes else 0.0,
                "pedidos": pedidos,
                "ticket_medio": round(faturamento / pedidos, 2) if pedidos else 0.0,
                "participacao_online": round(online / faturamento, 4) if faturamento else 0.0,
                "unidades_em_estoque": int(saldo["unidades"]) if saldo else 0,
                "pecas_esgotadas": int(saldo["esgotadas"]) if saldo else 0,
                "chamados_abertos": abertos_por_loja.get(loja["id_loja"], 0),
                "resposta_media_horas": (
                    _horas(resposta["resposta_media_horas"]) if resposta else None
                ),
            }
        )
    return linhas


def montar_rede(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    inicio: date,
    fim: date,
    ids_loja: tuple[UUID, ...],
    categoria: str | None,
    canal: str | None,
) -> dict[str, Any]:
    """Inicio do admin: a rede (ou as lojas escolhidas) lado a lado. Exclusivo do admin."""
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao()
    ant_inicio, ant_fim = periodo_anterior(inicio, fim)
    selecao = Filtro(categoria=categoria, canal=canal, ids_loja=ids_loja)
    # Chamados nao tem canal de venda nem categoria de produto: so o recorte de lojas vale.
    chamados = FiltroDeChamados(ids_loja=ids_loja)
    lojas = repositorio.lojas_ativas(conexao, ids_loja)

    if ids_loja:
        series = [(str(x["id_loja"]), x["nome"], x["id_loja"], (x["id_loja"],)) for x in lojas]
    else:
        series = [("rede", "Rede", None, ())]
    grupos = [
        _grupo(
            conexao,
            id_grupo=id_grupo,
            nome=nome,
            id_loja=id_loja,
            ids=ids,
            inicio=inicio,
            fim=fim,
            categoria=categoria,
            canal=canal,
        )
        for id_grupo, nome, id_loja, ids in series
    ]

    abertos = repositorio_de_chamados.abertos_agora(conexao, ids_loja)
    # Chamados da fila geral (sem loja) so entram quando se olha a rede toda.
    abertos_por_loja = {x["id_loja"]: int(x["total"]) for x in abertos if x["id_loja"]}
    sem_loja = sum(int(x["total"]) for x in abertos if x["id_loja"] is None and not ids_loja)
    estoque = repositorio.estoque_total(conexao, selecao)
    return {
        "periodo": {"inicio": inicio, "fim": fim},
        "periodo_anterior": {"inicio": ant_inicio, "fim": ant_fim},
        "atual": _resumo(repositorio.resumo(conexao, selecao, inicio, fim)),
        "anterior": _resumo(repositorio.resumo(conexao, selecao, ant_inicio, ant_fim)),
        "grupos": grupos,
        "pecas_mais_vendidas": [
            {
                **linha,
                "unidades": int(linha["unidades"]),
                "faturamento": _dinheiro(linha["faturamento"]),
            }
            for linha in repositorio.pecas_mais_vendidas(
                conexao, selecao, inicio, fim, limite=PECAS_NO_RANKING
            )
        ],
        "atendimento": {
            "atual": _resumo_atendimento(
                repositorio_de_chamados.resumo(conexao, chamados, inicio, fim)
            ),
            "anterior": _resumo_atendimento(
                repositorio_de_chamados.resumo(conexao, chamados, ant_inicio, ant_fim)
            ),
            "abertos_agora": sum(abertos_por_loja.values()) + sem_loja,
        },
        "estoque": {
            "unidades": int(estoque["unidades"]),
            "pecas": int(estoque["pecas"]),
            "produtos": int(estoque["produtos"]),
            "pecas_esgotadas": int(estoque["esgotadas"]),
        },
        "unidades": _unidades(
            conexao,
            lojas,
            selecao,
            inicio=inicio,
            fim=fim,
            ant_inicio=ant_inicio,
            ant_fim=ant_fim,
            abertos_por_loja=abertos_por_loja,
        ),
        "opcoes": {
            "lojas": repositorio_de_chamados.opcoes_de_loja(conexao, None),
            "canais": [{"codigo": c, "nome": n} for c, n in CANAIS_DE_VENDA],
            "categorias": repositorio.categorias_de_produto(conexao),
        },
    }
