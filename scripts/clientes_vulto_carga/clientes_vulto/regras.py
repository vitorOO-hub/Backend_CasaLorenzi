"""Regras de padronização dos clientes do Vulto+: uma função por campo, sem leitura de arquivos.

Cada regra reproduz o tratamento feito à mão na planilha final padronizada; as decisões de
negócio estão anotadas onde aparecem.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

# Fuso de São Paulo, usado em todas as datas da planilha padronizada.
SP = timezone(timedelta(hours=-3))

# Datas só com mês e ano ("jun/21") viram o dia 16: a média dos dias do mês (decisão do time).
DIA_DE_MES_ANO = 16

MESES = {'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6,
         'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12}

# Nome da loja como aparece na planilha -> nome padronizado.
LOJAS = {
    'site': 'site', 'ecommerce': 'site', 'e-commerce': 'site', 'web': 'site',
    'app': 'app',
    'pinheiros': 'pinheiros',
    'eldorado': 'eldorado', 'eldorado shop': 'eldorado',
    'savassi': 'savassi', 'bh': 'savassi',
    'batel': 'batel', 'cwb': 'batel',
}

# DDD da cidade de cada loja física; site e app não têm cidade.
DDD_DA_LOJA = {'pinheiros': '11', 'eldorado': '11', 'savassi': '31', 'batel': '41'}

# Domínios de e-mail com erro de digitação -> domínio certo.
DOMINIOS_CORRIGIDOS = {'gmial.com': 'gmail.com', 'hotmail.con': 'hotmail.com', 'uol.con.br': 'uol.com.br'}

# Textos que aparecem no lugar do e-mail quando não há e-mail.
SEM_EMAIL = {'-', 'nao tem', 'não tem', 'sem email', 'sem e-mail', 'n/a'}

SIM = {'sim', 's', '1', 'true', 'yes'}

# Anotações internas vagas, sem ação para o cliente: a planilha final as descartou.
# As que levam informação ao atendimento ("não ligar", "aniversario em maio") ficam.
OBS_DESCARTADAS = {'trocou de cpf?', 'ver com gerente', 'cliente reclamou', 'cadastro refeito', 'vip'}

# Categoria pelos pontos acumulados no ano (regra da aba LEIA ISSO).
LIMITE_PRATA = 2000
LIMITE_OURO = 5000


def texto(v):
    """Texto sem espaços repetidos nas pontas e no meio; vazio vira None."""
    if v is None:
        return None
    s = re.sub(r'\s+', ' ', str(v)).strip()
    return s or None


def minusculo(v):
    s = texto(v)
    return s.lower() if s else None


def digitos(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r'\D', '', str(v))


def cpf(v):
    """Só os números, com os zeros à esquerda que o Excel corta (9 ou 10 dígitos voltam a 11)."""
    d = digitos(v)
    if 9 <= len(d) <= 11:
        return d.zfill(11)
    return d or None


def cpf_valido(c):
    if not c or len(c) != 11 or not c.isdigit() or len(set(c)) == 1:
        return False
    for n in (9, 10):
        soma = sum(int(c[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10) % 11 % 10 != int(c[n]):
            return False
    return True


def cpfs_a_um_digito(c):
    """Todos os CPFs válidos que diferem de `c` em exatamente um dígito (para corrigir erro de digitação)."""
    saida = []
    for i in range(11):
        for d in '0123456789':
            if d != c[i]:
                outro = c[:i] + d + c[i + 1:]
                if cpf_valido(outro):
                    saida.append(outro)
    return saida


def loja(v):
    s = minusculo(v)
    if not s:
        return None
    return LOJAS.get(s, s)


def telefone(v, loja_padronizada):
    """Só números, sem o +55. Sem DDD, usa o da cidade da loja física; site e app ficam sem DDD.

    Devolve (telefone, faltou_ddd).
    """
    d = digitos(v)
    if not d:
        return None, False
    if len(d) in (12, 13) and d.startswith('55'):
        d = d[2:]
    if len(d) in (8, 9):
        ddd = DDD_DA_LOJA.get(loja_padronizada)
        if ddd:
            return ddd + d, False
        return d, True
    return d, False


def email(v):
    s = minusculo(v)
    if not s or s in SEM_EMAIL or '@' not in s:
        return None
    usuario, dominio = s.rsplit('@', 1)
    return f'{usuario}@{DOMINIOS_CORRIGIDOS.get(dominio, dominio)}'


def data_cadastro(v):
    """Data de cadastro como instante ISO no fuso de São Paulo (AAAA-MM-DDT00:00:00-03:00)."""
    d = dia(v)
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=SP).isoformat()


def dia(v):
    """Lê as formas de data da planilha: data do Excel, número de série, AAAA-MM-DD, DD/MM/AAAA e mmm/aa."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = str(v).strip().lower()
    if not s:
        return None
    if re.fullmatch(r'\d{5}', s):
        return date(1899, 12, 30) + timedelta(days=int(s))
    for formato in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s, formato).date()
        except ValueError:
            pass
    m = re.fullmatch(r'([a-zç]{3})/(\d{2,4})', s)
    if m and m.group(1) in MESES:
        ano = int(m.group(2))
        return date(ano + 2000 if ano < 100 else ano, MESES[m.group(1)], DIA_DE_MES_ANO)
    return None


