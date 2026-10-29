"""E-mails ao cliente pelo n8n: resumo da compra, pontos a vencer e categoria Lorenzi+.

Quem decide quem recebe e o backend; o n8n so recebe um webhook por e-mail, monta a mensagem e
envia pelo Gmail da loja. Cada chamada leva a chave das automacoes no cabecalho X-Chave-Automacao
(o webhook do n8n recusa sem ela).

- Resumo da compra: sai depois que a venda e gravada (tarefa em segundo plano da rota), nunca
  atrasa nem derruba a venda. Sem e-mail no cadastro, nao sai.
- Pontos a vencer (lotes que vencem nos proximos `emails_dias_aviso_pontos` dias) e categoria
  Lorenzi+ (quem esta perto da proxima): saem no disparo diario (`disparar`), chamado pelo
  agendamento. Respeitam `aceita_mensagens`.

Nunca em dobro: o resumo e a categoria ficam em `aviso_cliente` (reservado antes de enviar,
`enviado` ou `falhou` depois); os pontos, em `aviso_pontos`, gravados so quando o n8n confirma.
Quem falhou entra de novo no proximo disparo (ate `MAX_TENTATIVAS`). O log nunca leva o e-mail.
"""

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.engine import Connection

from app.automacoes import repositorio, service
from app.cliente.beneficios import beneficios
from app.cliente.repositorio import CATEGORIAS_VULTO_MAIS, situacao_da_categoria
from app.cliente.vencimento_pontos import SP
from app.core.config import Settings
from app.core.db import abrir_conexao

registro = logging.getLogger("app.automacoes.emails")

# Perto da proxima categoria: faltam ate 20% dos pontos que ela exige.
PERTO_DA_PROXIMA = 0.2
MINIMO_DA_CATEGORIA = dict(CATEGORIAS_VULTO_MAIS)
NOME_DA_CATEGORIA = {"bronze": "Bronze", "prata": "Prata", "ouro": "Ouro", "black": "Black"}


def _dinheiro(valor: Any) -> float:
    return float(Decimal(str(valor or 0)).quantize(Decimal("0.01")))


def _primeiro_nome(nome: str) -> str:
    primeiro = (nome or "").strip().split(" ")[0]
    return primeiro[:1].upper() + primeiro[1:].lower() if primeiro else "cliente"


def _iso(valor: Any) -> str:
    return valor.isoformat() if hasattr(valor, "isoformat") else str(valor)


# ------------------------------------------------------------------ envio


def configurado(configuracoes: Settings) -> bool:
    chave = configuracoes.chave_automacao
    return bool(configuracoes.n8n_webhook_emails and chave and chave.get_secret_value())


def enviar(configuracoes: Settings, mensagem: dict[str, Any]) -> str | None:
    """Manda um e-mail pelo webhook do n8n. Devolve None se o n8n confirmou, ou o erro curto."""
    if not configurado(configuracoes):
        return "n8n nao configurado"
    chave = configuracoes.chave_automacao.get_secret_value()  # type: ignore[union-attr]
    try:
        resposta = httpx.post(
            configuracoes.n8n_webhook_emails,  # type: ignore[arg-type]
            json=mensagem,
            headers={"X-Chave-Automacao": chave},
            timeout=configuracoes.n8n_timeout_segundos,
        )
    except httpx.HTTPError as erro:
        registro.warning(
            "n8n sem resposta (%s) no e-mail %s", type(erro).__name__, mensagem["tipo"]
        )
        return f"sem resposta do n8n ({type(erro).__name__})"
    if resposta.is_error:
        registro.warning("n8n respondeu %s no e-mail %s", resposta.status_code, mensagem["tipo"])
        return f"n8n respondeu {resposta.status_code}"
    return None


def _base(configuracoes: Settings, tipo: str, nome: str, email: str) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "para": {"nome": nome, "primeiro_nome": _primeiro_nome(nome), "email": email},
        "site": configuracoes.frontend_url,
    }


# ------------------------------------------------------------------ resumo da compra


def _imagem(configuracoes: Settings, caminho: str | None) -> str | None:
    """Foto da peca com endereco completo (o catalogo guarda o caminho no site, /img/...)."""
    if not caminho:
        return None
    if caminho.startswith(("http://", "https://")):
        return caminho
    return f"{configuracoes.frontend_url}/{caminho.lstrip('/')}"


