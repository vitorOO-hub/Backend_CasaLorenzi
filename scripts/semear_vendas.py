"""Popula vendas, estoque e pendencias de exemplo para o inicio do gerente (so desenvolvimento).

Sem isto os graficos do gerente ficam vazios. O script cria, coerente com as regras do banco:

- 2 lojas (Barra e Savassi) alem da que ja existe, cada uma com gerente e operador sem login;
- o catalogo da colecao (produtos, variacoes, SKUs no padrao que o front reconhece);
- clientes ficticios (e-mail @exemplo.com.br, sem conta de login);
- ~13 meses de pedidos (loja fisica e online), itens, pagamentos e movimentacoes de estoque, em
  que o saldo de cada peca bate com a soma das movimentacoes;
- ajustes de estoque a aprovar e transferencias pedidas entre as lojas.

    python scripts/semear_vendas.py             # mostra o que seria criado, sem alterar nada
    python scripts/semear_vendas.py --aplicar   # grava tudo numa unica transacao

Roda uma vez: se ja existir pedido com numero `SD-...`, nao faz nada. Os dados sao ficticios; nunca
rode em producao com clientes reais. Exige `alembic upgrade head` (revisao 20261007130000).
"""

import argparse
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[1]
BRT = timezone(timedelta(hours=-3))
DIAS_DE_HISTORICO = 400
SEMENTE = 20261007
PREFIXO_PEDIDO = "SD-"
LOJA_BASE = "LOJA-CENTRO"


@dataclass(frozen=True)
class Peca:
    nome: str
    categoria: str
    prefixo: str
    preco: float
    cores: tuple[tuple[str, str], ...]  # (nome, codigo no SKU)
    tamanhos: tuple[str, ...]
    popularidade: float


CATALOGO = (
    Peca(
        "Camisa Oxford Bianca",
        "Camisas",
        "CL-CAM-OXF",
        329,
        (("Branco", "BR"), ("Azul", "AZ")),
        ("P", "M", "G"),
        8,
    ),
    Peca(
        "Calça Alfaiataria Torino",
        "Calças",
        "CL-CAL-ALF",
        649,
        (("Preto", "PT"), ("Cinza", "CZ")),
        ("38", "40", "42"),
        7,
    ),
    Peca(
        "Blazer Estruturado Modena",
        "Alfaiataria",
        "CL-BLA",
        1290,
        (("Marinho", "MA"),),
        ("P", "M", "G"),
        3,
    ),
    Peca(
        "Vestido Midi Amalfi",
        "Vestidos",
        "CL-VES-MID",
        899,
        (("Verde", "VD"), ("Preto", "PT")),
        ("P", "M", "G"),
        6,
    ),
    Peca(
        "Vestido Slip Verona", "Vestidos", "CL-VES-SLI", 749, (("Champanhe", "CH"),), ("P", "M"), 4
    ),
    Peca(
        "Tricô Gola Alta Bolonha",
        "Malharia",
        "CL-TRI",
        459,
        (("Off-white", "OW"), ("Caramelo", "CA")),
        ("P", "M", "G"),
        6,
    ),
    Peca(
        "Suéter Lã Merino Aosta",
        "Malharia",
        "CL-SUE",
        689,
        (("Cinza Mescla", "CM"),),
        ("P", "M", "G"),
        4,
    ),
    Peca("Trench Coat Milano", "Outerwear", "CL-TRE", 1690, (("Bege", "BG"),), ("P", "M", "G"), 2),
    Peca(
        "Jaqueta Couro Firenze",
        "Outerwear",
        "CL-JAQ",
        2190,
        (("Preto", "PT"),),
        ("P", "M", "G"),
        1.5,
    ),
    Peca(
        "Saia Plissada Como",
        "Saias",
        "CL-SAI",
        529,
        (("Preto", "PT"), ("Vinho", "VI")),
        ("P", "M", "G"),
        4,
    ),
    Peca(
        "Bolsa Estruturada Lucca",
        "Acessórios",
        "CL-BOL",
        1150,
        (("Caramelo", "CA"),),
        ("Único",),
        2.5,
    ),
    Peca(
        "Cinto Couro Siena",
        "Acessórios",
        "CL-CIN",
        279,
        (("Preto", "PT"), ("Caramelo", "CA")),
        ("90", "95", "100"),
        6,
    ),
    Peca("Mocassim Pádua", "Calçados", "CL-MOC", 899, (("Preto", "PT"),), ("38", "40", "42"), 3),
    Peca(
        "Bota Chelsea Asolo",
        "Calçados",
        "CL-BOT",
        1090,
        (("Preto", "PT"),),
        ("37", "39", "41"),
        2.5,
    ),
)