def pontos_da_planilha(v):
    """Pontos escritos de várias formas: 1234, '1.234', '1234 pts', '1,2k'. Vazio = 0."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(round(v))
    s = str(v).strip().lower().replace('pontos', '').replace('pts', '').strip()
    if not s:
        return 0
    if s.endswith('k'):
        return round(float(s[:-1].replace(',', '.')) * 1000)
    return round(float(s.replace('.', '').replace(',', '.')))


def aceita_msg(v, obs=None):
    """'sim' só quando a coluna diz sim (S, 1, sim) e a observação não pede para não ligar. LGPD: na dúvida, não."""
    if obs and 'não ligar' in obs:
        return 'não'
    s = minusculo(v)
    return 'sim' if s in SIM else 'não'


def categoria(pontos_no_ano):
    if pontos_no_ano >= LIMITE_OURO:
        return 'ouro'
    if pontos_no_ano >= LIMITE_PRATA:
        return 'prata'
    return 'bronze'


def obs(v):
    s = minusculo(v)
    return None if not s or s in OBS_DESCARTADAS else s


def telefone_de_contato(v):
    """Telefone escrito em compras (cliente_ref): só números, sem +55."""
    d = digitos(v)
    if len(d) in (12, 13) and d.startswith('55'):
        d = d[2:]
    return d if 8 <= len(d) <= 11 else None


def nome_abreviado(nome):
    """'joão b. teixeira' tem um sobrenome abreviado."""
    return bool(nome and re.search(r'\b\w\.(\s|$)', nome))


def completa_o_nome(abreviado, completo):
    """'joão b. teixeira' e 'joão bastos teixeira' são a mesma pessoa: mesmo primeiro e último nome
    e cada inicial abreviada bate com o nome do meio."""
    if not abreviado or not completo or nome_abreviado(completo):
        return False
    a, c = abreviado.split(), completo.split()
    if len(a) != len(c) or a[0] != c[0] or a[-1] != c[-1]:
        return False
    return all(x == y or (x.endswith('.') and y.startswith(x[:-1])) for x, y in zip(a[1:-1], c[1:-1]))


def sem_acento(s):
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()


def dono_do_email(email_, nomes):
    """Entre os nomes que usam o mesmo e-mail, o dono é quem tem o primeiro nome igual ao início
    do e-mail (marta.ramos01@... é de 'marta duarte ramos'). None se não der para saber."""
    inicio = sem_acento(email_.split('@')[0].split('.')[0])
    donos = [n for n in nomes if n and sem_acento(n.split()[0]) == inicio]
    return donos[0] if len(donos) == 1 else None


def dia_br(v):
    """'09/04/23' ou data do Excel -> '09/04/2023'."""
    d = dia(v)
    return d.strftime('%d/%m/%Y') if d else None
