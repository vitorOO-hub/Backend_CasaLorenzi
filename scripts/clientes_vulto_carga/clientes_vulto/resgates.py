"""Aba Resgates: cliente por CPF ou deduzido pelo nome, atendente pelo cadastro de funcionários,
desconto conferido com a regra do programa.

Regras (decisão do time, conferidas contra a planilha final):
- cliente só com nome: vale o único cliente com aquele nome (completo, ou só o primeiro nome); se
  houver vários, o único deles com compra na mesma loja no mesmo dia (±1). Sem isso o resgate é
  removido, porque não existe resgate sem CPF;
- atendente: o apelido vira o funcionário da loja do resgate; "gerente" é o gerente da loja.
  Apelido de mais de um funcionário da loja ("rafa") desempata por quem registrou vendas na loja
  naquele dia. Sem certeza, o apelido fica como está e a observação explica;
- desconto: R$ 10 a cada 100 pontos até fev/2025 e R$ 5 a cada 100 desde mar/2025; o que passar
  da regra só é anotado.
"""
import re
from datetime import date, datetime, timedelta

from . import regras as r

COLUNAS = ['data', 'cliente', 'pontos usados', 'desconto R$', 'loja', 'atendente', 'observacao']

# Nos resgates, data só com mês e ano ("jan/23") vira o dia 1 (assim está na planilha final).
DIA_DE_MES_ANO = 1

# Regra do desconto: (início da regra, reais a cada 100 pontos, como a observação descreve a regra).
REGRAS_DE_DESCONTO = [
    (date(2025, 3, 1), 5, 'desde mar/2025'),
    (date.min, 10, 'até fev/2025'),
]

# Apelidos que não são o começo do nome -> começo do nome do funcionário.
APELIDOS = {
    'bia': ('beatriz', 'bianca'), 'rafa': ('rafael', 'rafaela'), 'cami': ('camila',),
    'lari': ('larissa',), 'pati': ('patricia',), 'fer': ('fernanda',), 'gus': ('gustavo',),
    'jess': ('jessica',), 'tiago': ('thiago',), 'carlinhos': ('carlos',),
    'ap': ('ana paula',), 'anapaula': ('ana paula',),
}

PERFIS_DE_LOJA = {'vendedor', 'gerente'}


def _chave(s):
    return re.sub(r'\s+', ' ', r.sem_acento(s or '').lower()).strip()


def candidatos(apelido, funcionarios):
    """Funcionários que o apelido pode ser: 'bia' -> beatriz e bianca; 'beatriz s.' -> beatriz souza;
    'rafa.pin' -> rafael e rafaela (o que vem depois do ponto é a loja)."""
    a = _chave(apelido).rstrip('.')
    a = re.sub(r'\.[a-z]{3,}$', '', a)          # 'fer.batel' -> 'fer'
    partes = a.replace('.', ' ').split()
    inicial = None
    if len(partes) > 1 and len(partes[-1]) == 1:  # 'patricia w.' / 'thiago m'
        inicial = partes.pop()
    a = ' '.join(partes)
    prefixos = APELIDOS.get(a, (a,))
    saida = []
    for f in funcionarios:
        nome = _chave(f.nome)
        if not any(nome == p or nome.startswith(p + ' ') for p in prefixos):
            continue
        if inicial and not any(s.startswith(inicial) for s in nome.split()[1:]):
            continue
        saida.append(f)
    return saida