def mensagem_da_compra(configuracoes: Settings, compra: dict[str, Any]) -> dict[str, Any]:
    itens = [
        {
            "produto": " ".join(str(x) for x in (i["produto"], i["cor"], i["tamanho"]) if x),
            "nome": i["produto"],
            "cor": i["cor"],
            "tamanho": i["tamanho"],
            "imagem": _imagem(configuracoes, i.get("imagem_url")),
            "quantidade": int(i["quantidade"]),
            "preco_unitario": _dinheiro(i["preco_unitario"]),
            "total": _dinheiro(Decimal(str(i["preco_unitario"])) * int(i["quantidade"])),
        }
        for i in compra["itens"]
    ]
    return {
        **_base(configuracoes, "pos_compra", compra["nome"], compra["email"]),
        "pedido": {
            "numero": compra["numero_pedido"],
            "data": _iso(compra["criado_em"]),
            "loja": compra["loja"],
            "loja_endereco": ", ".join(
                str(x) for x in (compra.get("loja_endereco"), compra.get("loja_cidade")) if x
            )
            or None,
            "canal": compra["canal_venda"],
            "pagamento": compra["pagamento"],
            "itens": itens,
            "frete": _dinheiro(compra["valor_frete"]),
            "total": _dinheiro(compra["valor_total"]),
        },
        "pontos": {"ganhos": int(compra["pontos_ganhos"]), "saldo": int(compra["saldo"])},
    }


def enviar_resumo_da_compra(conexao: Connection, configuracoes: Settings, id_pedido: UUID) -> str:
    """Envia (uma vez) o resumo de um pedido. Devolve o que aconteceu, para o log e o disparo."""
    compra = repositorio.dados_da_compra(conexao, id_pedido)
    if compra is None:
        return "pedido_inexistente"
    if not compra["email"]:
        return "sem_email"
    id_aviso = repositorio.reservar_aviso(
        conexao, compra["id_usuario"], "pos_compra", str(id_pedido)
    )
    conexao.commit()
    if id_aviso is None:
        return "ja_enviado"
    erro = enviar(configuracoes, mensagem_da_compra(configuracoes, compra))
    repositorio.concluir_aviso(conexao, id_aviso, erro)
    conexao.commit()
    return "falhou" if erro else "enviado"


def resumo_da_compra_em_segundo_plano(configuracoes: Settings, id_pedido: UUID) -> None:
    """Tarefa de segundo plano das rotas de venda: nada aqui pode estourar na venda."""
    if not configurado(configuracoes):
        return
    try:
        with abrir_conexao(configuracoes) as conexao:
            situacao = enviar_resumo_da_compra(conexao, configuracoes, id_pedido)
        registro.info("resumo da compra %s: %s", id_pedido, situacao)
    except Exception:
        registro.exception("resumo da compra %s nao enviado", id_pedido)


# ------------------------------------------------------------------ pontos e categoria


def _proxima(categoria_atual: dict[str, Any]) -> dict[str, Any] | None:
    proxima = categoria_atual["proxima_categoria"]
    if not proxima:
        return None
    # Quanto do caminho entre a categoria atual e a proxima ja foi feito (barra do e-mail).
    inicio = MINIMO_DA_CATEGORIA[categoria_atual["categoria"]]
    fim = MINIMO_DA_CATEGORIA[proxima]
    feito = fim - categoria_atual["faltam_para_proxima"] - inicio
    return {
        "codigo": proxima,
        "nome": NOME_DA_CATEGORIA.get(proxima, proxima),
        "faltam": categoria_atual["faltam_para_proxima"],
        "progresso": round(100 * feito / (fim - inicio)) if fim > inicio else 100,
        "beneficios": beneficios(proxima),
    }


def _categoria(situacao: dict[str, Any]) -> dict[str, Any]:
    atual = situacao["categoria"]
    return {
        "atual": {
            "codigo": atual,
            "nome": NOME_DA_CATEGORIA.get(atual, atual),
            "beneficios": beneficios(atual),
        },
        "proxima": _proxima(situacao),
    }


def perto_da_proxima(situacao: dict[str, Any]) -> bool:
    proxima, faltam = situacao["proxima_categoria"], situacao["faltam_para_proxima"]
    if not proxima or faltam is None:
        return False
    return faltam <= MINIMO_DA_CATEGORIA[proxima] * PERTO_DA_PROXIMA


def _chave_da_categoria(proxima: str) -> str:
    return f"{proxima}:{datetime.now(UTC).astimezone(SP).year}"


def mensagem_de_pontos(configuracoes: Settings, cliente: dict[str, Any]) -> dict[str, Any]:
    situacao = {k: cliente[k] for k in ("categoria", "proxima_categoria", "faltam_para_proxima")}
    return {
        **_base(configuracoes, "pontos", cliente["nome"], cliente["email"]),
        "pontos": {
            "saldo": cliente["saldo"],
            "a_vencer": cliente["pontos_a_vencer"],
            "vencimentos": [
                {"data": _iso(v["vence_em"]), "pontos": v["pontos"]} for v in cliente["vencimentos"]
            ],
        },
        "categoria": _categoria(situacao),
    }