# A camisa de linho ja existe no banco (Branco P e M). Entram as outras grades e uma cor nova.
LINHO = Peca(
    "Camisa Linho Essencial",
    "Camisas",
    "CL-CAM-LIN",
    149.90,
    (("Branco", "BR"), ("Azul", "AZ")),
    ("P", "M", "G"),
    10,
)

LOJAS = (
    # codigo, nome, cnpj ficticio, cidade, uf, pedidos por dia, parte online
    ("LOJA-CENTRO", "Casa Lorenzi Centro", None, "Sao Paulo", "SP", 2.4, 0.35),
    ("LOJA-BARRA", "Casa Lorenzi Barra", "98765432000101", "Rio de Janeiro", "RJ", 1.5, 0.45),
    ("LOJA-SAVASSI", "Casa Lorenzi Savassi", "98765432000202", "Belo Horizonte", "MG", 1.0, 0.40),
)
EQUIPE_NOVA = (
    ("LOJA-BARRA", "gerente_loja", "Rafael Queiroz", "rafael.queiroz@exemplo.com.br"),
    ("LOJA-BARRA", "operador_estoque", "Tiago Lemos", "tiago.lemos@exemplo.com.br"),
    ("LOJA-SAVASSI", "gerente_loja", "Juliana Prado", "juliana.prado@exemplo.com.br"),
    ("LOJA-SAVASSI", "operador_estoque", "Camila Rocha", "camila.rocha@exemplo.com.br"),
)
NOMES = (
    "Helena",
    "Beatriz",
    "Marina",
    "Larissa",
    "Camila",
    "Fernanda",
    "Patrícia",
    "Renata",
    "Aline",
    "Bruno",
    "Rodrigo",
    "Felipe",
    "Gustavo",
    "Ricardo",
    "André",
    "Eduardo",
    "Thiago",
    "Marcelo",
)
SOBRENOMES = (
    "Almeida",
    "Barros",
    "Cardoso",
    "Dias",
    "Esteves",
    "Farias",
    "Guimarães",
    "Honório",
    "Ibrahim",
    "Junqueira",
    "Klein",
    "Lacerda",
    "Monteiro",
    "Nogueira",
    "Ottoni",
    "Pacheco",
    "Queiroz",
    "Rangel",
)
CIDADES = ("São Paulo", "Rio de Janeiro", "Belo Horizonte", "Campinas", "Niterói", "Santos")
QUANTIDADE_DE_CLIENTES = 36

DIA_DA_SEMANA = (0.75, 0.8, 0.9, 1.0, 1.35, 1.7, 0.6)  # segunda ... domingo
MES = {1: 0.9, 2: 0.9, 6: 1.1, 11: 1.35, 12: 1.5}
HORAS_LOJA = (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)
PESO_HORAS_LOJA = (2, 3, 4, 3, 4, 5, 5, 6, 6, 5, 3, 1)
HORAS_ONLINE = (8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)
PESO_HORAS_ONLINE = (1, 2, 3, 3, 4, 3, 3, 3, 3, 3, 4, 4, 5, 6, 6, 3)
METODOS = {
    "loja": (("cartao_credito", 40), ("cartao_debito", 25), ("pix", 25), ("dinheiro", 10)),
    "online": (("cartao_credito", 55), ("pix", 35), ("boleto", 10)),
}


@dataclass
class Variacao:
    id: UUID
    id_produto: UUID
    sku: str
    preco: float
    popularidade: float


@dataclass
class Plano:
    pedidos: list[tuple] = field(default_factory=list)
    itens: list[tuple] = field(default_factory=list)
    pagamentos: list[tuple] = field(default_factory=list)
    movimentos: list[tuple] = field(default_factory=list)
    # (id_loja, id_variacao) -> (quantidade final, estoque minimo)
    estoque: dict[tuple[UUID, UUID], tuple[int, int]] = field(default_factory=dict)
    transferencias: list[tuple] = field(default_factory=list)
    ajustes: list[tuple] = field(default_factory=list)


