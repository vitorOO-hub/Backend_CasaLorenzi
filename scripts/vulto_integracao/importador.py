"""Persistencia transacional do plano, protegida para banco dedicado de teste."""

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any
from urllib.parse import unquote, urlsplit


class ImportacaoVultoError(RuntimeError):
    pass


def validar_dsn_local_teste(dsn: str) -> None:
    """Recusa destinos remotos e bancos que nao sejam explicitamente de teste."""
    try:
        url = urlsplit(dsn)
        host = (url.hostname or "").lower()
        banco = unquote(url.path.lstrip("/"))
    except ValueError as erro:
        raise ImportacaoVultoError("TEST_DATABASE_URL invalida") from erro
    if url.scheme not in {"postgres", "postgresql"}:
        raise ImportacaoVultoError("TEST_DATABASE_URL precisa usar PostgreSQL")
    if host not in {"localhost", "127.0.0.1", "::1"} or not banco.endswith("_teste"):
        raise ImportacaoVultoError(
            "gravacao bloqueada: use PostgreSQL local e banco terminado em _teste"
        )


def validar_dsn_producao_supabase(dsn: str) -> None:
    """Permite producao somente em hostname Supabase remoto, nunca em localhost/teste."""
    try:
        url = urlsplit(dsn)
        host = (url.hostname or "").lower()
        banco = unquote(url.path.lstrip("/"))
    except ValueError as erro:
        raise ImportacaoVultoError("DATABASE_URL invalida") from erro
    host_supabase = host.endswith(".supabase.co") or host.endswith(".pooler.supabase.com")
    if (
        url.scheme not in {"postgres", "postgresql"}
        or not host_supabase
        or not banco
        or banco.endswith("_teste")
    ):
        raise ImportacaoVultoError(
            "gravacao de producao bloqueada: DATABASE_URL nao aponta para Supabase remoto"
        )


def validar_plano(plano: dict[str, Any]) -> None:
    pedidos = plano.get("pedidos")
    itens = plano.get("itens_pedido")
    pendencias = plano.get("pendencias", [])
    if (
        not isinstance(pedidos, list)
        or not isinstance(itens, list)
        or not isinstance(pendencias, list)
    ):
        raise ImportacaoVultoError(
            "Plano precisa conter listas de pedidos, itens_pedido e pendencias"
        )
    if not pedidos and not pendencias:
        raise ImportacaoVultoError("Plano nao contem pedidos nem vendas pendentes")
    if not str(plano.get("codigo_lote") or "").strip():
        raise ImportacaoVultoError("Plano precisa de codigo_lote para rastreabilidade")

    ids_pendentes = set()
    for pendencia in pendencias:
        venda_id = str(pendencia.get("venda_id") or "").strip()
        motivos = pendencia.get("motivos")
        if not venda_id or venda_id in ids_pendentes:
            raise ImportacaoVultoError("Plano contem venda pendente sem ID ou com ID duplicado")
        if (
            not isinstance(motivos, list)
            or not motivos
            or not all(str(m).strip() for m in motivos)
        ):
            raise ImportacaoVultoError(f"Venda pendente sem motivos validos: {venda_id}")
        if not isinstance(pendencia.get("dados_origem"), dict):
            raise ImportacaoVultoError(f"Venda pendente sem dados de origem: {venda_id}")
        ids_pendentes.add(venda_id)

    ids_prontos = {
        str(pedido.get("numero_pedido") or "").removeprefix("VULTO-") for pedido in pedidos
    }
    if ids_pendentes & ids_prontos:
        raise ImportacaoVultoError("Uma venda aparece como pronta e pendente no mesmo plano")

    pedidos_por_numero = {}
    for pedido in pedidos:
        numero = str(pedido.get("numero_pedido") or "").strip()
        if not numero or numero in pedidos_por_numero:
            raise ImportacaoVultoError("Plano contem numero_pedido vazio ou duplicado")
        pedidos_por_numero[numero] = pedido

    itens_por_pedido: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in itens:
        numero = str(item.get("numero_pedido") or "").strip()
        if numero not in pedidos_por_numero:
            raise ImportacaoVultoError("Item sem pedido correspondente no plano")
        if (
            int(item.get("quantidade", 0)) <= 0
            or Decimal(str(item.get("preco_unitario", -1))) < 0
        ):
            raise ImportacaoVultoError("Item com quantidade ou preco invalido")
        itens_por_pedido[numero].append(item)

    for numero, pedido in pedidos_por_numero.items():
        linhas = itens_por_pedido.get(numero, [])
        if not linhas:
            raise ImportacaoVultoError(f"Pedido sem itens: {numero}")
        total_itens = sum(
            Decimal(str(item["quantidade"])) * Decimal(str(item["preco_unitario"]))
            for item in linhas
        )
        total_esperado = Decimal(str(pedido["valor_total"])) - Decimal(
            str(pedido.get("valor_frete", 0))
        )
        if total_itens != total_esperado:
            raise ImportacaoVultoError(
                f"Itens + frete nao fecham o pedido {numero}; pedido mantido sem gravar"
            )