class Resgates:
    def __init__(self, clientes, banco, loja_por_id):
        self.loja_por_id = loja_por_id
        self.funcionarios = [f for f in banco.funcionarios if f.perfil in PERFIS_DE_LOJA]
        self.clientes = [c for c in clientes if c.get('Nome')]
        # Dias com compra de cada cliente em cada loja (compras e vendas do banco).
        self.compras_do_cpf = {}
        for ref, loja_id, quando in ([(c.cliente_ref, c.loja_id, c.quando) for c in banco.compras.values()]
                                     + [(v.cliente_ref, v.loja_id, v.quando) for v in banco.vendas]):
            c = r.digitos(ref)
            if r.cpf_valido(c):
                self.compras_do_cpf.setdefault(c, set()).add((loja_por_id.get(loja_id), r.dia(quando.astimezone(r.SP))))
        # Quem registrou venda em cada loja e dia (apelido do PDV).
        self.vendedores_do_dia = {}
        for v in banco.vendas:
            if v.vendedor:
                chave = (loja_por_id.get(v.loja_id), r.dia(v.quando.astimezone(r.SP)))
                self.vendedores_do_dia.setdefault(chave, set()).add(v.vendedor)
        self.primeira_venda = min((v.quando for v in banco.vendas), default=None)

    def loja_do(self, f):
        return self.loja_por_id.get(f.loja_id)

    # --- cliente -------------------------------------------------------------------------------

    def cliente(self, valor, loja, dia):
        """(cpf, nota) do resgate; (None, motivo) quando não dá para saber quem é."""
        c = r.cpf(valor)
        if c and r.cpf_valido(c):
            return c, None
        nome = r.minusculo(valor)
        if not nome:
            return None, 'resgate sem cliente'
        chave = _chave(nome)
        if ' ' in chave:
            mesmos = [x for x in self.clientes if _chave(x['Nome']) == chave]
        else:
            mesmos = [x for x in self.clientes if _chave(x['Nome']).split()[0] == chave]
        if len(mesmos) == 1:
            x = mesmos[0]
            return x['cpf'], f'cpf atribuído pelo nome "{nome}" ({x["Nome"]}): único cliente com esse nome'
        perto = {dia + timedelta(days=d) for d in (-1, 0, 1)}
        com_compra = [x for x in mesmos
                      if any(lj == loja and d in perto for lj, d in self.compras_do_cpf.get(x['cpf'], ()))]
        if len(com_compra) == 1:
            x = com_compra[0]
            return x['cpf'], (f'cpf atribuído pelo nome "{nome}" ({x["Nome"]}): entre {len(mesmos)} clientes chamados '
                              f'"{nome}", o único com compra na loja {loja} no mesmo dia (±1)')
        if not mesmos:
            return None, f'nenhum cliente chamado "{nome}"'
        return None, f'{len(mesmos)} clientes chamados "{nome}" e nenhum ou mais de um com compra na loja {loja} no dia'

    # --- atendente -----------------------------------------------------------------------------

    def atendente(self, valor, loja, dia):
        """(atendente, nota). Sem certeza, o apelido fica como foi digitado."""
        apelido = r.minusculo(valor)
        if not apelido:
            return None, None
        if apelido == 'gerente':
            gerentes = [f for f in self.funcionarios if f.perfil == 'gerente' and self.loja_do(f) == loja]
            if len(gerentes) == 1:
                return gerentes[0].nome, None
            return apelido, f'atendente não identificado com certeza: "{apelido}" sem gerente cadastrado na loja {loja}'
        todos = candidatos(apelido, self.funcionarios)
        nomes = [f.nome for f in todos]
        da_loja = [f for f in todos if self.loja_do(f) == loja]
        if len(da_loja) == 1:
            return da_loja[0].nome, None
        if not todos:
            return apelido, f'atendente não identificado com certeza: "{apelido}" não é apelido de nenhum funcionário'
        if not da_loja:
            if len(todos) == 1:
                return apelido, (f'atendente não identificado com certeza: "{apelido}" só existe como apelido de '
                                 f'{nomes[0]}, que é de outra loja (provável cobertura) — conferir')
            return apelido, (f'atendente não identificado com certeza: "{apelido}" fora da loja dele(a): '
                             f'pode ser {r.lista_ou(nomes)}')
        # Mais de um funcionário da loja com esse apelido: vale quem registrou vendas na loja no dia.
        nomes = [f.nome for f in da_loja]
        if self.primeira_venda is None or dia < r.dia(self.primeira_venda.astimezone(r.SP)):
            ano = self.primeira_venda.year if self.primeira_venda else ''
            return apelido, (f'atendente não identificado com certeza: "{apelido}" pode ser {r.lista_ou(nomes)}; '
                             f'resgate anterior a {ano}, sem registro de vendas para desempatar')
        venderam = set()
        for vendedor in self.vendedores_do_dia.get((loja, dia), ()):
            quem = [f for f in candidatos(vendedor, self.funcionarios) if self.loja_do(f) == loja]
            if len(quem) == 1:
                venderam.add(quem[0].nome)
        venderam &= set(nomes)
        if len(venderam) == 1:
            (nome,) = venderam
            return nome, f'atendente "{apelido}" pode ser {r.lista_ou(nomes)}; só {nome} registrou vendas na loja nesse dia'
        return apelido, (f'atendente não identificado com certeza: "{apelido}" pode ser {r.lista_ou(nomes)}; '
                         'as vendas do dia não desempatam')


def desconto_acima_da_regra(dia, pontos, desconto):
    for inicio, por_100, descricao in REGRAS_DE_DESCONTO:
        if dia >= inicio:
            break
    pela_regra = pontos / 100 * por_100
    if desconto is None or desconto <= pela_regra:
        return None
    return (f'desconto acima da regra: dado {r.reais_br(desconto)}; pela regra {descricao} '
            f'(r$ {por_100} a cada 100 pontos) seria {r.reais_br(pela_regra)}; '
            f'diferença {r.reais_br(desconto - pela_regra)}')


def aba_resgates(linhas, clientes, banco, loja_por_id):
    """(cabeçalho, linhas, avisos). Resgates sem cliente identificável saem da aba e viram aviso."""
    rg = Resgates(clientes, banco, loja_por_id)
    saida, avisos = [], []
    for linha in linhas:
        dia = r.dia(linha.get('data'), DIA_DE_MES_ANO)
        loja = r.loja(linha.get('loja'))
        if dia is None:
            avisos.append(('Resgates', linha['_linha'], f'resgate removido: data ilegível {linha.get("data")!r}'))
            continue
        cpf, nota_cliente = rg.cliente(linha.get('cliente'), loja, dia)
        if cpf is None:
            avisos.append(('Resgates', linha['_linha'],
                           f'resgate removido: cliente {linha.get("cliente")!r} não identificado ({nota_cliente})'))
            continue
        atendente, nota_atendente = rg.atendente(linha.get('atendente'), loja, dia)
        pontos = r.pontos_da_planilha(linha.get('pontos usados'))
        desconto = r.reais(linha.get('desconto R$'))
        notas = [nota_cliente, nota_atendente, desconto_acima_da_regra(dia, pontos, desconto)]
        saida.append({
            'data': datetime(dia.year, dia.month, dia.day, tzinfo=r.SP).isoformat(),
            'cliente': cpf,
            'pontos usados': pontos,
            'desconto R$': desconto,
            'loja': loja,
            'atendente': atendente,
            'observacao': '; '.join(n for n in notas if n) or None,
        })
    return COLUNAS, saida, avisos