@dataclass(frozen=True)
class Equipe:
    gerente: UUID | None
    operador: UUID | None
    atendimento: tuple[UUID, ...]


def grade(peca: Peca):
    """(cor, tamanho, sku) de cada variacao da peca."""
    for cor, codigo_cor in peca.cores:
        for tamanho in peca.tamanhos:
            yield (
                cor,
                tamanho,
                f"{peca.prefixo}-{codigo_cor}-{'U' if tamanho == 'Único' else tamanho}",
            )


def poisson(lam: float, rng: random.Random) -> int:
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def minimo_para(preco: float) -> int:
    return 5 if preco < 500 else 3 if preco < 1000 else 2


def estoque_inicial(preco: float, rng: random.Random) -> int:
    return (
        rng.randint(10, 24)
        if preco < 500
        else rng.randint(8, 18)
        if preco < 1000
        else rng.randint(4, 10)
    )


def reposicao(preco: float, rng: random.Random) -> int:
    return (
        rng.randint(8, 16)
        if preco < 500
        else rng.randint(6, 12)
        if preco < 1000
        else rng.randint(3, 6)
    )


def sortear_status(canal: str, idade_dias: float, rng: random.Random) -> str:
    if canal == "loja":
        return "cancelado" if rng.random() < 0.02 else "entregue"
    if idade_dias >= 14:
        opcoes = (("entregue", 94), ("cancelado", 6))
    elif idade_dias >= 5:
        opcoes = (("entregue", 80), ("separado", 10), ("cancelado", 6), ("pago", 4))
    elif idade_dias >= 1:
        opcoes = (
            ("entregue", 35),
            ("separado", 35),
            ("pago", 22),
            ("cancelado", 5),
            ("aguardando_pagamento", 3),
        )
    else:
        opcoes = (
            ("pago", 50),
            ("separado", 15),
            ("aguardando_pagamento", 20),
            ("criado", 10),
            ("cancelado", 5),
        )
    return rng.choices([o for o, _ in opcoes], [p for _, p in opcoes])[0]


