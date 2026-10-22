"""Compara o snapshot de estoque Vulto com a contagem fisica, sem gravar no banco."""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from .lojas import CODIGO_LOJA_POR_ID_VULTO
from .skus import normalizar_sku_reduzido

LOJA_POR_ABA = {
    "pinheiros": 1,
    "eldorado": 2,
    "savassi": 3,
    "batel": 4,
    "cd": 7,
}
TAMANHO_NUMERICO = {"38": "P", "40": "M", "42": "G", "44": "G", "46": "GG"}


def _texto(valor: object) -> str:
    return "" if valor is None else str(valor).strip()


def _inteiro(valor: object) -> int | None:
    if valor is None or _texto(valor) == "":
        return None
    try:
        numero = Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return int(numero) if numero == numero.to_integral_value() else None


def _valor(linha: Mapping[str, object], *chaves: str) -> object:
    normalizadas = {
        re.sub(r"\s+", "_", str(chave).strip().lower()): valor
        for chave, valor in linha.items()
    }
    for chave in chaves:
        valor = normalizadas.get(chave)
        if valor is not None:
            return valor
    return None


def _modelo(sku: str) -> str | None:
    encontrado = re.fullmatch(r"VLT-([A-Z]{3}-\d{3})-[A-Z]{3}-(?:PP|P|M|G|GG|U|\d{2})", sku)
    if encontrado:
        return encontrado.group(1)
    encontrado = re.fullmatch(r"([A-Z]{3})-(\d{3})", sku)
    return f"{encontrado.group(1)}-{encontrado.group(2)}" if encontrado else None


def _sku(valor: object) -> str | None:
    texto = _texto(valor)
    if not texto:
        return None
    reduzido = normalizar_sku_reduzido(texto)
    if reduzido:
        return reduzido
    canonico_numerico = re.fullmatch(
        r"VLT-([A-Z]{3})-(\d{3})-([A-Z]{3})-(\d{2})", texto.upper()
    )
    if canonico_numerico:
        categoria, modelo, cor, tamanho = canonico_numerico.groups()
        tamanho_padrao = "PP" if int(tamanho) <= 36 else TAMANHO_NUMERICO.get(tamanho)
        if tamanho_padrao:
            return f"VLT-{categoria}-{modelo}-{cor}-{tamanho_padrao}"
    return texto.upper()


def _cabecalho(
    chave: str, quantidade: object, metrica: str = "quantidade"
) -> dict[str, Any] | None:
    sku = _sku(chave)
    qtd = _inteiro(quantidade)
    if not sku or qtd is None:
        return None
    return {"sku": sku, "quantidade": qtd, "metrica": metrica}


def planejar_conferencia(
    estoque: Iterable[Mapping[str, object]],
    contagens_por_aba: Mapping[str, Iterable[Mapping[str, object]]],
) -> dict[str, Any]:
    """Gera comparacoes detalhadas por SKU ou modelo; ausencias nao sao tratadas como zero."""
    estoque_por_loja: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    estoque_sem_sku = []
    for linha in estoque:
        try:
            loja_id = int(linha.get("loja_id"))
        except (TypeError, ValueError):
            estoque_sem_sku.append({**linha, "motivo": "loja_id invalido"})
            continue
        sku = _sku(linha.get("sku_padronizado") or linha.get("sku"))
        quantidade = _inteiro(linha.get("qtd"))
        if not sku or quantidade is None:
            estoque_sem_sku.append({**linha, "motivo": "sku ou quantidade invalido"})
            continue
        estoque_por_loja[loja_id][sku] += quantidade

    comparacoes = []
    contagem_sem_sku = []
    for nome_aba, linhas in contagens_por_aba.items():
        chave_aba = _texto(nome_aba).lower()
        loja_id = next(
            (id_loja for nome, id_loja in LOJA_POR_ABA.items() if nome in chave_aba),
            None,
        )
        if loja_id is None:
            continue
        linhas = list(linhas)
        por_metrica: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for linha in linhas:
            if loja_id == 7:
                sku_origem = _valor(linha, "sku")
                for campo in ("SALDO", "DISPONIVEL"):
                    registro = _cabecalho(sku_origem, _valor(linha, campo.lower()), campo.lower())
                    if registro:
                        por_metrica[campo.lower()].append(registro)
                    elif campo == "SALDO":
                        contagem_sem_sku.append({"aba": nome_aba, **linha})
            else:
                sku_origem = _valor(linha, "sku", "codigo", "modelo")
                qtd_origem = _valor(linha, "qtd", "qtde", "quantidade", "qtd_total")
                registro = _cabecalho(sku_origem, qtd_origem)
                if registro:
                    por_metrica["quantidade"].append(registro)
                else:
                    contagem_sem_sku.append({"aba": nome_aba, **linha})

        granularidade = "modelo" if loja_id == 3 else "sku"
        for metrica, registros in por_metrica.items():
            contagem: dict[str, int] = defaultdict(int)
            for registro in registros:
                chave = _modelo(registro["sku"]) if granularidade == "modelo" else registro["sku"]
                if chave is None:
                    contagem_sem_sku.append(
                        {"aba": nome_aba, **registro, "motivo": "modelo nao identificavel"}
                    )
                    continue
                contagem[chave] += registro["quantidade"]

            saldos = estoque_por_loja.get(loja_id, {})
            if granularidade == "modelo":
                saldo_agregado: dict[str, int] = defaultdict(int)
                for sku, quantidade in saldos.items():
                    modelo = _modelo(sku)
                    if modelo:
                        saldo_agregado[modelo] += quantidade
                    else:
                        estoque_sem_sku.append(
                            {
                                "loja_id": loja_id,
                                "sku": sku,
                                "qtd": quantidade,
                                "motivo": "modelo nao identificavel para comparar com Savassi",
                            }
                        )
                saldos_comparaveis = saldo_agregado
            else:
                saldos_comparaveis = saldos

            for chave in sorted(set(saldos_comparaveis) | set(contagem)):
                saldo = saldos_comparaveis.get(chave)
                contado = contagem.get(chave)
                if saldo is None:
                    situacao = "sem_registro_no_estoque_vulto"
                elif contado is None:
                    situacao = "sem_registro_na_contagem"
                else:
                    situacao = "confere" if saldo == contado else "divergente"
                comparacoes.append(
                    {
                        "aba_contagem": nome_aba,
                        "loja_id_vulto": loja_id,
                        "codigo_loja": CODIGO_LOJA_POR_ID_VULTO[loja_id],
                        "granularidade": granularidade,
                        "metrica_contagem": metrica,
                        "sku_ou_modelo": chave,
                        "saldo_estoque_vulto": saldo,
                        "quantidade_contada": contado,
                        "diferenca_contagem_menos_estoque": (
                            contado - saldo if contado is not None and saldo is not None else None
                        ),
                        "situacao": situacao,
                    }
                )

    resumo = defaultdict(int)
    for linha in comparacoes:
        resumo[f'{linha["codigo_loja"]}:{linha["metrica_contagem"]}:{linha["situacao"]}'] += 1
    return {
        "nao_gravou_no_banco": True,
        "comparacoes": comparacoes,
        "resumo": dict(sorted(resumo.items())),
        "estoque_sem_sku_ou_loja": estoque_sem_sku,
        "contagem_sem_sku": contagem_sem_sku,
    }
