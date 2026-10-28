"""Ferramentas do assistente do cliente.

O modelo escolhe a ferramenta e os argumentos de negocio. Quem e o cliente vem sempre do token
(`UsuarioAtual`): nenhuma ferramenta recebe id de cliente, CPF ou loja do cliente. Cada argumento e
validado aqui (Pydantic, campos extras recusados) e cada ferramenta chama o service que ja existe.
Se a consulta falhar, a ferramenta devolve `{"erro": ...}` e o prompt manda dizer que nao conseguiu
consultar; nada e inventado.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy.engine import Connection

from app.assistente.cliente import passagem, politicas, repositorio
from app.assistente.cliente.provedor import Ferramenta
from app.cliente import service as cliente
from app.cliente.vencimento_pontos import SP
from app.core.horario import aberta, descrever
from app.core.papeis import UsuarioAtual

log = logging.getLogger(__name__)

LIMITE_PRODUTOS = 5
LIMITE_PEDIDOS = 5
# Palavras que o cliente fala mas que nao estao no nome da peca ("camisa DE linho"), como no
# assistente do vendedor (app/assistente/vendedor/ferramentas.py).
SEM_PESO = frozenset(
    {"de", "da", "do", "das", "dos", "com", "sem", "para", "e", "a", "o", "em", "um", "uma"}
)
TEMAS_DE_POLITICA = tuple(politicas.todas())
CATEGORIAS_DE_CHAMADO = (
    "pedido",
    "entrega",
    "troca_devolucao",
    "pagamento",
    "produto",
    "agendamento",
    "outro",
)

Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuscarProduto(_Entrada):
    descricao: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)
    ]


class ConsultarEstoque(_Entrada):
    sku: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=2, max_length=40, pattern=r"^[A-Za-z0-9-]+$"
        ),
    ]
    loja: Texto | None = None


class ConsultarPolitica(_Entrada):
    # Sem enum no esquema enviado ao modelo: o Groq recusa a chamada inteira (HTTP 400) quando o
    # modelo erra o valor. A validacao fica aqui, e o erro volta ao modelo com os temas validos.
    tema: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)]


class InfoLoja(_Entrada):
    loja: Texto | None = None


class SemArgumentos(_Entrada):
    pass


class MontarCarrinho(_Entrada):
    sku: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=2, max_length=40, pattern=r"^[A-Za-z0-9-]+$"
        ),
    ]
    quantidade: int = Field(default=1, ge=1, le=10)


class TransferirParaAtendente(_Entrada):
    motivo: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    resumo: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1500)]
    # Categoria fora da lista vira "outro" (o chamado nao se perde por um rotulo errado).
    categoria: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = "outro"


DECLARACOES = [
    Ferramenta(
        "buscar_produto",
        "Procura pecas ativas e com estoque pela descricao (nome, categoria, cor, tecido, marca). "
        "Devolve ate 5 pecas com os SKUs de cada cor e tamanho.",
        {
            "type": "object",
            "properties": {
                "descricao": {"type": "string", "description": "Ex.: camisa azul de linho"}
            },
            "required": ["descricao"],
            "additionalProperties": False,
        },
    ),
    Ferramenta(
        "consultar_estoque",
        "Quantidade disponivel de um SKU (cor e tamanho) em cada loja. "
        "Use o SKU vindo de buscar_produto.",
        {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "SKU da variacao, ex.: VLT-CAM-013-OLI-G"},
                "loja": {
                    "type": "string",
                    "description": "Nome ou parte do nome da loja (opcional)",
                },
            },
            "required": ["sku"],
            "additionalProperties": False,
        },
    ),
    Ferramenta(
        "info_loja",
        "Endereco, telefone e horario de funcionamento das lojas. Sem loja, lista todas.",
        {
            "type": "object",
            "properties": {
                "loja": {"type": "string", "description": "Nome ou parte do nome da loja"}
            },
            "additionalProperties": False,
        },
    ),
    Ferramenta(
        "consultar_pontos",
        "Saldo de pontos Lorenzi+ do cliente logado, categoria, quanto falta para a proxima, "
        "pontos que vencem nos proximos 30 dias e os beneficios da categoria.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Ferramenta(
        "consultar_pedidos",
        "Os ultimos pedidos do cliente logado: numero, data, loja, situacao, valor e pecas.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Ferramenta(
        "montar_carrinho",
        "Coloca um SKU na sacola do cliente logado. Use so quando o cliente pedir para comprar ou "
        "separar a peca.",
        {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "quantidade": {"type": "integer", "description": "De 1 a 10 (padrao 1)"},
            },
            "required": ["sku"],
            "additionalProperties": False,
        },
    ),
    Ferramenta(
        "transferir_para_atendente",
        "Abre um chamado e passa a conversa para a equipe. Use quando o cliente pedir uma pessoa, "
        "quando houver reclamacao, troca, problema com pagamento ou pedido, ou quando nao der para "
        "resolver com as outras ferramentas.",
        {
            "type": "object",
            "properties": {
                "motivo": {"type": "string", "description": "Assunto curto do chamado"},
                "resumo": {
                    "type": "string",
                    "description": "2 ou 3 linhas com o essencial da conversa",
                },
                "categoria": {
                    "type": "string",
                    "description": "Uma de: " + ", ".join(CATEGORIAS_DE_CHAMADO),
                },
            },
            "required": ["motivo", "resumo"],
            "additionalProperties": False,
        },
    ),
    Ferramenta(
        "consultar_politica",
        "Politicas oficiais da loja: trocas, devolucao, defeito, reembolso, cancelamento, "
        "frete, prazo de entrega, retirada na loja, pagamento e parcelamento, ajustes e "
        "agendamento, regras do Lorenzi+. Responda so com o texto devolvido.",
        {
            "type": "object",
            "properties": {
                "tema": {"type": "string", "description": "Um de: " + ", ".join(TEMAS_DE_POLITICA)}
            },
            "required": ["tema"],
            "additionalProperties": False,
        },
    ),
]


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).strip()


def _tema_da_politica(tema: str) -> str | None:
    """'troca', 'Trocas' ou 'prazo de entrega' tambem valem: o codigo exato, se houver um so."""
    palavras = re.findall(r"[a-z]+", _normalizar(tema))
    alvo = "_".join(p for p in palavras if p not in {"de", "da", "do", "e", "a", "o"})
    if alvo in TEMAS_DE_POLITICA:
        return alvo
    parecidos = [t for t in TEMAS_DE_POLITICA if t.startswith(alvo) or alvo.startswith(t)]
    return parecidos[0] if len(parecidos) == 1 else None


class Ferramentas:
    """Executa as ferramentas para o cliente do token. Guarda o que o fluxo precisa saber depois
    (chamado aberto, sacola alterada)."""

    def __init__(
        self, conexao: Connection, usuario: UsuarioAtual, id_conversa: UUID | None = None
    ) -> None:
        self.conexao, self.usuario, self.id_conversa = conexao, usuario, id_conversa
        self.id_atendimento: UUID | None = None
        # Loja do chamado (None = fila geral), para o aviso de horario da resposta.
        self.id_loja_chamado: UUID | None = None
        self.carrinho_alterado = False

    def executar(self, nome: str, argumentos: dict[str, Any]) -> dict[str, Any]:
        metodo = getattr(self, f"_{nome}", None) if nome in {d.nome for d in DECLARACOES} else None
        if metodo is None:
            return {"erro": "ferramenta_desconhecida"}
        try:
            return metodo(argumentos if isinstance(argumentos, dict) else {})
        except ValidationError:
            return {"erro": "argumentos_invalidos"}
        except Exception as erro:  # noqa: BLE001 - a falha vira resposta controlada, sem dado inventado
            log.warning("ferramenta %s falhou: %s", nome, type(erro).__name__)
            # A pergunta ja foi confirmada; o rollback so libera a transacao para gravar a resposta.
            self.conexao.rollback()
            return {"erro": "nao_foi_possivel_consultar"}

    # ---------------------------------------------------------------- consultas

    def _buscar_produto(self, argumentos: dict[str, Any]) -> dict[str, Any]:
        dados = BuscarProduto.model_validate(argumentos)
        palavras = re.findall(r"[0-9a-zà-ÿ]{2,}", _normalizar(dados.descricao))
        termos = [t for t in palavras if t not in SEM_PESO][:6]
        if not termos:
            return {"pecas": [], "observacao": "descricao sem termos de busca"}
        pecas = repositorio.buscar_produtos(self.conexao, termos, LIMITE_PRODUTOS)
        return {"pecas": [{**p, "variacoes": p["variacoes"][:12]} for p in pecas]}

    def _consultar_estoque(self, argumentos: dict[str, Any]) -> dict[str, Any]:
        dados = ConsultarEstoque.model_validate(argumentos)
        sku = dados.sku.upper()
        linhas = [
            r for r in cliente.listar_estoque_catalogo(self.conexao) if str(r["sku"]).upper() == sku
        ]
        if dados.loja:
            alvo = _normalizar(dados.loja)
            linhas = [r for r in linhas if alvo in _normalizar(str(r["loja"]))]
        if not linhas:
            return {"sku": sku, "encontrado": False}
        por_loja = [{"loja": r["loja"], "quantidade": r["quantidade"]} for r in linhas]
        return {
            "sku": sku,
            "encontrado": True,
            "por_loja": por_loja,
            "total": sum(r["quantidade"] for r in linhas),
        }

    def _lojas(self) -> list[dict[str, Any]]:
        return cliente.listar_lojas(self.conexao, self.usuario)

    def _info_loja(self, argumentos: dict[str, Any]) -> dict[str, Any]:
        dados = InfoLoja.model_validate(argumentos)
        lojas = self._lojas()
        if dados.loja:
            alvo = _normalizar(dados.loja)
            lojas = [lj for lj in lojas if alvo in _normalizar(str(lj["nome"]))]
        return {
            "lojas": [
                {
                    "nome": lj["nome"],
                    "endereco": lj.get("endereco"),
                    "cidade": lj.get("cidade"),
                    "uf": lj.get("uf"),
                    "telefone": lj.get("telefone"),
                    # Nulo = a loja nao tem horario cadastrado: o assistente deve dizer isso.
                    "horario_funcionamento": descrever(lj.get("horario_funcionamento")),
                    "aberta_agora": aberta(lj.get("horario_funcionamento"), datetime.now(SP))
                    if lj.get("horario_funcionamento")
                    else None,
                }
                for lj in lojas
            ]
        }

    def _consultar_pontos(self, argumentos: dict[str, Any]) -> dict[str, Any]:
        SemArgumentos.model_validate(argumentos)
        p = cliente.obter_vulto_mais(self.conexao, self.usuario)
        return {
            "saldo": p["saldo"],
            "categoria": p["categoria"],
            "proxima_categoria": p.get("proxima_categoria"),
            "faltam_para_proxima": p.get("faltam_para_proxima"),
            "pontos_a_vencer_30_dias": p.get("pontos_a_vencer", 0),
            "proximos_vencimentos": p.get("proximos_vencimentos", []),
            "beneficios": [b["titulo"] for b in p.get("beneficios", [])],
            "regras": p.get("regras"),
        }

    def _consultar_pedidos(self, argumentos: dict[str, Any]) -> dict[str, Any]:
        SemArgumentos.model_validate(argumentos)
        pedidos = cliente.listar_pedidos(self.conexao, self.usuario, limit=LIMITE_PEDIDOS, offset=0)
        return {
            "pedidos": [
                {
                    "numero": p.get("numero_pedido"),
                    "data": p.get("criado_em"),
                    "loja": p.get("loja"),
                    "situacao": p.get("status"),
                    "valor_total": p.get("valor_total"),
                    "pecas": [
                        f"{i.get('produto')} ({i.get('cor')}, {i.get('tamanho')})"
                        f" x{i.get('quantidade')}"
                        for i in p.get("itens", [])
                    ],
                }
                for p in pedidos
            ]
        }

    def _consultar_politica(self, argumentos: dict[str, Any]) -> dict[str, Any]:
        dados = ConsultarPolitica.model_validate(argumentos)
        codigo = _tema_da_politica(dados.tema)
        if codigo is None:
            return {"erro": "tema_desconhecido", "temas_validos": list(TEMAS_DE_POLITICA)}
        politica = politicas.todas()[codigo]
        resultado = {
            # Antes do texto: o modelo menor tende a repetir a secao inteira.
            "como_responder": (
                "Responda em 1 ou 2 frases curtas so o que o cliente perguntou, com base neste "
                "texto. Nao repita o texto inteiro."
            ),
            "tema": politica.codigo,
            "titulo": politica.titulo,
            "texto": politica.texto,
        }
        if politica.pendente:
            resultado["orientacao"] = (
                "ha ponto sem definicao oficial: nao informe esse ponto; ofereca transferir para a "
                "equipe (transferir_para_atendente)"
            )
        return resultado

    # ---------------------------------------------------------------- acoes

    def _montar_carrinho(self, argumentos: dict[str, Any]) -> dict[str, Any]:
        dados = MontarCarrinho.model_validate(argumentos)
        id_variacao = repositorio.variacao_ativa_pelo_sku(self.conexao, dados.sku)
        if id_variacao is None:
            return {"adicionado": False, "motivo": "sku_nao_encontrado"}
        cliente.adicionar_item_carrinho(
            self.conexao, self.usuario, {"id_variacao": id_variacao, "quantidade": dados.quantidade}
        )
        self.carrinho_alterado = True
        return {"adicionado": True, "sku": dados.sku.upper(), "quantidade": dados.quantidade}

    def _transferir_para_atendente(self, argumentos: dict[str, Any]) -> dict[str, Any]:
        dados = TransferirParaAtendente.model_validate(argumentos)
        # O atendente recebe o resumo do modelo e a conversa inteira: o cliente nao repete nada.
        chamado = passagem.abrir_chamado_da_conversa(
            self.conexao,
            self.usuario,
            self.id_conversa,
            assunto=dados.motivo,
            motivo=dados.motivo,
            categoria=dados.categoria if dados.categoria in CATEGORIAS_DE_CHAMADO else "outro",
            resumo=dados.resumo,
        )
        self.id_atendimento = UUID(str(chamado["id_atendimento"]))
        self.id_loja_chamado = UUID(str(chamado["id_loja"])) if chamado.get("id_loja") else None
        return {
            "transferido": True,
            "protocolo": chamado.get("protocolo"),
            "equipe": chamado.get("loja_nome") or "atendimento geral",
        }