def simular(
    *,
    lojas: dict[str, UUID],
    variacoes: list[Variacao],
    clientes: list[UUID],
    equipes: dict[str, Equipe],
    agora: datetime,
    rng: random.Random,
) -> Plano:
    """Gera, sem tocar no banco, as linhas coerentes entre si (estoque, pedidos, pagamentos)."""
    plano = Plano()
    inicio = (agora - timedelta(days=DIAS_DE_HISTORICO)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    por_id = {v.id: v for v in variacoes}
    pares = [(loja, v.id) for loja in lojas.values() for v in variacoes]
    saldo: dict[tuple[UUID, UUID], int] = {}
    sem_reposicao = set(rng.sample(pares, 10))
    corte_reposicao = agora - timedelta(days=30)

    def movimento(loja, variacao, tipo, quantidade, quando, motivo, *, pedido=None, usuario=None):
        anterior = saldo[(loja, variacao)]
        sinal = -1 if tipo in ("saida", "ajuste_negativo", "venda", "transferencia_saida") else 1
        posterior = anterior + sinal * quantidade
        if posterior < 0:
            raise RuntimeError(f"saldo negativo na simulacao: {tipo} {quantidade} de {anterior}")
        saldo[(loja, variacao)] = posterior
        plano.movimentos.append(
            (loja, variacao, pedido, usuario, tipo, quantidade, anterior, posterior, motivo, quando)
        )

    def repor(loja, variacao, quando, quantidade=None):
        preco = por_id[variacao].preco
        operador = equipes[codigo_de[loja]].operador
        movimento(
            loja,
            variacao,
            "entrada",
            quantidade or reposicao(preco, rng),
            quando,
            "Reposição de fornecedor",
            usuario=operador,
        )

    codigo_de = {id_loja: codigo for codigo, id_loja in lojas.items()}
    for loja, variacao in pares:
        saldo[(loja, variacao)] = 0
        abertura = inicio - timedelta(hours=16)
        movimento(
            loja,
            variacao,
            "entrada",
            estoque_inicial(por_id[variacao].preco, rng),
            abertura,
            "Estoque inicial",
            usuario=equipes[codigo_de[loja]].operador,
        )

    # Pedidos desejados, dia a dia, por loja.
    desejos = []
    perfil = {codigo: (taxa, online) for codigo, _n, _c, _ci, _uf, taxa, online in LOJAS}
    pesos = [v.popularidade for v in variacoes]
    for i in range(DIAS_DE_HISTORICO + 1):
        dia = inicio + timedelta(days=i)
        fator = (
            DIA_DA_SEMANA[dia.weekday()]
            * MES.get(dia.month, 1.0)
            * (0.75 + 0.35 * i / DIAS_DE_HISTORICO)
        )
        for codigo, id_loja in lojas.items():
            taxa, parte_online = perfil[codigo]
            for _ in range(poisson(taxa * fator, rng)):
                canal = "online" if rng.random() < parte_online else "loja"
                horas, peso = (
                    (HORAS_ONLINE, PESO_HORAS_ONLINE)
                    if canal == "online"
                    else (HORAS_LOJA, PESO_HORAS_LOJA)
                )
                quando = dia.replace(
                    hour=rng.choices(horas, peso)[0],
                    minute=rng.randint(0, 59),
                    second=rng.randint(0, 59),
                )
                if quando > agora - timedelta(minutes=5):
                    continue
                escolhidas, vistos = [], set()
                for _ in range(rng.choices([1, 2, 3, 4], [55, 28, 12, 5])[0]):
                    v = rng.choices(variacoes, pesos)[0]
                    if v.id not in vistos:
                        vistos.add(v.id)
                        escolhidas.append((v.id, 2 if rng.random() < 0.12 else 1))
                desejos.append((quando, "pedido", id_loja, canal, escolhidas))

    # Transferencias ja aceitas (movem estoque de verdade) entram na mesma linha do tempo.
    aceitas = []
    centro, barra, savassi = lojas[LOJA_BASE], lojas["LOJA-BARRA"], lojas["LOJA-SAVASSI"]
    pecas_para_mover = [
        v for v in variacoes if v.sku.startswith(("CL-VES-MID-VD-M", "CL-TRI-OW-M"))
    ]
    for variacao, origem, destino, dias_atras in zip(
        pecas_para_mover, (centro, barra), (savassi, centro), (20, 12), strict=False
    ):
        aceitas.append(
            (agora - timedelta(days=dias_atras), "transferencia", origem, destino, variacao.id, 3)
        )
    linha_do_tempo = sorted(desejos + aceitas, key=lambda e: e[0])

    numero = 0
    for quando, tipo, *resto in linha_do_tempo:
        if tipo == "transferencia":
            origem, destino, variacao, quantidade = resto
            if saldo[(origem, variacao)] < quantidade:
                repor(origem, variacao, quando, quantidade)
            gerente = equipes[codigo_de[origem]].gerente
            movimento(
                origem,
                variacao,
                "transferencia_saida",
                quantidade,
                quando,
                "Transferência para outra loja",
                usuario=gerente,
            )
            movimento(
                destino,
                variacao,
                "transferencia_entrada",
                quantidade,
                quando + timedelta(seconds=1),
                "Transferência recebida",
                usuario=equipes[codigo_de[destino]].operador,
            )
            plano.transferencias.append(
                (
                    "transferencia",
                    "aceita",
                    origem,
                    destino,
                    variacao,
                    equipes[codigo_de[destino]].operador,
                    gerente,
                    quantidade,
                    "Reposição combinada entre lojas",
                    quando - timedelta(days=1),
                    quando,
                )
            )
            continue

        id_loja, canal, escolhidas = resto
        itens = []
        for variacao, quantidade in escolhidas:
            disponivel = saldo[(id_loja, variacao)]
            if disponivel < quantidade:
                if (id_loja, variacao) in sem_reposicao and quando > corte_reposicao:
                    quantidade = disponivel
                else:
                    repor(
                        id_loja,
                        variacao,
                        quando,
                        max(quantidade, 0) + reposicao(por_id[variacao].preco, rng),
                    )
            if quantidade > 0:
                itens.append((variacao, quantidade))
        if not itens:
            continue

        numero += 1
        id_pedido = uuid4()
        subtotal = round(sum(por_id[v].preco * q for v, q in itens), 2)
        frete, retirada = 0.0, canal == "online" and rng.random() < 0.2
        if canal == "online" and not retirada and subtotal < 800:
            frete = rng.choice((29.9, 39.9, 49.0, 59.0))
        total = round(subtotal + frete, 2)
        status = sortear_status(canal, (agora - quando).total_seconds() / 86400, rng)
        equipe = equipes[codigo_de[id_loja]]
        vendedor = (
            rng.choice(equipe.atendimento) if canal == "loja" and equipe.atendimento else None
        )
        nota = (
            "Venda no balcão."
            if canal == "loja"
            else (
                f"Checkout pelo portal. Entrega: {'loja' if retirada else 'casa'}. "
                f"Frete: R$ {frete:.2f}."
            )
        )
        plano.pedidos.append(
            (
                id_pedido,
                f"{PREFIXO_PEDIDO}{quando:%Y%m%d}-{numero:05d}",
                id_loja,
                rng.choice(clientes),
                vendedor,
                status,
                total,
                nota,
                quando,
                quando,
                canal,
                frete,
            )
        )
        for variacao, quantidade in itens:
            plano.itens.append((id_pedido, variacao, quantidade, por_id[variacao].preco, quando))

        baixa = status in ("pago", "separado", "entregue", "cancelado")
        if baixa:
            for variacao, quantidade in itens:
                movimento(
                    id_loja,
                    variacao,
                    "venda",
                    quantidade,
                    quando,
                    f"Pedido {plano.pedidos[-1][1]}",
                    pedido=id_pedido,
                )
        if status == "cancelado":
            # Mesmo instante da venda (+2 s): o saldo de cada peca segue a ordem do relogio.
            volta = quando + timedelta(seconds=2)
            for variacao, quantidade in itens:
                movimento(
                    id_loja,
                    variacao,
                    "cancelamento_venda",
                    quantidade,
                    volta,
                    "Pedido cancelado",
                    pedido=id_pedido,
                )

        if status != "criado":
            metodo = rng.choices([m for m, _ in METODOS[canal]], [p for _, p in METODOS[canal]])[0]
            situacao = {"aguardando_pagamento": "pendente", "cancelado": "estornado"}.get(
                status, "aprovado"
            )
            processado = (
                None if situacao == "pendente" else quando + timedelta(minutes=rng.randint(1, 15))
            )
            externo = None if metodo == "dinheiro" else f"SIM-{uuid4().hex[:16]}"
            plano.pagamentos.append(
                (id_pedido, 1, metodo, situacao, total, externo, processado, quando)
            )

    # Inventario recente: algumas pecas ficam abaixo do minimo ou esgotadas, para a tela de
    # reposicao ter o que mostrar.
    candidatas = [p for p in pares if saldo[p] > 2]
    for loja, variacao in rng.sample(candidatas, min(7, len(candidatas))):
        alvo = rng.choice((0, 0, 1, 2))
        movimento(
            loja,
            variacao,
            "ajuste_negativo",
            saldo[(loja, variacao)] - alvo,
            agora - timedelta(minutes=1),
            "Inventário: peças não localizadas",
            usuario=equipes[codigo_de[loja]].gerente,
        )

    for (loja, variacao), quantidade in saldo.items():
        plano.estoque[(loja, variacao)] = (quantidade, minimo_para(por_id[variacao].preco))

    # Pendencias para o gerente decidir.
    pecas = {v.sku: v.id for v in variacoes}

    def pedir(sku: str) -> UUID:
        return pecas[sku]

    for codigo, sku, quantidade, motivo in (
        (LOJA_BASE, "CL-CAM-OXF-BR-M", -1, "Mancha de tinta na vitrine"),
        (LOJA_BASE, "CL-SAI-PT-P", -2, "Peças danificadas no transporte"),
        (LOJA_BASE, "CL-CIN-PT-95", 1, "Peça encontrada no estoque do fundo"),
        ("LOJA-BARRA", "CL-BLA-MA-M", -1, "Costura aberta"),
        ("LOJA-BARRA", "CL-VES-SLI-CH-P", 2, "Contagem de inventário"),
        ("LOJA-SAVASSI", "CL-TRE-BG-G", -1, "Peça de mostruário"),
    ):
        equipe = equipes[codigo]
        plano.ajustes.append(
            (
                lojas[codigo],
                pedir(sku),
                equipe.operador,
                None,
                quantidade,
                motivo,
                "pendente",
                agora - timedelta(hours=rng.randint(2, 70)),
                None,
                None,
            )
        )
    equipe = equipes[LOJA_BASE]
    plano.ajustes.append(
        (
            centro,
            pedir("CL-CIN-CA-100"),
            equipe.operador,
            equipe.gerente,
            -1,
            "Cinto com defeito de fábrica",
            "rejeitado",
            agora - timedelta(days=6),
            agora - timedelta(days=5),
            "A divergência é de embalagem, não de saldo",
        )
    )

    for origem, destino, sku, quantidade, obs in (
        (centro, barra, "CL-BLA-MA-M", 2, "Cliente quer o blazer em outra tamanho"),
        (centro, savassi, "CL-TRE-BG-M", 3, "Trench em falta para o outono"),
        (barra, centro, "CL-JAQ-PT-M", 1, "Reposição de vitrine"),
    ):
        plano.transferencias.append(
            (
                "transferencia",
                "solicitada",
                origem,
                destino,
                pedir(sku),
                equipes[codigo_de[destino]].operador,
                None,
                quantidade,
                obs,
                agora - timedelta(hours=rng.randint(3, 40)),
                None,
            )
        )
    plano.transferencias.append(
        (
            "reposicao_rede",
            "solicitada",
            None,
            savassi,
            pedir("CL-BOT-PT-39"),
            equipes["LOJA-SAVASSI"].operador,
            None,
            4,
            "Reposição urgente a rede",
            agora - timedelta(hours=5),
            None,
        )
    )
    return plano


# ---------------------------------------------------------------- banco


def _um(conexao, comando, parametros=()):
    linha = conexao.execute(comando, parametros).fetchone()
    return linha[0] if linha else None


def preparar(conexao: psycopg.Connection):
    """Garante lojas, equipe, catalogo e clientes. Devolve o que a simulacao precisa."""
    lojas = {}
    for codigo, nome, cnpj, cidade, uf, _taxa, _online in LOJAS:
        existente = _um(conexao, "SELECT id_loja FROM loja WHERE codigo = %s", (codigo,))
        if existente is None and codigo == LOJA_BASE:
            raise RuntimeError(f"a loja {LOJA_BASE!r} nao existe (rode scripts/criar_contas.py)")
        lojas[codigo] = existente or _um(
            conexao,
            "INSERT INTO loja (codigo, nome, cnpj, cidade, uf) VALUES (%s, %s, %s, %s, %s) "
            "RETURNING id_loja",
            (codigo, nome, cnpj, cidade, uf),
        )

    for codigo, tipo, nome, email in EQUIPE_NOVA:
        conexao.execute(
            "INSERT INTO usuario (id_tipo_usuario, id_loja, nome, email) VALUES "
            "((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = %s), %s, %s, %s) "
            "ON CONFLICT (email) DO NOTHING",
            (tipo, lojas[codigo], nome, email),
        )

    def uma_pessoa(tipo, id_loja):
        return _um(
            conexao,
            "SELECT u.id_usuario FROM usuario u JOIN tipo_usuario t USING (id_tipo_usuario) "
            "WHERE t.codigo = %s AND u.id_loja = %s AND u.ativo ORDER BY u.criado_em LIMIT 1",
            (tipo, id_loja),
        )

    equipes = {}
    for codigo, id_loja in lojas.items():
        atendimento = [
            linha[0]
            for linha in conexao.execute(
                "SELECT u.id_usuario FROM usuario u JOIN tipo_usuario t USING (id_tipo_usuario) "
                "WHERE t.codigo IN ('atendente', 'gerente_loja') AND u.id_loja = %s AND u.ativo "
                "ORDER BY u.criado_em",
                (id_loja,),
            )
        ]
        equipes[codigo] = Equipe(
            uma_pessoa("gerente_loja", id_loja),
            uma_pessoa("operador_estoque", id_loja),
            tuple(atendimento),
        )
        if equipes[codigo].gerente is None or equipes[codigo].operador is None:
            raise RuntimeError(f"a loja {codigo} precisa de gerente e operador de estoque")

    existentes = {
        linha[0]
        for linha in conexao.execute(
            "SELECT id_variacao FROM estoque WHERE id_loja = %s", (lojas[LOJA_BASE],)
        )
    }
    variacoes = []
    for peca in (LINHO, *CATALOGO):
        id_produto = _um(
            conexao,
            "SELECT id_produto FROM produto WHERE nome = %s AND marca = 'Casa Lorenzi'",
            (peca.nome,),
        )
        if id_produto is None:
            id_produto = _um(
                conexao,
                "INSERT INTO produto (nome, marca, categoria, descricao, preco_base) "
                "VALUES (%s, 'Casa Lorenzi', %s, %s, %s) RETURNING id_produto",
                (peca.nome, peca.categoria, f"{peca.nome}, coleção atual.", peca.preco),
            )
        for cor, tamanho, sku in grade(peca):
            id_variacao = _um(
                conexao, "SELECT id_variacao FROM variacao_produto WHERE sku = %s", (sku,)
            )
            if id_variacao is None:
                id_variacao = _um(
                    conexao,
                    "INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id_variacao",
                    (id_produto, sku, cor, tamanho, peca.preco),
                )
            # As duas variacoes antigas do linho ficam como estao, com a historia que ja tem.
            if id_variacao not in existentes:
                variacoes.append(
                    Variacao(id_variacao, id_produto, sku, peca.preco, peca.popularidade)
                )

    clientes = []
    for n in range(QUANTIDADE_DE_CLIENTES):
        nome = f"{NOMES[n % len(NOMES)]} {SOBRENOMES[(n * 5 + n // len(NOMES)) % len(SOBRENOMES)]}"
        email = f"{nome.lower().replace(' ', '.')}{n:02d}@exemplo.com.br".encode(
            "ascii", "ignore"
        ).decode()
        conexao.execute(
            "INSERT INTO usuario (id_tipo_usuario, nome, email, telefone, cidade) VALUES "
            "((SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = 'cliente'), %s, %s, %s, %s) "
            "ON CONFLICT (email) DO NOTHING",
            (nome, email, f"(11) 9{8000 + n:04d}-{1000 + n * 7:04d}", CIDADES[n % len(CIDADES)]),
        )
        clientes.append(_um(conexao, "SELECT id_usuario FROM usuario WHERE email = %s", (email,)))
    return lojas, equipes, variacoes, clientes


def gravar(conexao: psycopg.Connection, plano: Plano) -> None:
    with conexao.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO pedido (
                id_pedido, numero_pedido, id_loja, id_cliente, id_usuario_responsavel,
                id_status_pedido, valor_total, observacao, criado_em, atualizado_em,
                canal_venda, valor_frete)
            VALUES (
                %s, %s, %s, %s, %s,
                (SELECT id_status_pedido FROM status_pedido WHERE codigo = %s),
                %s, %s, %s, %s, %s, %s)
            """,
            plano.pedidos,
        )
        cur.executemany(
            "INSERT INTO item_pedido "
            "(id_pedido, id_variacao, quantidade, preco_unitario, criado_em) "
            "VALUES (%s, %s, %s, %s, %s)",
            plano.itens,
        )
        cur.executemany(
            """
            INSERT INTO pagamento (id_pedido, tentativa, id_metodo_pagamento, id_status_pagamento,
                                   valor, transacao_externa_id, processado_em, criado_em)
            VALUES (%s, %s, (SELECT id_metodo_pagamento FROM metodo_pagamento WHERE codigo = %s),
                    (SELECT id_status_pagamento FROM status_pagamento WHERE codigo = %s),
                    %s, %s, %s, %s)
            """,
            plano.pagamentos,
        )
        cur.executemany(
            """
            INSERT INTO movimentacao_estoque (
                id_loja, id_variacao, id_pedido, id_usuario_responsavel,
                id_tipo_movimentacao_estoque, quantidade, quantidade_anterior,
                quantidade_posterior, motivo, criada_em)
            VALUES (%s, %s, %s, %s,
                    (SELECT id_tipo_movimentacao_estoque FROM tipo_movimentacao_estoque
                     WHERE codigo = %s),
                    %s, %s, %s, %s, %s)
            """,
            plano.movimentos,
        )
        cur.executemany(
            "INSERT INTO estoque (id_loja, id_variacao, quantidade, estoque_minimo) "
            "VALUES (%s, %s, %s, %s)",
            [
                (loja, variacao, q, minimo)
                for (loja, variacao), (q, minimo) in plano.estoque.items()
            ],
        )
        cur.executemany(
            """
            INSERT INTO transferencia_estoque (
                id_tipo_transferencia_estoque, id_status_transferencia_estoque, id_loja_origem,
                id_loja_destino, id_variacao, id_usuario_solicitante, id_usuario_responsavel,
                quantidade, observacao, solicitada_em, aceita_em)
            VALUES (
                (SELECT id_tipo_transferencia_estoque FROM tipo_transferencia_estoque
                 WHERE codigo = %s),
                (SELECT id_status_transferencia_estoque FROM status_transferencia_estoque
                 WHERE codigo = %s),
                %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            plano.transferencias,
        )
        cur.executemany(
            """
            INSERT INTO ajuste_estoque (
                id_loja, id_variacao, id_usuario_solicitante, id_usuario_decisor,
                quantidade, motivo, status, solicitado_em, decidido_em, motivo_recusa)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            plano.ajustes,
        )


def semear(conexao: psycopg.Connection, *, agora: datetime | None = None) -> Plano | None:
    """Prepara, simula e grava numa transacao. Devolve o plano (None se ja estava semeado)."""
    if not conexao.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'pedido' "
        "AND column_name = 'canal_venda'"
    ).fetchone():
        raise RuntimeError("falta a revisao 20261007130000 (rode: alembic upgrade head)")
    if conexao.execute(
        "SELECT 1 FROM pedido WHERE numero_pedido LIKE %s LIMIT 1", (f"{PREFIXO_PEDIDO}%",)
    ).fetchone():
        return None
    lojas, equipes, variacoes, clientes = preparar(conexao)
    plano = simular(
        lojas=lojas,
        variacoes=variacoes,
        clientes=clientes,
        equipes=equipes,
        agora=agora or datetime.now(BRT),
        rng=random.Random(SEMENTE),  # nosec B311 - dados de exemplo, nao e criptografia
    )
    gravar(conexao, plano)
    return plano


def resumo(plano: Plano) -> str:
    por_status: dict[str, int] = defaultdict(int)
    for pedido in plano.pedidos:
        por_status[pedido[5]] += 1
    por_status_texto = ", ".join(f"{k}: {v}" for k, v in sorted(por_status.items()))
    linhas = [
        f"  pedidos .............. {len(plano.pedidos)}  ({por_status_texto})",
        f"  itens de pedido ...... {len(plano.itens)}",
        f"  pagamentos ........... {len(plano.pagamentos)}",
        f"  movimentacoes ........ {len(plano.movimentos)}",
        f"  linhas de estoque .... {len(plano.estoque)}",
        f"  transferencias ....... {len(plano.transferencias)}",
        f"  ajustes .............. {len(plano.ajustes)}",
    ]
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--aplicar", action="store_true", help="grava no banco (sem isto so mostra)"
    )
    args = parser.parse_args(argv)

    banco = (dotenv_values(RAIZ / ".env").get("DATABASE_URL") or "").strip()
    if not banco:
        print("DATABASE_URL nao encontrada no .env", file=sys.stderr)
        return 1
    print(f"Banco: {urlsplit(banco).hostname}\n")
    with psycopg.connect(banco, connect_timeout=15) as conexao:
        try:
            plano = semear(conexao)
        except RuntimeError as erro:
            print(f"Nada feito: {erro}", file=sys.stderr)
            return 1
        if plano is None:
            print("Ja existem pedidos SD-...: nada a fazer.")
            return 0
        print(resumo(plano))
        if not args.aplicar:
            conexao.rollback()
            print("\nNada foi gravado. Rode com --aplicar para criar os dados.")
            return 0
        conexao.commit()
        print("\nPronto: dados gravados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