def gravar_plano(conexao: Any, plano: dict[str, Any]) -> dict[str, int]:
    """Grava pedidos e pendencias em uma transacao; recusa pedidos ja existentes."""
    validar_plano(plano)
    pedidos = plano["pedidos"]
    pendencias = plano.get("pendencias", [])

    with conexao.transaction():
        with conexao.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('casa-lorenzi-vulto-import'))")
            numeros = [pedido["numero_pedido"] for pedido in pedidos]
            existentes = []
            if numeros:
                cursor.execute(
                    "SELECT numero_pedido FROM public.pedido WHERE numero_pedido = ANY(%s)",
                    (numeros,),
                )
                existentes = [linha[0] for linha in cursor.fetchall()]
            if existentes:
                amostra = ", ".join(sorted(existentes)[:5])
                raise ImportacaoVultoError(
                    f"Carga cancelada: {len(existentes)} pedidos ja existem (ex.: {amostra})"
                )

            cursor.execute(
                """
                INSERT INTO public.importacao_lote (codigo, origem)
                VALUES (%s, 'Vulto vendas')
                ON CONFLICT (codigo) DO NOTHING
                """,
                (plano["codigo_lote"],),
            )
            cursor.execute(
                "SELECT id_lote FROM public.importacao_lote WHERE codigo = %s",
                (plano["codigo_lote"],),
            )
            id_lote = cursor.fetchone()[0]

            ids_origem = [str(pendencia["venda_id"]) for pendencia in pendencias]
            ids_origem.extend(numero.removeprefix("VULTO-") for numero in numeros)
            ids_origem = sorted(set(ids_origem))
            if ids_origem:
                cursor.execute(
                    """
                    SELECT venda_id_origem, estado
                    FROM public.venda_importacao_pendente
                    WHERE origem = 'vulto' AND venda_id_origem = ANY(%s)
                    FOR UPDATE
                    """,
                    (ids_origem,),
                )
                estados_existentes = dict(cursor.fetchall())
                resolvidas = sorted(
                    venda_id
                    for venda_id, estado in estados_existentes.items()
                    if estado != "pendente"
                )
                if resolvidas:
                    amostra = ", ".join(resolvidas[:5])
                    raise ImportacaoVultoError(
                        "Carga cancelada: ha vendas pendentes previamente resolvidas "
                        f"(ex.: {amostra})"
                    )

            if pendencias:
                cursor.executemany(
                    """
                    INSERT INTO public.venda_importacao_pendente AS atual (
                        id_lote, origem, venda_id_origem, status_origem, motivos,
                        quantidade_itens, dados_origem
                    ) VALUES (%s, 'vulto', %s, %s, %s, %s, CAST(%s AS jsonb))
                    ON CONFLICT (origem, venda_id_origem) DO UPDATE SET
                        id_lote = EXCLUDED.id_lote,
                        status_origem = EXCLUDED.status_origem,
                        motivos = EXCLUDED.motivos,
                        quantidade_itens = EXCLUDED.quantidade_itens,
                        dados_origem = EXCLUDED.dados_origem,
                        atualizada_em = now()
                    WHERE atual.estado = 'pendente'
                    """,
                    (
                        (
                            id_lote,
                            str(pendencia["venda_id"]),
                            pendencia.get("status_origem"),
                            pendencia["motivos"],
                            len(pendencia["dados_origem"].get("itens", [])),
                            json.dumps(
                                pendencia["dados_origem"], ensure_ascii=False, default=str
                            ),
                        )
                        for pendencia in pendencias
                    ),
                )

            if pedidos:
                cursor.execute(
                    """
                    INSERT INTO public.pedido AS p (
                        numero_pedido, id_loja, id_cliente, id_status_pedido,
                        valor_total, valor_frete, canal_venda, criado_em, observacao
                    )
                    SELECT * FROM unnest(
                        %s::text[], %s::uuid[], %s::uuid[], %s::uuid[],
                        %s::numeric[], %s::numeric[], %s::text[], %s::timestamptz[], %s::text[]
                    ) AS entrada(
                        numero_pedido, id_loja, id_cliente, id_status_pedido,
                        valor_total, valor_frete, canal_venda, criado_em, observacao
                    )
                    """,
                    (
                        [p["numero_pedido"] for p in pedidos],
                        [str(p["id_loja"]) for p in pedidos],
                        [str(p["id_cliente"]) for p in pedidos],
                        [str(p["id_status_pedido"]) for p in pedidos],
                        [p["valor_total"] for p in pedidos],
                        [p["valor_frete"] for p in pedidos],
                        [p["canal_venda"] for p in pedidos],
                        [p["criado_em"] for p in pedidos],
                        [p["observacao"] for p in pedidos],
                    ),
                )
            itens = plano["itens_pedido"]
            if itens:
                cursor.execute(
                    """
                    INSERT INTO public.item_pedido (
                        id_pedido, id_variacao, quantidade, preco_unitario
                    )
                    SELECT p.id_pedido, entrada.id_variacao, entrada.quantidade,
                           entrada.preco_unitario
                    FROM unnest(
                        %s::text[], %s::uuid[], %s::integer[], %s::numeric[]
                    ) AS entrada(numero_pedido, id_variacao, quantidade, preco_unitario)
                    JOIN public.pedido p ON p.numero_pedido = entrada.numero_pedido
                    """,
                    [
                        [item["numero_pedido"] for item in itens],
                        [str(item["id_variacao"]) for item in itens],
                        [item["quantidade"] for item in itens],
                        [item["preco_unitario"] for item in itens],
                    ],
                )
            if numeros:
                cursor.execute(
                    """
                    UPDATE public.venda_importacao_pendente vp
                    SET estado = 'importada', id_pedido = (
                            SELECT p.id_pedido FROM public.pedido p
                            WHERE p.numero_pedido = 'VULTO-' || vp.venda_id_origem
                        ),
                        resolvida_em = now(), atualizada_em = now()
                    WHERE vp.origem = 'vulto' AND vp.estado = 'pendente'
                      AND ('VULTO-' || vp.venda_id_origem) = ANY(%s::text[])
                    """,
                    (numeros,),
                )
    return {
        "pedidos": len(pedidos),
        "itens": len(plano["itens_pedido"]),
        "pendencias": len(pendencias),
    }
