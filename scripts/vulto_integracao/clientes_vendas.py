"""Resolve o CPF de uma venda Vulto sem promover conciliacoes pendentes."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

SITUACOES_VINCULO_CONFIRMADAS = frozenset(
    {"preexistente_nao_alterado", "vinculado_confirmado"}
)


@dataclass(frozen=True)
class ResolucaoCpfVenda:
    cpf: str | None
    motivo: str


def normalizar_cpf(valor: object) -> str:
    """Retorna apenas digitos; a validade deve ser conferida separadamente."""
    if isinstance(valor, bool) or valor is None:
        return ""
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return "".join(caractere for caractere in str(valor) if caractere in "0123456789")


def cpf_valido(valor: object) -> bool:
    cpf = normalizar_cpf(valor)
    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False

    digitos = [int(caractere) for caractere in cpf]
    for posicao in (9, 10):
        soma = sum(digitos[indice] * (posicao + 1 - indice) for indice in range(posicao))
        verificador = (soma * 10) % 11
        if verificador == 10:
            verificador = 0
        if digitos[posicao] != verificador:
            return False
    return True


def indexar_compras_por_id(compras: Iterable[Mapping[str, object]]) -> dict[str, str | None]:
    """Indexa IDs únicos; compra repetida ou CPF inválido não pode identificar cliente."""
    indice: dict[str, str | None] = {}
    ids_repetidos: set[str] = set()

    for compra in compras:
        id_compra = str(compra.get("id") or "").strip()
        if not id_compra:
            continue
        cpf = normalizar_cpf(compra.get("cpf_cliente_quando_identificavel"))
        candidato = cpf if cpf_valido(cpf) else None

        if id_compra in indice:
            ids_repetidos.add(id_compra)
        else:
            indice[id_compra] = candidato

    for id_compra in ids_repetidos:
        indice[id_compra] = None
    return indice


def indexar_clientes_por_cpf(
    clientes: Iterable[Mapping[str, object]],
    tipos_por_id: Mapping[str, str] | None = None,
) -> dict[str, str | None]:
    """Indexa CPFs de clientes ativos; documentos repetidos ficam indisponiveis."""
    indice: dict[str, str | None] = {}
    cpfs_repetidos: set[str] = set()

    for cliente in clientes:
        if str(cliente.get("ativo", "true")).strip().lower() != "true":
            continue
        if tipos_por_id is not None:
            tipo_id = str(cliente.get("id_tipo_usuario") or "").strip()
            if tipos_por_id.get(tipo_id) != "cliente":
                continue
        cpf = normalizar_cpf(cliente.get("documento"))
        id_cliente = str(cliente.get("id_usuario") or "").strip()
        if not cpf_valido(cpf) or not id_cliente:
            continue
        if cpf in indice:
            cpfs_repetidos.add(cpf)
        else:
            indice[cpf] = id_cliente

    for cpf in cpfs_repetidos:
        indice[cpf] = None
    return indice


def listar_vendas_pendentes_cliente(
    vendas: Iterable[Mapping[str, object]],
    cpfs_por_compra: Mapping[str, str | None],
    clientes_por_cpf: Mapping[str, str | None],
) -> list[dict[str, str]]:
    """Retorna somente ID da venda e motivo, sem incluir CPF ou outros dados pessoais."""
    pendencias = []
    for venda in vendas:
        id_venda = str(venda.get("id") or "").strip()
        id_cliente, resolucao = resolver_id_cliente_venda(
            venda, cpfs_por_compra, clientes_por_cpf
        )
        if id_cliente is None:
            pendencias.append(
                {"venda_id": id_venda, "pendencia_cliente": resolucao.motivo}
            )
    return pendencias


def resolver_cpf_venda(
    venda: Mapping[str, object], cpfs_por_compra: Mapping[str, str | None]
) -> ResolucaoCpfVenda:
    """Usa CPF da venda ou, com vínculo confirmado, o CPF da compra relacionada."""
    cpf_venda = normalizar_cpf(venda.get("cpf_padronizado"))
    if cpf_venda:
        if cpf_valido(cpf_venda):
            return ResolucaoCpfVenda(cpf_venda, "cpf_da_venda")
        return ResolucaoCpfVenda(None, "cpf_da_venda_invalido")

    situacao = str(venda.get("situacao_vinculo_compra") or "").strip()
    if situacao not in SITUACOES_VINCULO_CONFIRMADAS:
        return ResolucaoCpfVenda(None, "vinculo_compra_pendente")

    id_compra = str(venda.get("compra_id_resolvida") or "").strip()
    if not id_compra:
        return ResolucaoCpfVenda(None, "sem_compra_id_resolvida")
    if id_compra not in cpfs_por_compra:
        return ResolucaoCpfVenda(None, "compra_nao_encontrada")

    cpf_compra = cpfs_por_compra[id_compra]
    if cpf_compra is None:
        return ResolucaoCpfVenda(None, "cpf_da_compra_ausente_ambiguo_ou_invalido")
    if not cpf_valido(cpf_compra):
        return ResolucaoCpfVenda(None, "cpf_da_compra_invalido")
    return ResolucaoCpfVenda(normalizar_cpf(cpf_compra), "cpf_de_compra_com_vinculo_confirmado")


def resolver_id_cliente_venda(
    venda: Mapping[str, object],
    cpfs_por_compra: Mapping[str, str | None],
    clientes_por_cpf: Mapping[str, str | None],
) -> tuple[str | None, ResolucaoCpfVenda]:
    """Resolve id_usuario apenas quando o CPF aponta para um cliente unico cadastrado."""
    resolucao_cpf = resolver_cpf_venda(venda, cpfs_por_compra)
    if resolucao_cpf.cpf is None:
        return None, resolucao_cpf
    if resolucao_cpf.cpf not in clientes_por_cpf:
        return None, ResolucaoCpfVenda(resolucao_cpf.cpf, "cliente_nao_encontrado_por_cpf")
    id_cliente = clientes_por_cpf[resolucao_cpf.cpf]
    if id_cliente is None:
        return None, ResolucaoCpfVenda(resolucao_cpf.cpf, "cpf_ambiguo_no_cadastro_de_clientes")
    return id_cliente, resolucao_cpf
