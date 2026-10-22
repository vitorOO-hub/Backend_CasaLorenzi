"""Fila das vendas Vulto que a importacao nao conseguiu virar pedido (so admin).

A lista nunca le `dados_origem`: o JSON interno pode conter CPF, telefone ou e-mail. O detalhe de
uma venda le o JSON no servidor e devolve so o que serve para resolver (data, loja, canal, valores,
itens, sugestoes); o CPF sai mascarado. Resolver e importar (vira pedido, com o cliente e as pecas
escolhidos pelo admin) ou descartar (com o porque). As regras de loja, canal, status e SKU sao as da
importacao em lote (scripts/vulto_integracao).
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.clientes.repositorio import escapar_busca
from app.core.erros_auth import SemPermissao
from app.core.papeis import Papel, UsuarioAtual
from app.gestao import auditoria
from app.gestao.erros import (
    ClienteDaVendaInvalido,
    PecaDaVendaInvalida,
    PecaRepetidaNaVenda,
    VendaJaResolvida,
    VendaNaoImportavel,
    VendaPendenteNaoEncontrada,
)
from scripts.vulto_integracao.clientes_vendas import cpf_valido, normalizar_cpf
from scripts.vulto_integracao.lojas import CODIGO_LOJA_POR_ID_VULTO
from scripts.vulto_integracao.plano_importacao import CANAL_POR_LOJA_VULTO, STATUS_POR_ORIGEM
from scripts.vulto_integracao.skus import normalizar_sku_reduzido, resolver_id_variacao
from scripts.vulto_integracao.valores_vendas import reconciliar_valores_venda

# Grupos de motivo (prefixo antes dos dois pontos), na ordem em que aparecem na tela.
GRUPOS = (
    "cliente",
    "valores",
    "sku",
    "itens",
    "item",
    "loja",
    "status",
    "data_hora",
    "duplicidade",
)
ESTADOS = ("pendente", "importada", "descartada")

FILTRO = """
    origem = 'vulto' AND estado = :estado
    AND (CAST(:grupo AS text) IS NULL
         OR EXISTS (SELECT 1 FROM unnest(motivos) m WHERE m LIKE CAST(:grupo AS text) || ':%'))
