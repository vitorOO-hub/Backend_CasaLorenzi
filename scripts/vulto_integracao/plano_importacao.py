"""Monta um plano sem persistir; a exportacao detalhada inclui dados de origem restritos."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .clientes_vendas import (
    indexar_clientes_por_cpf,
    indexar_compras_por_id,
    resolver_id_cliente_venda,
)
from .lojas import CODIGO_LOJA_POR_ID_VULTO
from .skus import resolver_id_variacao
from .valores_vendas import reconciliar_valores_venda

STATUS_POR_ORIGEM = {
    "aguardando": "aguardando_pagamento",
    "cancelada": "cancelado",
    "concluida": "pago",
    "estornada": "cancelado",
}
CANAL_POR_LOJA_VULTO = {
    1: "loja",
    2: "loja",
    3: "loja",
    4: "loja",
    5: "online",
    6: "online",
}


def _texto(valor: object) -> str:
    return "" if valor is None else str(valor).strip()


def _data_hora(valor: object) -> str | None:
    texto = _texto(valor)
    if not texto:
        return None
    try:
        data = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    if data.tzinfo is None:
        return None
    return data.isoformat()


def _dinheiro(valor: object) -> Decimal | None:
    if valor is None or not _texto(valor):
        return None
    try:
        return Decimal(_texto(valor).replace(",", ".")).quantize(Decimal("0.01"))
    except Exception:
        return None


def _json_valor(valor: object) -> object:
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    return str(valor)


def _campos_origem(registro: Mapping[str, object], campos: tuple[str, ...]) -> dict[str, object]:
    return {
        campo: _json_valor(registro[campo])
        for campo in campos
        if campo in registro and registro[campo] is not None
    }


VENDA_ORIGEM = (
    "id", "loja_id", "status", "status_padronizado", "origem", "canal",
    "canal_padronizado", "criado_em", "data_hora_padronizada", "total",
    "total_decimal", "desconto", "desconto_decimal", "frete", "frete_decimal",
    "cliente_ref", "cpf_cliente", "cpf_padronizado", "telefone", "email", "vendedor",
    "vendedor_padronizado", "compra_id", "compra_id_resolvida", "situacao_vinculo_compra",
)
COMPRA_ORIGEM = (
    "id", "cliente_ref", "cpf_cliente_quando_identificavel", "email",
    "telefone", "criado_em", "data_hora_padronizada", "loja_id",
)
ITEM_ORIGEM = (
    "id", "venda_id", "sku", "sku_padronizado", "descricao", "qtd",
    "preco_unitario", "preco_unitario_decimal",
)


def planejar_importacao(
    vendas: Iterable[Mapping[str, object]],
    itens: Iterable[Mapping[str, object]],
    compras: Iterable[Mapping[str, object]],
    usuarios: Iterable[Mapping[str, object]],
    tipos_usuario: Iterable[Mapping[str, object]],
    lojas: Iterable[Mapping[str, object]],
    status_pedido: Iterable[Mapping[str, object]],
    variacoes: Iterable[Mapping[str, object]],
    codigo_lote: str = "VULTO-VENDAS-MANUAL",
) -> dict[str, Any]:
    """Retorna pedidos/itens prontos e pendencias; nao escreve no banco."""
    compras_lista = [dict(compra) for compra in compras]
    vendas_por_id = {_texto(venda.get("id")): dict(venda) for venda in vendas}
    itens_por_venda: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in itens:
        itens_por_venda[_texto(item.get("venda_id"))].append(dict(item))

    tipos_por_id = {
        _texto(tipo.get("id_tipo_usuario")): _texto(tipo.get("codigo"))
        for tipo in tipos_usuario
    }
    clientes_por_cpf = indexar_clientes_por_cpf(usuarios, tipos_por_id)
    cpfs_por_compra = indexar_compras_por_id(compras_lista)
    compras_por_id = {_texto(compra.get("id")): compra for compra in compras_lista}
    lojas_por_codigo = {
        _texto(loja.get("codigo")): _texto(loja.get("id_loja")) for loja in lojas
    }
    status_por_codigo = {
        _texto(status.get("codigo")): _texto(status.get("id_status_pedido"))
        for status in status_pedido
    }
    variacao_por_sku = {
        _texto(variacao.get("sku")): _texto(variacao.get("id_variacao"))
        for variacao in variacoes
        if _texto(variacao.get("sku")) and _texto(variacao.get("id_variacao"))
    }

    pedidos, itens_pedido, pendencias, rastreabilidade = [], [], [], []
    for venda_id, venda in vendas_por_id.items():
        motivos = []
        cliente_id, resolucao = resolver_id_cliente_venda(
            venda, cpfs_por_compra, clientes_por_cpf
        )
        if cliente_id is None:
            motivos.append(f"cliente:{resolucao.motivo}")

        loja_id_legado = _texto(venda.get("loja_id"))
        try:
            loja_codigo = CODIGO_LOJA_POR_ID_VULTO[int(loja_id_legado)]
            loja_id = lojas_por_codigo.get(loja_codigo)
            canal = CANAL_POR_LOJA_VULTO.get(int(loja_id_legado))
        except (ValueError, KeyError):
            loja_codigo, loja_id, canal = None, None, None
        if loja_id is None or canal is None:
            motivos.append("loja:sem_correspondencia_ou_nao_aplicavel")

        status_origem = _texto(venda.get("status_padronizado")).lower()
        status_codigo = STATUS_POR_ORIGEM.get(status_origem)
        status_id = status_por_codigo.get(status_codigo or "")
        if status_id is None:
            motivos.append("status:codigo_ausente_no_destino")

        criado_em = _data_hora(venda.get("data_hora_padronizada"))
        if criado_em is None:
            motivos.append("data_hora:ausente_invalida_ou_sem_fuso")

        total = _dinheiro(venda.get("total_decimal"))
        frete = _dinheiro(venda.get("frete_decimal")) or Decimal("0.00")
        resultado_valores = reconciliar_valores_venda(venda, itens_por_venda.get(venda_id, []))
        if resultado_valores["situacao"] not in {"sem_ajuste", "desconto_rateado"}:
            motivos.append(f"valores:{resultado_valores['situacao']}")
        if total is None or total < 0 or frete < 0:
            motivos.append("valores:total_ou_frete_invalido")

        linhas_item = resultado_valores["itens"]
        por_sku: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item in linhas_item:
            sku = _texto(item.get("sku_padronizado"))
            variacao_id = resolver_id_variacao(sku, variacao_por_sku)
            if not variacao_id:
                motivos.append("sku:variacao_nao_encontrada")
                continue
            try:
                quantidade_decimal = Decimal(_texto(item.get("qtd")))
                preco = _dinheiro(item.get("preco_unitario_decimal"))
            except Exception:
                motivos.append("item:quantidade_ou_preco_invalido")
                continue
            if (
                preco is None
                or preco < 0
                or quantidade_decimal != quantidade_decimal.to_integral_value()
                or quantidade_decimal <= 0
            ):
                motivos.append("item:quantidade_nao_positiva_ou_nao_inteira")
                continue
            por_sku[sku].append(
                {
                    "id_variacao": variacao_id,
                    "quantidade": int(quantidade_decimal),
                    "preco_unitario": preco,
                }
            )

        itens_da_venda = []
        for _, linhas in por_sku.items():
            precos = {linha["preco_unitario"] for linha in linhas}
            if len(precos) != 1:
                motivos.append("sku:linhas_duplicadas_com_precos_diferentes")
                continue
            itens_da_venda.append(
                {
                    "id_variacao": linhas[0]["id_variacao"],
                    "quantidade": sum(linha["quantidade"] for linha in linhas),
                    "preco_unitario": linhas[0]["preco_unitario"],
                }
            )
        if not itens_da_venda:
            motivos.append("itens:nenhum_item_importavel")

        if motivos:
            compra_id = _texto(venda.get("compra_id_resolvida")) or _texto(
                venda.get("compra_id")
            )
            linhas_origem = itens_por_venda.get(venda_id, [])
            pendencias.append(
                {
                    "venda_id": venda_id,
                    "origem": "vulto",
                    "status_origem": status_origem or None,
                    "motivos": sorted(set(motivos)),
                    "dados_origem": {
                        "venda": _campos_origem(venda, VENDA_ORIGEM),
                        "itens": [
                            _campos_origem(item, ITEM_ORIGEM) for item in linhas_origem
                        ],
                        "compra": _campos_origem(compras_por_id[compra_id], COMPRA_ORIGEM)
                        if compra_id in compras_por_id
                        else None,
                    },
                }
            )
            continue

        pedidos.append(
            {
                "numero_pedido": f"VULTO-{venda_id}",
                "id_loja": loja_id,
                "id_cliente": cliente_id,
                "id_status_pedido": status_id,
                "valor_total": total,
                "valor_frete": frete,
                "canal_venda": canal,
                "criado_em": criado_em,
                "observacao": (
                    f"Importado do Vulto; venda de origem {venda_id}; "
                    f"status original: {status_origem or 'ausente'}."
                ),
                "origem_importacao": "vulto",
                "chave_origem": venda_id,
                "venda_id_origem": venda_id,
                "compra_id_origem": _texto(venda.get("compra_id_resolvida"))
                or _texto(venda.get("compra_id")) or None,
                "funcionario_id_origem": _texto(venda.get("funcionario_id")) or None,
                "vendedor_padronizado": _texto(venda.get("vendedor_padronizado")) or None,
                "dados_origem": {
                    "venda": _campos_origem(venda, tuple(venda.keys())),
                    "itens": [
                        _campos_origem(item, tuple(item.keys()))
                        for item in itens_por_venda.get(venda_id, [])
                    ],
                },
            }
        )
        for item in itens_da_venda:
            itens_pedido.append({"numero_pedido": f"VULTO-{venda_id}", **item})
        rastreabilidade.append(
            {
                "numero_pedido": f"VULTO-{venda_id}",
                "origem": "vulto",
                "chave_origem": venda_id,
                "venda_id_origem": venda_id,
                "compra_id_origem": pedidos[-1]["compra_id_origem"],
                "funcionario_id_origem": pedidos[-1]["funcionario_id_origem"],
                "vendedor_padronizado": pedidos[-1]["vendedor_padronizado"],
                "dados_origem": pedidos[-1]["dados_origem"],
            }
        )

    return {
        "codigo_lote": codigo_lote,
        "nao_gravou_no_banco": True,
        "pedidos": pedidos,
        "itens_pedido": itens_pedido,
        "pendencias": pendencias,
        "rastreabilidade": rastreabilidade,
        "total_vendas": len(vendas_por_id),
        "total_pedidos_planejados": len(pedidos),
        "total_vendas_pendentes": len(pendencias),
        "total_itens_planejados": len(itens_pedido),
        "contagem_motivos_pendencia": dict(
            Counter(motivo for pendencia in pendencias for motivo in pendencia["motivos"])
        ),
        "pagamentos": (
            "nao planejados: a planilha de vendas nao fornece metodo/transacao de pagamento"
        ),
        "estoque": "nao alterado; pertence ao Bloco C",
    }
