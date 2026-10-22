"""Planeja vendas manuais do Batel usando apenas decisões registradas na planilha."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from .clientes_vendas import indexar_clientes_por_cpf, normalizar_cpf
from .lojas import CODIGO_LOJA_POR_ID_VULTO
from .skus import resolver_id_variacao

STATUS_POR_ORIGEM = {
    "concluida": "pago",
    "cancelada": "cancelado",
    "estornada": "cancelado",
}


def _texto(valor: object) -> str:
    return "" if valor is None else str(valor).strip()


def _decimal(valor: object) -> Decimal | None:
    if valor is None or not _texto(valor):
        return None
    try:
        return Decimal(_texto(valor).replace(",", ".")).quantize(Decimal("0.01"))
    except Exception:
        return None


def _chave_linha(valor: object) -> str:
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return _texto(valor)


def planejar_vendas_batel(
    vendas: Iterable[Mapping[str, object]],
    itens_mapeados: Iterable[Mapping[str, object]],
    lojas: Iterable[Mapping[str, object]],
    status_pedido: Iterable[Mapping[str, object]],
    variacoes: Iterable[Mapping[str, object]],
    usuarios: Iterable[Mapping[str, object]],
    tipos_usuario: Iterable[Mapping[str, object]],
    codigo_lote: str,
) -> dict[str, Any]:
    vendas_lista = [dict(venda) for venda in vendas]
    itens_por_linha: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in itens_mapeados:
        itens_por_linha[_chave_linha(item.get("linha_venda"))].append(dict(item))

    lojas_por_codigo = {
        _texto(loja.get("codigo")): _texto(loja.get("id_loja")) for loja in lojas
    }
    status_por_codigo = {
        _texto(s.get("codigo")): _texto(s.get("id_status_pedido")) for s in status_pedido
    }
    variacao_por_sku = {
        _texto(v.get("sku")): _texto(v.get("id_variacao"))
        for v in variacoes
        if _texto(v.get("sku")) and _texto(v.get("id_variacao"))
    }
    tipos_por_id = {
        _texto(tipo.get("id_tipo_usuario")): _texto(tipo.get("codigo"))
        for tipo in tipos_usuario
    }
    clientes_por_cpf = indexar_clientes_por_cpf(usuarios, tipos_por_id)
    loja_codigo = CODIGO_LOJA_POR_ID_VULTO[4]
    loja_id = lojas_por_codigo.get(loja_codigo)
    pedidos: list[dict[str, object]] = []
    itens_pedido: list[dict[str, object]] = []
    pendencias: list[dict[str, object]] = []
    rastreabilidade: list[dict[str, object]] = []

    for numero_linha, venda in enumerate(vendas_lista, start=2):
        chave = _texto(venda.get("chave_origem_importacao"))
        motivos: list[str] = []
        revisao_duplicidade = _texto(venda.get("revisao_duplicidade")).lower()
        if revisao_duplicidade != "sem duplicidade confirmada no vulto.db":
            motivos.append("duplicidade:sem_confirmacao_para_importar")
        if not chave:
            motivos.append("origem:chave_de_idempotencia_ausente")
        if loja_id is None:
            motivos.append(f"loja:codigo_destino_ausente:{loja_codigo}")

        status_origem = _texto(venda.get("status")).lower()
        status_codigo = STATUS_POR_ORIGEM.get(status_origem)
        status_id = status_por_codigo.get(status_codigo or "")
        if status_id is None:
            motivos.append("status:codigo_ausente_no_destino")

        data_hora = _texto(venda.get("data_hora"))
        if not data_hora:
            motivos.append("data_hora:ausente")
        else:
            try:
                parsed = datetime.fromisoformat(data_hora.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    motivos.append("data_hora:sem_fuso")
            except ValueError:
                motivos.append("data_hora:invalida")
        total = _decimal(venda.get("valor"))
        if total is None:
            motivos.append("valor:total_ausente_ou_invalido")
        cpf = normalizar_cpf(venda.get("cpf"))
        id_cliente = clientes_por_cpf.get(cpf) if cpf else None

        linhas = itens_por_linha.get(str(numero_linha), [])
        itens_agregados: dict[str, dict[str, object]] = {}
        for linha in linhas:
            sku = _texto(linha.get("sku_confirmado"))
            variacao_id = resolver_id_variacao(sku, variacao_por_sku)
            try:
                quantidade = int(Decimal(_texto(linha.get("quantidade_item"))))
            except Exception:
                quantidade = 0
            if not variacao_id:
                motivos.append(f"sku:variacao_nao_encontrada:{sku or 'vazio'}")
            if quantidade <= 0:
                motivos.append("item:quantidade_invalida")
            if variacao_id and quantidade > 0:
                atual = itens_agregados.setdefault(
                    sku,
                    {"id_variacao": variacao_id, "quantidade": 0, "preco_unitario": None},
                )
                atual["quantidade"] = int(atual["quantidade"]) + quantidade
        if not itens_agregados:
            motivos.append("itens:nenhum_item_mapeado")

        numero_pedido = f"VULTO-BATEL-MANUAL-{chave}"
        origem_dados = {
            "venda": venda,
            "itens_mapeados": linhas,
            "decisoes": {
                "preco_unitario": "NULL conforme DEC-008; o total da venda e a fonte financeira",
                "cliente": "NULL quando CPF ausente; nao criar cliente ficticio (DEC-001)",
                "estoque": "nao alterar nesta carga; recomposicao pertence ao Bloco C (DEC-009)",
            },
        }
        if motivos:
            pendencias.append(
                {
                    "venda_id": chave or f"linha_{numero_linha}",
                    "origem": "vulto_batel_manual",
                    "status_origem": status_origem or None,
                    "motivos": sorted(set(motivos)),
                    "dados_origem": origem_dados,
                }
            )
            continue

        pedidos.append(
            {
                "numero_pedido": numero_pedido,
                "id_loja": loja_id,
                "id_cliente": id_cliente,
                "id_status_pedido": status_id,
                "valor_total": total,
                "valor_frete": Decimal("0.00"),
                "canal_venda": "loja",
                "criado_em": data_hora,
                "observacao": (
                    f"Venda manual Vulto Batel; origem {chave}; status original: "
                    f"{status_origem}; vendedor legado: "
                    f"{_texto(venda.get('vendedora_padrao')) or 'nao informado'}."
                ),
                "origem_importacao": "vulto_batel_manual",
                "chave_origem": chave,
                "venda_id_origem": chave,
                "compra_id_origem": None,
                "funcionario_id_origem": _texto(venda.get("funcionario_legado_id")) or None,
                "vendedor_padronizado": _texto(venda.get("vendedora_padrao")) or None,
                "dados_origem": origem_dados,
            }
        )
        for item in itens_agregados.values():
            itens_pedido.append({"numero_pedido": numero_pedido, **item})
        rastreabilidade.append(
            {
                "numero_pedido": numero_pedido,
                "origem": "vulto_batel_manual",
                "chave_origem": chave,
                "venda_id_origem": chave,
                "compra_id_origem": None,
                "funcionario_id_origem": _texto(venda.get("funcionario_legado_id")) or None,
                "vendedor_padronizado": _texto(venda.get("vendedora_padrao")) or None,
                "dados_origem": origem_dados,
            }
        )

    return {
        "codigo_lote": codigo_lote,
        "nao_gravou_no_banco": True,
        "pedidos": pedidos,
        "itens_pedido": itens_pedido,
        "pendencias": pendencias,
        "rastreabilidade": rastreabilidade,
        "total_vendas": len(vendas_lista),
        "total_pedidos_planejados": len(pedidos),
        "total_vendas_pendentes": len(pendencias),
        "total_itens_planejados": len(itens_pedido),
        "contagem_motivos_pendencia": dict(
            Counter(motivo for pendencia in pendencias for motivo in pendencia["motivos"])
        ),
        "frete": "0.00; vendas manuais nao registram frete e frete nao compoe faturamento",
        "pagamentos": "nao importados: sem transacao comprovada nas tabelas de destino",
        "estoque": "nao alterado; recomposicao de canceladas/estornadas pertence ao Bloco C",
    }