"""

CONTAR = text(f"SELECT count(*) FROM venda_importacao_pendente WHERE {FILTRO}")  # nosec B608

# Nao selecionar dados_origem: o JSON interno pode conter CPF, telefone ou e-mail.
LISTAR = text(
    f"""
    SELECT id_venda_pendente, venda_id_origem, status_origem, motivos,
           quantidade_itens, criada_em, estado, resolvida_em
    FROM venda_importacao_pendente
    WHERE {FILTRO}
    ORDER BY criada_em, venda_id_origem
    LIMIT :limite OFFSET :offset
    """  # nosec B608
)

POR_GRUPO = text(
    """
    SELECT split_part(m, ':', 1) AS grupo, count(DISTINCT id_venda_pendente) AS vendas
    FROM venda_importacao_pendente, unnest(motivos) m
    WHERE origem = 'vulto' AND estado = :estado
    GROUP BY 1
    """
)


def _so_admin(usuario: UsuarioAtual) -> None:
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao()


def listar(
    conexao: Connection,
    usuario: UsuarioAtual,
    *,
    limit: int = 50,
    offset: int = 0,
    grupo: str | None = None,
    estado: str = "pendente",
) -> dict[str, Any]:
    _so_admin(usuario)
    filtro = {"estado": estado, "grupo": grupo}
    total = int(conexao.execute(CONTAR, filtro).scalar_one())
    linhas = conexao.execute(LISTAR, {**filtro, "limite": limit, "offset": offset}).mappings()
    return {
        "total": total,
        "itens": [
            {
                "id_venda_pendente": linha["id_venda_pendente"],
                "venda_id_origem": linha["venda_id_origem"],
                "status_origem": linha["status_origem"],
                "motivos": list(linha["motivos"]),
                "quantidade_itens": int(linha["quantidade_itens"]),
                "criada_em": linha["criada_em"],
                "estado": linha.get("estado", estado),
                "resolvida_em": linha.get("resolvida_em"),
            }
            for linha in linhas
        ],
    }


def resumo_por_grupo(conexao: Connection, usuario: UsuarioAtual, estado: str) -> list[dict]:
    """Quantas vendas tem cada grupo de motivo (uma venda pode estar em mais de um)."""
    _so_admin(usuario)
    contagem = {
        linha["grupo"]: int(linha["vendas"])
        for linha in conexao.execute(POR_GRUPO, {"estado": estado}).mappings()
    }
    return [{"grupo": g, "vendas": contagem[g]} for g in GRUPOS if g in contagem]


# ---------- detalhe ----------


def _texto(valor: object) -> str:
    return "" if valor is None else str(valor).strip()


def _dinheiro(valor: object) -> Decimal | None:
    try:
        return Decimal(_texto(valor)) if _texto(valor) else None
    except InvalidOperation:
        return None


def _data(valor: object) -> datetime | None:
    try:
        data = datetime.fromisoformat(_texto(valor))
    except ValueError:
        return None
    return data if data.tzinfo else None


def _cpf_da_venda(dados: dict[str, Any]) -> str | None:
    venda, compra = dados.get("venda") or {}, dados.get("compra") or {}
    for valor in (venda.get("cpf_padronizado"), compra.get("cpf_cliente_quando_identificavel")):
        cpf = normalizar_cpf(valor)
        if cpf and cpf_valido(cpf):
            return cpf
    return None


def _origem(conexao: Connection, id_venda: UUID, *, travar: bool = False) -> dict[str, Any]:
    linha = (
        conexao.execute(
            text(
                f"""
                SELECT id_venda_pendente, id_lote, venda_id_origem, status_origem, estado,
                       motivos, dados_origem, resolvida_em, observacao_resolucao, id_pedido
                FROM venda_importacao_pendente
                WHERE id_venda_pendente = CAST(:id AS uuid) AND origem = 'vulto'
                {"FOR UPDATE" if travar else ""}
                """  # nosec B608
            ),
            {"id": str(id_venda)},
        )
        .mappings()
        .first()
    )
    if linha is None:
        raise VendaPendenteNaoEncontrada()
    return dict(linha)


def _destino(conexao: Connection, venda: dict[str, Any]) -> dict[str, Any]:
    """Loja, canal, status e data do pedido, pelas regras da importacao. Nulo = nao reconhecido."""
    try:
        loja_vulto = int(_texto(venda.get("loja_id")))
    except ValueError:
        loja_vulto = None
    loja = None
    if loja_vulto in CODIGO_LOJA_POR_ID_VULTO:
        loja = (
            conexao.execute(
                text("SELECT id_loja, nome FROM loja WHERE codigo = :c"),
                {"c": CODIGO_LOJA_POR_ID_VULTO[loja_vulto]},
            )
            .mappings()
            .first()
        )
    status = STATUS_POR_ORIGEM.get(_texto(venda.get("status_padronizado")).lower())
    return {
        "id_loja": loja["id_loja"] if loja else None,
        "loja": loja["nome"] if loja else None,
        "canal": CANAL_POR_LOJA_VULTO.get(loja_vulto) if loja_vulto else None,
        "status": status,
        "vendida_em": _data(venda.get("data_hora_padronizada")),
    }


def _variacoes(conexao: Connection, skus: list[str]) -> dict[str, dict[str, Any]]:
    candidatos = {s for s in skus if s} | {
        n for n in (normalizar_sku_reduzido(s) for s in skus) if n
    }
    linhas = conexao.execute(
        text(
            """
            SELECT v.id_variacao, v.sku, p.nome || ' · ' || v.cor || ', ' || v.tamanho AS nome
            FROM variacao_produto v JOIN produto p ON p.id_produto = v.id_produto
            WHERE v.sku = ANY(CAST(:skus AS text[]))
            """
        ),
        {"skus": sorted(candidatos)},
    ).mappings()
    return {linha["sku"]: dict(linha) for linha in linhas}


def detalhe(conexao: Connection, usuario: UsuarioAtual, id_venda: UUID) -> dict[str, Any]:
    _so_admin(usuario)
    origem = _origem(conexao, id_venda)
    dados = origem["dados_origem"] or {}
    venda, itens = dados.get("venda") or {}, list(dados.get("itens") or [])

    cpf = _cpf_da_venda(dados)
    sugestao_cliente = None
    if cpf:
        clientes = (
            conexao.execute(
                text(
                    """
                    SELECT u.id_usuario, u.nome FROM usuario u
                    JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
                    WHERE t.codigo = 'cliente' AND u.documento = :cpf
                    """
                ),
                {"cpf": cpf},
            )
            .mappings()
            .all()
        )
        if len(clientes) == 1:
            sugestao_cliente = {
                "id_cliente": clientes[0]["id_usuario"],
                "nome": clientes[0]["nome"],
            }

    por_sku = _variacoes(conexao, [_texto(i.get("sku_padronizado")) for i in itens])
    variacao_por_sku = {sku: v["id_variacao"] for sku, v in por_sku.items()}
    valores = reconciliar_valores_venda(venda, itens)
    linhas_itens = []
    for item in valores["itens"]:
        sku = _texto(item.get("sku_padronizado"))
        id_variacao = resolver_id_variacao(sku, variacao_por_sku)
        sugerida = next((v for v in por_sku.values() if v["id_variacao"] == id_variacao), None)
        try:
            quantidade = int(Decimal(_texto(item.get("qtd"))))
        except (InvalidOperation, ValueError):
            quantidade = 0
        linhas_itens.append(
            {
                "sku_origem": sku or _texto(item.get("sku")),
                "descricao": _texto(item.get("descricao")) or None,
                "quantidade": quantidade,
                "preco_unitario": _dinheiro(item.get("preco_unitario_decimal")),
                "variacao_sugerida": sugerida,
            }
        )

    destino = _destino(conexao, venda)
    return {
        "id_venda_pendente": origem["id_venda_pendente"],
        "venda_id_origem": origem["venda_id_origem"],
        "estado": origem["estado"],
        "motivos": list(origem["motivos"]),
        "status_origem": origem["status_origem"],
        "resolvida_em": origem["resolvida_em"],
        "observacao_resolucao": origem["observacao_resolucao"],
        "loja": destino["loja"],
        "canal": destino["canal"],
        "status_destino": destino["status"],
        "vendida_em": destino["vendida_em"],
        "vendedor": _texto(venda.get("vendedor_padronizado")) or None,
        "total": _dinheiro(venda.get("total_decimal")),
        "frete": _dinheiro(venda.get("frete_decimal")) or Decimal("0.00"),
        "desconto": _dinheiro(venda.get("desconto_decimal")) or Decimal("0.00"),
        "total_calculado": valores.get("total_calculado"),
        "situacao_valores": valores["situacao"],
        "cpf_final": cpf[-4:] if cpf else None,
        "sugestao_cliente": sugestao_cliente,
        "itens": linhas_itens,
    }


# ---------- resolucao ----------


def _pessoa(conexao: Connection, usuario: UsuarioAtual) -> str | None:
    pessoa = conexao.execute(
        text("SELECT id_usuario FROM usuario WHERE auth_user_id = CAST(:a AS uuid) AND ativo"),
        {"a": str(usuario.id_auth)},
    ).scalar()
    return str(pessoa) if pessoa else None


def _pendente(conexao: Connection, id_venda: UUID) -> dict[str, Any]:
    origem = _origem(conexao, id_venda, travar=True)
    if origem["estado"] != "pendente":
        raise VendaJaResolvida()
    return origem


def descartar(
    conexao: Connection, usuario: UsuarioAtual, id_venda: UUID, observacao: str
) -> dict[str, Any]:
    _so_admin(usuario)
    origem = _pendente(conexao, id_venda)
    conexao.execute(
        text(
            """
            UPDATE venda_importacao_pendente
            SET estado = 'descartada', resolvida_em = now(), atualizada_em = now(),
                id_usuario_resolveu = CAST(:u AS uuid), observacao_resolucao = :obs
            WHERE id_venda_pendente = CAST(:id AS uuid)
            """
        ),
        {"id": str(id_venda), "u": _pessoa(conexao, usuario), "obs": observacao},
    )
    auditoria.registrar(
        conexao,
        usuario,
        "Descartou venda pendente do Vulto",
        f"venda {origem['venda_id_origem']}: {observacao}",
    )
    return detalhe(conexao, usuario, id_venda)


def importar(
    conexao: Connection, usuario: UsuarioAtual, id_venda: UUID, resolucao: Any
) -> dict[str, Any]:
    """Grava o pedido com o cliente, as pecas e o total escolhidos. Loja, canal, status e data
    vem da venda de origem; sem eles a venda nao e importavel por aqui."""
    _so_admin(usuario)
    origem = _pendente(conexao, id_venda)
    venda = (origem["dados_origem"] or {}).get("venda") or {}
    destino = _destino(conexao, venda)
    faltam = [campo for campo in ("id_loja", "canal", "status", "vendida_em") if not destino[campo]]
    if faltam:
        raise VendaNaoImportavel()

    cliente = conexao.execute(
        text(
            """
            SELECT 1 FROM usuario u JOIN tipo_usuario t ON t.id_tipo_usuario = u.id_tipo_usuario
            WHERE u.id_usuario = CAST(:c AS uuid) AND t.codigo = 'cliente'
            """
        ),
        {"c": str(resolucao.id_cliente)},
    ).scalar()
    if cliente is None:
        raise ClienteDaVendaInvalido()
    ids = sorted({str(item.id_variacao) for item in resolucao.itens})
    if len(ids) != len(resolucao.itens):
        raise PecaRepetidaNaVenda()
    achadas = conexao.execute(
        text("SELECT count(*) FROM variacao_produto WHERE id_variacao = ANY(CAST(:ids AS uuid[]))"),
        {"ids": ids},
    ).scalar_one()
    if achadas != len(ids):
        raise PecaDaVendaInvalida()

    numero = f"VULTO-{origem['venda_id_origem']}"
    if conexao.execute(
        text("SELECT 1 FROM pedido WHERE numero_pedido = :n"), {"n": numero}
    ).scalar():
        raise VendaJaResolvida()
    id_pedido = conexao.execute(
        text(
            """
            INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido, valor_total,
                                valor_frete, canal_venda, criado_em, observacao)
            VALUES (:numero, CAST(:loja AS uuid), CAST(:cliente AS uuid),
                    (SELECT id_status_pedido FROM status_pedido WHERE codigo = :status),
                    :total, :frete, :canal, :criado_em, :obs)
            RETURNING id_pedido
            """
        ),
        {
            "numero": numero,
            "loja": str(destino["id_loja"]),
            "cliente": str(resolucao.id_cliente),
            "status": destino["status"],
            "total": resolucao.valor_total,
            "frete": resolucao.valor_frete,
            "canal": destino["canal"],
            "criado_em": destino["vendida_em"],
            "obs": (
                f"Importado do Vulto pela fila de pendentes; venda de origem "
                f"{origem['venda_id_origem']}; "
                f"status original: {origem['status_origem'] or 'ausente'}."
            ),
        },
    ).scalar_one()
    for item in resolucao.itens:
        conexao.execute(
            text(
                """
                INSERT INTO item_pedido (id_pedido, id_variacao, quantidade, preco_unitario)
                VALUES (CAST(:p AS uuid), CAST(:v AS uuid), :q, :preco)
                """
            ),
            {
                "p": str(id_pedido),
                "v": str(item.id_variacao),
                "q": item.quantidade,
                "preco": item.preco_unitario,
            },
        )
    conexao.execute(
        text(
            """
            INSERT INTO venda_importacao_origem (
                id_lote, id_pedido, origem, chave_origem, venda_id_origem, compra_id_origem,
                funcionario_id_origem, vendedor_padronizado, dados_origem)
            SELECT vp.id_lote, CAST(:p AS uuid), 'vulto', vp.venda_id_origem, vp.venda_id_origem,
                   NULLIF(COALESCE(vp.dados_origem->'venda'->>'compra_id_resolvida',
                                   vp.dados_origem->'venda'->>'compra_id'), ''),
                   NULLIF(vp.dados_origem->'venda'->>'funcionario_id', ''),
                   NULLIF(vp.dados_origem->'venda'->>'vendedor_padronizado', ''),
                   vp.dados_origem
            FROM venda_importacao_pendente vp
            WHERE vp.id_venda_pendente = CAST(:id AS uuid)
            """
        ),
        {"p": str(id_pedido), "id": str(id_venda)},
    )
    conexao.execute(
        text(
            """
            UPDATE venda_importacao_pendente
            SET estado = 'importada', id_pedido = CAST(:p AS uuid), resolvida_em = now(),
                atualizada_em = now(), id_usuario_resolveu = CAST(:u AS uuid),
                observacao_resolucao = :obs
            WHERE id_venda_pendente = CAST(:id AS uuid)
            """
        ),
        {
            "p": str(id_pedido),
            "id": str(id_venda),
            "u": _pessoa(conexao, usuario),
            "obs": resolucao.observacao,
        },
    )
    auditoria.registrar(
        conexao,
        usuario,
        "Importou venda pendente do Vulto",
        f"venda {origem['venda_id_origem']} → pedido {numero}",
    )
    return detalhe(conexao, usuario, id_venda)


def buscar_variacoes(conexao: Connection, usuario: UsuarioAtual, busca: str) -> list[dict]:
    """Pecas para trocar o SKU que a venda de origem nao encontrou (por SKU ou nome)."""
    _so_admin(usuario)
    termo = escapar_busca(busca)
    linhas = conexao.execute(
        text(
            """
            SELECT v.id_variacao, v.sku, p.nome || ' · ' || v.cor || ', ' || v.tamanho AS nome
            FROM variacao_produto v JOIN produto p ON p.id_produto = v.id_produto
            WHERE v.sku ILIKE :t ESCAPE '\\' OR p.nome ILIKE :t ESCAPE '\\'
            ORDER BY v.ativa DESC, p.nome, v.cor, v.tamanho
            LIMIT 20
            """
        ),
        {"t": termo},
    ).mappings()
    return [dict(linha) for linha in linhas]
