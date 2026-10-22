"""Leitura do banco antigo do Vulto+ (vulto.db, SQLite). Só leitura: o arquivo é aberto em modo ro."""
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .regras import SP, cpf, cpf_valido, digitos

# Status de venda que não dão pontos (cancelada, aguardando pagamento, estornada ou contestada no cartão).
STATUS_SEM_PONTOS = {'cancelado', 'cancelada', 'aguardando', 'estornado', 'estornada', 'chargeback'}

# Canais em que a compra vale pontos em dobro (site e app).
CANAIS_ONLINE = {'site', 'app', 'online', 'web', 'e-commerce', 'ecommerce'}

_FORMATOS = ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M')


def momento(s):
    """As datas do banco vêm em 5 formatos; as terminadas em Z estão em UTC, as demais em São Paulo."""
    s = str(s).strip()
    if s.endswith('Z'):
        return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    for formato in _FORMATOS:
        try:
            return datetime.strptime(s, formato).replace(tzinfo=SP)
        except ValueError:
            pass
    raise ValueError(f'data do banco em formato desconhecido: {s!r}')


@dataclass
class Compra:
    id: int
    cliente_ref: str
    reais: float
    online: bool
    loja_id: int | None
    quando: datetime
    status_venda: str  # '' quando não há venda ligada

    @property
    def da_pontos(self):
        return self.status_venda not in STATUS_SEM_PONTOS

    @property
    def pontos(self):
        """R$ 1 = 1 ponto; site e app valem o dobro. Arredonda depois de multiplicar."""
        return round(self.reais * (2 if self.online else 1))


@dataclass
class Movimento:
    cpf: str
    tipo: str          # C crédito, D resgate, E estorno, AJ ajuste manual
    qtd: int
    quando: datetime
    compra: Compra | None
    obs: str = ''


@dataclass
class Funcionario:
    nome: str
    loja_id: int | None
    perfil: str       # vendedor, gerente, operador, admin


@dataclass
class Venda:
    loja_id: int | None
    cliente_ref: str
    vendedor: str     # apelido livre digitado no PDV ("rafa.pin", "bia")
    quando: datetime


@dataclass
class Banco:
    movimentos: dict = field(default_factory=dict)   # cpf -> [Movimento]
    compras: dict = field(default_factory=dict)      # id -> Compra
    cpfs: set = field(default_factory=set)
    lojas: dict = field(default_factory=dict)        # id -> nome
    # Compras lançadas com telefone ou e-mail no lugar do CPF: o banco não deu pontos a elas.
    sem_cpf: list = field(default_factory=list)      # [Compra]
    funcionarios: list = field(default_factory=list)  # [Funcionario] ativos
    vendas: list = field(default_factory=list)       # [Venda]


def valor_em_reais(valor, origem):
    """O app grava centavos (25990) e às vezes reais (259.9); site e PDV gravam reais, às vezes com vírgula."""
    s = str(valor).strip()
    if origem == 'app' and re.fullmatch(r'\d+', s):
        return int(s) / 100
    return float(s.replace(',', '.'))


def ler(caminho):
    con = sqlite3.connect(f'file:{caminho}?mode=ro', uri=True)
    try:
        banco = Banco()
        banco.lojas = dict(con.execute('SELECT id, nome FROM lojas'))
        status = {}
        for compra_id, st in con.execute('SELECT compra_id, status FROM vendas WHERE compra_id IS NOT NULL ORDER BY id'):
            status.setdefault(compra_id, (st or '').strip().lower())
        for cid, ref, valor, canal, loja_id, criado, origem in con.execute(
            'SELECT id, cliente_ref, valor, canal, loja_id, criado_em, origem FROM compras'
        ):
            banco.compras[cid] = Compra(
                id=cid,
                cliente_ref=(ref or '').strip(),
                reais=valor_em_reais(valor, origem),
                online=(canal or '').strip().lower() in CANAIS_ONLINE,
                loja_id=loja_id,
                quando=momento(criado),
                status_venda=status.get(cid, ''),
            )
        # Só as colunas necessárias: a tabela também guarda a senha, que não é lida.
        for nome, loja_id, perfil in con.execute('SELECT nome, loja_id, perfil FROM funcionarios WHERE ativo = 1'):
            banco.funcionarios.append(Funcionario((nome or '').strip().lower(), loja_id, (perfil or '').strip().lower()))
        for loja_id, ref, vendedor, criado in con.execute('SELECT loja_id, cliente_ref, vendedor, criado_em FROM vendas'):
            banco.vendas.append(Venda(loja_id, (ref or '').strip(), (vendedor or '').strip().lower(), momento(criado)))
        creditadas = set()
        for cpf_bruto, tipo, qtd, criado, compra_id, obs in con.execute(
            'SELECT cpf, tipo, qtd, criado_em, compra_id, obs FROM pontos_mov ORDER BY id'
        ):
            c = cpf(cpf_bruto)
            mov = Movimento(c, tipo, int(qtd), momento(criado), banco.compras.get(compra_id), (obs or '').strip().lower())
            banco.movimentos.setdefault(c, []).append(mov)
            banco.cpfs.add(c)
            if compra_id is not None:
                creditadas.add(compra_id)
        for compra in banco.compras.values():
            d = digitos(compra.cliente_ref)
            if cpf_valido(d):
                banco.cpfs.add(d)
            elif compra.id not in creditadas and ('@' in compra.cliente_ref or 8 <= len(d) <= 13):
                banco.sem_cpf.append(compra)
        return banco
    finally:
        con.close()
