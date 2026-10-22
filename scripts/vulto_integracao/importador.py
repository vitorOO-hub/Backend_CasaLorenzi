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
    rastreabilidade = plano.get("rastreabilidade", [])
    if (
        not isinstance(pedidos, list)
        or not isinstance(itens, list)
        or not isinstance(pendencias, list)
        or not isinstance(rastreabilidade, list)
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
        chave = (str(pendencia.get("origem") or "vulto"), venda_id)
        motivos = pendencia.get("motivos")
        if not venda_id or chave in ids_pendentes:
            raise ImportacaoVultoError("Plano contem venda pendente sem ID ou com ID duplicado")
        if (
            not isinstance(motivos, list)
            or not motivos
            or not all(str(m).strip() for m in motivos)
        ):
            raise ImportacaoVultoError(f"Venda pendente sem motivos validos: {venda_id}")
        if not isinstance(pendencia.get("dados_origem"), dict):
            raise ImportacaoVultoError(f"Venda pendente sem dados de origem: {venda_id}")
        ids_pendentes.add(chave)

    pedidos_por_numero = {}
    for pedido in pedidos:
        numero = str(pedido.get("numero_pedido") or "").strip()
        if not numero or numero in pedidos_por_numero:
            raise ImportacaoVultoError("Plano contem numero_pedido vazio ou duplicado")
        pedidos_por_numero[numero] = pedido
        chave = (
            str(pedido.get("origem_importacao") or "vulto"),
            str(pedido.get("chave_origem") or ""),
        )
        if chave[1] and chave in ids_pendentes:
            raise ImportacaoVultoError("Uma origem aparece como pronta e pendente no mesmo plano")

    chaves_rastreabilidade = set()
    for registro in rastreabilidade:
        origem = str(registro.get("origem") or "vulto")
        chave = str(registro.get("chave_origem") or "").strip()
        numero = str(registro.get("numero_pedido") or "").strip()
        if not chave or numero not in pedidos_por_numero:
            raise ImportacaoVultoError("Rastreabilidade sem chave ou pedido correspondente")
        if (origem, chave) in chaves_rastreabilidade:
            raise ImportacaoVultoError("Plano contem chave de origem duplicada")
        chaves_rastreabilidade.add((origem, chave))

    itens_por_pedido: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in itens:
        numero = str(item.get("numero_pedido") or "").strip()
        if numero not in pedidos_por_numero:
            raise ImportacaoVultoError("Item sem pedido correspondente no plano")
        preco = item.get("preco_unitario")
        if int(item.get("quantidade", 0)) <= 0 or (
            preco is not None and Decimal(str(preco)) < 0
        ):
            raise ImportacaoVultoError("Item com quantidade ou preco invalido")
        itens_por_pedido[numero].append(item)

    for numero, pedido in pedidos_por_numero.items():
        linhas = itens_por_pedido.get(numero, [])
        if not linhas:
            raise ImportacaoVultoError(f"Pedido sem itens: {numero}")
        sem_preco = [item for item in linhas if item.get("preco_unitario") is None]
        if sem_preco and (
            len(sem_preco) != len(linhas)
            or pedido.get("origem_importacao") != "vulto_batel_manual"
        ):
            raise ImportacaoVultoError(
                f"Preco unitario ausente permitido somente para itens do Batel manual: {numero}"
            )
        total_itens = sum(
            Decimal(str(item["quantidade"])) * Decimal(str(item["preco_unitario"]))
            for item in linhas if item.get("preco_unitario") is not None
        )
        total_esperado = Decimal(str(pedido["valor_total"])) - Decimal(
            str(pedido.get("valor_frete", 0))
        )
        if not sem_preco and total_itens != total_esperado:
            raise ImportacaoVultoError(
                f"Itens + frete nao fecham o pedido {numero}; pedido mantido sem gravar"
            )


def gravar_plano(conexao: Any, plano: dict[str, Any]) -> dict[str, int]:
    """Grava pedidos e pendencias em uma transacao; recusa pedidos ja existentes."""
    validar_plano(plano)
    pedidos = plano["pedidos"]
    pendencias = plano.get("pendencias", [])
    rastreabilidade = plano.get("rastreabilidade", [])

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

            chaves_por_origem: dict[str, set[str]] = defaultdict(set)
            for pendencia in pendencias:
                chaves_por_origem[str(pendencia.get("origem") or "vulto")].add(
                    str(pendencia["venda_id"])
                )
            for registro in rastreabilidade:
                chaves_por_origem[str(registro.get("origem") or "vulto")].add(
                    str(registro["chave_origem"])
                )
            for pedido in pedidos:
                if pedido.get("chave_origem"):
                    chaves_por_origem[str(pedido.get("origem_importacao") or "vulto")].add(
                        str(pedido["chave_origem"])
                    )

            for origem, chaves in chaves_por_origem.items():
                cursor.execute(
                    """
                    SELECT origem, chave_origem
                    FROM public.venda_importacao_origem
                    WHERE origem = %s AND chave_origem = ANY(%s)
                    FOR UPDATE
                    """,
                    (origem, sorted(chaves)),
                )
                existentes_origem = cursor.fetchall()
                if existentes_origem:
                    amostra = ", ".join(f"{o}:{c}" for o, c in existentes_origem[:5])
                    raise ImportacaoVultoError(
                        f"Carga cancelada: {len(existentes_origem)} origens ja importadas "
                        f"(ex.: {amostra})"
                    )
                cursor.execute(
                    """
                    SELECT venda_id_origem, estado
                    FROM public.venda_importacao_pendente
                    WHERE origem = %s AND venda_id_origem = ANY(%s)
                    FOR UPDATE
                    """,
                    (origem, sorted(chaves)),
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
                        f"(origem {origem}, ex.: {amostra})"
                    )

            if pendencias:
                cursor.executemany(
                    """
                    INSERT INTO public.venda_importacao_pendente AS atual (
                        id_lote, origem, venda_id_origem, status_origem, motivos,
                        quantidade_itens, dados_origem
                    ) VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
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
                            str(pendencia.get("origem") or "vulto"),
                            str(pendencia["venda_id"]),
                            pendencia.get("status_origem"),
                            pendencia["motivos"],
                            len(
                                pendencia["dados_origem"].get("itens", [])
                                or pendencia["dados_origem"].get("itens_mapeados", [])
                            ),
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
                        [str(p["id_cliente"]) if p.get("id_cliente") else None for p in pedidos],
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
                        [item.get("preco_unitario") for item in itens],
                    ],
                )
            if rastreabilidade:
                cursor.executemany(
                    """
                    INSERT INTO public.venda_importacao_origem (
                        id_lote, id_pedido, origem, chave_origem, venda_id_origem,
                        compra_id_origem, funcionario_id_origem, vendedor_padronizado,
                        dados_origem
                    )
                    SELECT %s, p.id_pedido, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb)
                    FROM public.pedido p WHERE p.numero_pedido = %s
                    """,
                    (
                        (
                            id_lote,
                            registro.get("origem") or "vulto",
                            str(registro["chave_origem"]),
                            registro.get("venda_id_origem"),
                            registro.get("compra_id_origem"),
                            registro.get("funcionario_id_origem"),
                            registro.get("vendedor_padronizado"),
                            json.dumps(
                                registro.get("dados_origem") or {},
                                ensure_ascii=False,
                                default=str,
                            ),
                            registro["numero_pedido"],
                        )
                        for registro in rastreabilidade
                    ),
                )

            pedidos_com_origem = [
                pedido for pedido in pedidos if pedido.get("chave_origem")
            ]
            if pedidos_com_origem:
                cursor.execute(
                    """
                    UPDATE public.venda_importacao_pendente vp
                    SET estado = 'importada', id_pedido = p.id_pedido,
                        resolvida_em = now(), atualizada_em = now()
                    FROM unnest(%s::text[], %s::text[], %s::text[])
                        AS origem_pronta(origem, chave_origem, numero_pedido)
                    JOIN public.pedido p ON p.numero_pedido = origem_pronta.numero_pedido
                    WHERE vp.origem = origem_pronta.origem
                      AND vp.venda_id_origem = origem_pronta.chave_origem
                      AND vp.estado = 'pendente'
                    """,
                    (
                        [str(p.get("origem_importacao") or "vulto") for p in pedidos_com_origem],
                        [str(p["chave_origem"]) for p in pedidos_com_origem],
                        [str(p["numero_pedido"]) for p in pedidos_com_origem],
                    ),
                )
    return {
        "pedidos": len(pedidos),
        "itens": len(plano["itens_pedido"]),
        "pendencias": len(pendencias),
        "rastreabilidade": len(rastreabilidade),
    }