def mensagem_de_categoria(configuracoes: Settings, cliente: dict[str, Any]) -> dict[str, Any]:
    situacao = situacao_da_categoria(cliente["creditos_no_ano"])
    return {
        **_base(configuracoes, "categoria", cliente["nome"], cliente["email"]),
        "pontos": {"saldo": cliente["saldo"], "no_ano": cliente["creditos_no_ano"]},
        "categoria": _categoria(situacao),
    }


def _avisos_de_pontos(
    conexao: Connection, configuracoes: Settings, limite: int, simular: bool
) -> dict[str, Any]:
    clientes = service.clientes_a_avisar(
        conexao, dias=configuracoes.emails_dias_aviso_pontos, canal="email"
    )["clientes"][:limite]
    feito = {"candidatos": len(clientes), "enviados": 0, "falhas": 0, "clientes": []}
    for cliente in clientes:
        feito["clientes"].append(str(cliente["id_cliente"]))
        if simular:
            continue
        erro = enviar(configuracoes, mensagem_de_pontos(configuracoes, cliente))
        if erro:
            feito["falhas"] += 1
            continue
        feito["enviados"] += 1
        repositorio.gravar_avisos(
            conexao,
            "email",
            json.dumps(
                [
                    {
                        "id_cliente": str(cliente["id_cliente"]),
                        "vence_em": _iso(v["vence_em"]),
                        "pontos": v["pontos"],
                    }
                    for v in cliente["vencimentos"]
                ]
            ),
        )
        # O e-mail de pontos ja falou da proxima categoria: nao repete no aviso de categoria.
        if perto_da_proxima(cliente):
            chave = _chave_da_categoria(cliente["proxima_categoria"])
            id_aviso = repositorio.reservar_aviso(
                conexao, cliente["id_cliente"], "categoria", chave
            )
            if id_aviso:
                repositorio.concluir_aviso(conexao, id_aviso, None)
            conexao.commit()
    return feito


def _avisos_de_categoria(
    conexao: Connection, configuracoes: Settings, limite: int, simular: bool
) -> dict[str, Any]:
    candidatos = []
    for cliente in repositorio.clientes_com_email(conexao):
        situacao = situacao_da_categoria(cliente["creditos_no_ano"])
        if perto_da_proxima(situacao):
            candidatos.append((cliente, _chave_da_categoria(situacao["proxima_categoria"])))
    ja = repositorio.avisos_de_categoria(conexao, sorted({c for _, c in candidatos}))
    candidatos = [(c, k) for c, k in candidatos if (c["id_usuario"], k) not in ja][:limite]
    feito = {"candidatos": len(candidatos), "enviados": 0, "falhas": 0, "clientes": []}
    for cliente, chave in candidatos:
        feito["clientes"].append(str(cliente["id_usuario"]))
        if simular:
            continue
        id_aviso = repositorio.reservar_aviso(conexao, cliente["id_usuario"], "categoria", chave)
        conexao.commit()
        if id_aviso is None:
            continue
        erro = enviar(configuracoes, mensagem_de_categoria(configuracoes, cliente))
        repositorio.concluir_aviso(conexao, id_aviso, erro)
        conexao.commit()
        feito["falhas" if erro else "enviados"] += 1
    return feito


def disparar(conexao: Connection, configuracoes: Settings, *, simular: bool = False) -> dict:
    """O disparo diario: pontos a vencer, categoria e os resumos de compra que falharam.
    `simular` so diz quem receberia, sem enviar nem gravar nada."""
    teto = configuracoes.emails_por_disparo
    pontos = _avisos_de_pontos(conexao, configuracoes, teto, simular)
    restante = max(teto - pontos["enviados"] - pontos["falhas"], 0)
    categoria = _avisos_de_categoria(conexao, configuracoes, restante, simular)
    reenvios = {"candidatos": 0, "enviados": 0, "falhas": 0}
    restante = max(restante - categoria["enviados"] - categoria["falhas"], 0)
    for id_pedido in repositorio.compras_a_reenviar(conexao, restante):
        reenvios["candidatos"] += 1
        if simular:
            continue
        situacao = enviar_resumo_da_compra(conexao, configuracoes, id_pedido)
        if situacao == "enviado":
            reenvios["enviados"] += 1
        elif situacao == "falhou":
            reenvios["falhas"] += 1
    return {
        "simulado": simular,
        "n8n_configurado": configurado(configuracoes),
        "dias_aviso_pontos": configuracoes.emails_dias_aviso_pontos,
        "pontos": pontos,
        "categoria": categoria,
        "resumos_reenviados": reenvios,
    }
