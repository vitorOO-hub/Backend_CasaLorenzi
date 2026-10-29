"""Consultas permitidas ao assistente admin; toda regra de acesso continua no servidor."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Connection

from app.chamados import service as chamados_service
from app.clientes import service as clientes_service
from app.core.config import Settings
from app.core.papeis import Papel, UsuarioAtual
from app.gerencia import service as gerencia_service
from app.gerencia.repositorio import Filtro
from app.gestao import auditoria, catalogo, integracoes, vendas_pendentes
from app.gestao import service as gestao_service
from app.painel_estoque import minimos, service_escrita, transferencias
from app.painel_estoque import service as estoque_service
from app.painel_estoque.repositorio import FiltroSaldo

FERRAMENTAS: list[dict[str, Any]] = [
    {
        "name": "consultar_vendas",
        "description": "Indicadores e vendas da rede em um periodo. Datas no formato AAAA-MM-DD.",
        "parameters": {
            "type": "object",
            "properties": {
                "inicio": {"type": "string", "format": "date"},
                "fim": {"type": "string", "format": "date"},
                "id_loja": {"type": "string", "format": "uuid"},
                "categoria": {"type": "string"},
                "canal": {"type": "string", "enum": ["loja", "online"]},
                "marca": {"type": "string"},
            },
            "required": ["inicio", "fim"],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_estoque",
        "description": ("Saldo atual por peça, filtrado por loja, termo, categoria ou situação."),
        "parameters": {
            "type": "object",
            "properties": {
                "id_loja": {"type": "string", "format": "uuid"},
                "busca": {"type": "string"},
                "categoria": {"type": "string"},
                "situacao": {"type": "string", "enum": ["ok", "baixo", "esgotado"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_movimentacoes_estoque",
        "description": (
            "Consulta o histórico de entradas, saídas, ajustes e transferências de estoque."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id_loja": {"type": "string", "format": "uuid"},
                "tipo": {"type": "string", "enum": ["entrada", "saida", "ajuste", "transferencia"]},
                "sku": {"type": "string", "maxLength": 60},
                "de": {"type": "string", "format": "date"},
                "ate": {"type": "string", "format": "date"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_ajustes_estoque",
        "description": "Consulta ajustes de inventário pendentes, aprovados ou recusados.",
        "parameters": {
            "type": "object",
            "properties": {
                "id_loja": {"type": "string", "format": "uuid"},
                "situacao": {
                    "type": "string",
                    "enum": ["pendente", "aprovado", "rejeitado", "decididos"],
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_transferencias_estoque",
        "description": "Consulta transferências ou reposições da rede por situação.",
        "parameters": {
            "type": "object",
            "properties": {
                "id_loja": {"type": "string", "format": "uuid"},
                "situacao": {"type": "string", "enum": ["acao", "andamento", "todas"]},
                "tipo": {"type": "string", "enum": ["transferencia", "reposicao_rede"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_estoque_minimo",
        "description": "Consulta os níveis mínimos de estoque definidos para uma loja.",
        "parameters": {
            "type": "object",
            "properties": {
                "id_loja": {"type": "string", "format": "uuid"},
                "busca": {"type": "string", "maxLength": 80},
            },
            "required": ["id_loja"],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_reposicao",
        "description": (
            "Peças que precisam de reposição, com saldo, mínimo, giro e dias de cobertura."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id_loja": {"type": "string", "format": "uuid"},
                "categoria": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_estoque_parado",
        "description": "Peças com saldo e sem venda no período informado.",
        "parameters": {
            "type": "object",
            "properties": {
                "dias": {"type": "integer", "minimum": 7, "maximum": 365},
                "id_loja": {"type": "string", "format": "uuid"},
                "categoria": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_lojas",
        "description": "Resumo operacional das lojas: equipe, estoque, alertas, vendas e chamados.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "consultar_pendencias",
        "description": "Totais de ajustes de estoque, transferências e chamados aguardando ação.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "consultar_chamados",
        "description": "Consulta chamados de atendimento por situação e prioridade.",
        "parameters": {
            "type": "object",
            "properties": {
                "situacao": {
                    "type": "string",
                    "enum": [
                        "abertos",
                        "aberto",
                        "em_andamento",
                        "resolvido",
                        "todos",
                        "historico_vulto",
                    ],
                },
                "prioridade": {"type": "string", "enum": ["baixa", "media", "alta", "urgente"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_mensagens_chamado",
        "description": "Lê as mensagens de um chamado que o admin pode acessar.",
        "parameters": {
            "type": "object",
            "properties": {"id_atendimento": {"type": "string", "format": "uuid"}},
            "required": ["id_atendimento"],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_pontos_a_vencer",
        "description": (
            "Totais de clientes e pontos com vencimento próximo; não retorna nomes de clientes."
        ),
        "parameters": {
            "type": "object",
            "properties": {"dias": {"type": "integer", "minimum": 1, "maximum": 90}},
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_equipe",
        "description": "Lista funcionários, cargos, lojas e situação de acesso.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "consultar_catalogo",
        "description": (
            "Busca peças do catálogo por nome, SKU ou descrição semântica, com preços e estoque."
        ),
        "parameters": {
            "type": "object",
            "properties": {"busca": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "buscar_cliente",
        "description": (
            "Busca clientes por nome, e-mail ou telefone. Use termo específico e retorne "
            "no máximo cinco resultados."
        ),
        "parameters": {
            "type": "object",
            "properties": {"busca": {"type": "string", "minLength": 2, "maxLength": 80}},
            "required": ["busca"],
            "additionalProperties": False,
        },
    },
    {
        "name": "detalhar_cliente",
        "description": (
            "Consulta ficha, contato, compras e chamados do cliente previamente localizado."
        ),
        "parameters": {
            "type": "object",
            "properties": {"id_cliente": {"type": "string", "format": "uuid"}},
            "required": ["id_cliente"],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_auditoria",
        "description": "Busca registros recentes da auditoria por pessoa, ação ou detalhe.",
        "parameters": {
            "type": "object",
            "properties": {"busca": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_integracoes",
        "description": "Consulta lotes de integração e registros que aguardam mapeamento.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "consultar_vendas_pendentes",
        "description": "Lista vendas importadas do legado ainda pendentes, agrupadas por motivo.",
        "parameters": {
            "type": "object",
            "properties": {"grupo": {"type": "string"}},
            "additionalProperties": False,
        },
    },
]


class FerramentaInvalida(Exception):
    pass


def _somente_admin(usuario: UsuarioAtual) -> None:
    if usuario.papel is not Papel.ADMIN:
        raise FerramentaInvalida("Ferramenta disponível somente para administrador")


def executar(
    conexao: Connection,
    usuario: UsuarioAtual,
    nome: str,
    argumentos: dict[str, Any],
    configuracoes: Settings | None = None,
) -> dict[str, Any] | list[Any]:
    """Executa uma função allowlisted. Nunca interpreta SQL ou nomes vindos do modelo."""
    _somente_admin(usuario)
    definicao = next((item for item in FERRAMENTAS if item["name"] == nome), None)
    if definicao is None or not isinstance(argumentos, dict):
        raise FerramentaInvalida("Consulta não permitida")
    propriedades = definicao["parameters"]["properties"]
    obrigatorios = definicao["parameters"].get("required", [])
    if set(argumentos) - set(propriedades) or set(obrigatorios) - set(argumentos):
        raise FerramentaInvalida("Argumentos inválidos para a consulta")
    for chave, valor in argumentos.items():
        regra = propriedades[chave]
        if regra["type"] == "string" and not isinstance(valor, str):
            raise FerramentaInvalida("Argumentos inválidos para a consulta")
        if regra["type"] == "integer" and (not isinstance(valor, int) or isinstance(valor, bool)):
            raise FerramentaInvalida("Argumentos inválidos para a consulta")
        if "enum" in regra and valor not in regra["enum"]:
            raise FerramentaInvalida("Argumentos inválidos para a consulta")
        if regra["type"] == "integer" and not (
            regra.get("minimum", valor) <= valor <= regra.get("maximum", valor)
        ):
            raise FerramentaInvalida("Argumentos inválidos para a consulta")
        if regra.get("format") == "date":
            try:
                date.fromisoformat(valor)
            except ValueError as erro:
                raise FerramentaInvalida("Data inválida") from erro
        if regra.get("format") == "uuid":
            try:
                UUID(valor)
            except ValueError as erro:
                raise FerramentaInvalida("Identificador inválido") from erro
        if regra["type"] == "string" and (
            regra.get("minLength", 0) > len(valor) or len(valor) > regra.get("maxLength", 1000)
        ):
            raise FerramentaInvalida("Argumentos inválidos para a consulta")

    if nome == "consultar_vendas":
        inicio = date.fromisoformat(argumentos["inicio"])
        fim = date.fromisoformat(argumentos["fim"])
        gerencia_service.validar_periodo(inicio, fim)
        if (fim - inicio).days > 366:
            raise FerramentaInvalida("A consulta de vendas aceita períodos de até 367 dias")
        loja = UUID(argumentos["id_loja"]) if argumentos.get("id_loja") else None
        filtro = Filtro(
            loja,
            argumentos.get("categoria"),
            argumentos.get("canal"),
            marca=argumentos.get("marca"),
        )
        return gerencia_service.montar_dashboard(
            conexao, usuario, inicio=inicio, fim=fim, filtro=filtro
        )
    if nome == "consultar_estoque":
        loja = UUID(argumentos["id_loja"]) if argumentos.get("id_loja") else None
        filtro = FiltroSaldo(
            loja,
            argumentos.get("busca"),
            argumentos.get("categoria"),
            argumentos.get("situacao"),
        )
        return estoque_service.montar_saldo(conexao, filtro, limit=50, offset=0)
    if nome == "consultar_movimentacoes_estoque":
        loja = UUID(argumentos["id_loja"]) if argumentos.get("id_loja") else None
        filtro = estoque_service.filtro_de_movimentacoes(
            conexao,
            usuario,
            id_loja=loja,
            grupo=argumentos.get("tipo"),
            sku=argumentos.get("sku"),
            de=date.fromisoformat(argumentos["de"]) if argumentos.get("de") else None,
            ate=date.fromisoformat(argumentos["ate"]) if argumentos.get("ate") else None,
        )
        return estoque_service.montar_movimentacoes(conexao, filtro, limit=30, offset=0)
    if nome == "consultar_ajustes_estoque":
        loja = UUID(argumentos["id_loja"]) if argumentos.get("id_loja") else None
        return service_escrita.listar_ajustes(
            conexao, usuario, id_loja=loja, status=argumentos.get("situacao"), limit=30, offset=0
        )
    if nome == "consultar_transferencias_estoque":
        loja = UUID(argumentos["id_loja"]) if argumentos.get("id_loja") else None
        return transferencias.listar_do_usuario(
            conexao,
            usuario,
            id_loja=loja,
            situacao=argumentos.get("situacao", "acao"),
            tipo=argumentos.get("tipo"),
            limit=30,
            offset=0,
        )
    if nome == "consultar_estoque_minimo":
        return minimos.listar(
            conexao,
            usuario,
            id_loja=UUID(argumentos["id_loja"]),
            busca=argumentos.get("busca"),
            limit=50,
            offset=0,
        )
    if nome == "consultar_reposicao":
        loja = UUID(argumentos["id_loja"]) if argumentos.get("id_loja") else None
        return gerencia_service.montar_reposicao(
            conexao, Filtro(loja, argumentos.get("categoria")), limite=20
        )
    if nome == "consultar_estoque_parado":
        dias = int(argumentos.get("dias", 60))
        if not 7 <= dias <= 365:
            raise FerramentaInvalida("O período deve estar entre 7 e 365 dias")
        loja = UUID(argumentos["id_loja"]) if argumentos.get("id_loja") else None
        return gerencia_service.montar_estoque_parado(
            conexao, Filtro(loja, argumentos.get("categoria")), dias=dias, limite=30
        )
    if nome == "consultar_lojas":
        return gerencia_service.montar_lojas(conexao, Filtro(None))
    if nome == "consultar_pendencias":
        return gerencia_service.montar_pendencias(
            conexao, Filtro(None), incluir_chamados_sem_loja=False
        )
    if nome == "consultar_chamados":
        escopo = chamados_service.montar_escopo(conexao, usuario, None)
        return chamados_service.listar(
            conexao,
            escopo,
            situacao=argumentos.get("situacao", "abertos"),
            responsavel="todos",
            prioridade=argumentos.get("prioridade"),
            canal=None,
            categoria=None,
            limit=20,
            offset=0,
        )
    if nome == "consultar_mensagens_chamado":
        escopo = chamados_service.montar_escopo(conexao, usuario, None)
        return chamados_service.mensagens(conexao, escopo, UUID(argumentos["id_atendimento"]))
    if nome == "consultar_pontos_a_vencer":
        dias = int(argumentos.get("dias", 30))
        if not 1 <= dias <= 90:
            raise FerramentaInvalida("O período deve estar entre 1 e 90 dias")
        return gerencia_service.montar_pontos_a_vencer(conexao, dias=dias)
    if nome == "consultar_equipe":
        return gestao_service.montar_equipe(conexao, usuario)
    if nome == "consultar_catalogo":
        busca = argumentos.get("busca")
        resultado = catalogo.listar_para_assistente(
            conexao, usuario, busca=busca, limit=30, offset=0
        )
        chave = configuracoes.gemini_api_key if configuracoes else None
        if (
            resultado["itens"]
            or not busca
            or chave is None
            or not catalogo.tem_embeddings(conexao, usuario)
        ):
            return resultado
        from app.assistente import embeddings

        vetor = embeddings.gerar(busca, chave)
        return catalogo.buscar_semantico(conexao, usuario, vetor, limite=5)
    if nome == "buscar_cliente":
        escopo = clientes_service.montar_escopo(conexao, usuario, None)
        return clientes_service.listar(
            conexao,
            usuario,
            escopo,
            busca=argumentos["busca"],
            secao="todos",
            limit=5,
            offset=0,
        )
    if nome == "detalhar_cliente":
        escopo = clientes_service.montar_escopo(conexao, usuario, None)
        return clientes_service.ficha(conexao, usuario, escopo, UUID(argumentos["id_cliente"]))
    if nome == "consultar_auditoria":
        return auditoria.listar(conexao, usuario, busca=argumentos.get("busca"), limit=20, offset=0)
    if nome == "consultar_integracoes":
        return integracoes.montar(conexao, usuario)
    if nome == "consultar_vendas_pendentes":
        grupo = argumentos.get("grupo")
        if grupo is not None and grupo not in vendas_pendentes.GRUPOS:
            raise FerramentaInvalida("Grupo de pendência inválido")
        return {
            **vendas_pendentes.listar(
                conexao, usuario, limit=20, offset=0, grupo=grupo, estado="pendente"
            ),
            "por_grupo": vendas_pendentes.resumo_por_grupo(conexao, usuario, "pendente"),
        }
    raise FerramentaInvalida("Consulta não permitida")
