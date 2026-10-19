"""Regras de padronização do catálogo Vulto.

Tudo aqui foi definido com você ao longo do trabalho no catálogo; nenhuma regra nova.
"""
import re
import unicodedata

# ---------------------------------------------------------------- abas
# Ordem das coleções, da mais antiga para a mais nova (usada na regra do "último custo").
ORDEM_ABAS = ['PLANILHA ANTIGA NAO USAR', 'VERAO 25', 'inverno25', 'Atemporais', 'Verão 26', 'INVERNO 26']
# A coluna OBS só é removida desta aba (nas outras ela é mantida se existir).
ABAS_SEM_OBS = {'inverno25'}
# Colunas extras que sempre saem do catálogo.
COLUNAS_REMOVIDAS = {'fornecedor', 'lancamento'}
# Cores de preenchimento que significam "descontinuada" (vermelho). Texto tachado também.
VERMELHOS = {'FFFF0000', 'FFC00000'}

# Nomes de cabeçalho aceitos para cada campo (sem acento, minúsculo).
CABECALHOS = {
    'sku': {'sku', 'cod', 'codigo'},
    'produto': {'produto', 'descricao', 'nome'},
    'categoria': {'categoria', 'cat', 'grupo'},
    'cor': {'cor'},
    'tam': {'tam', 'tamanho'},
    'preco': {'preco', 'preco venda', 'preco (r$)'},
    'custo': {'custo', 'custo unit', 'custo_medio'},
    'ean': {'ean', 'ean13'},
}


def eh_aba_antiga(nome):
    n = sem_acento(nome).lower()
    return 'antiga' in n or 'nao usar' in n


def colecao_da_aba(nome):
    """Nome da aba em minúsculas; 'inverno25' vira 'inverno 25'."""
    n = nome.strip().lower()
    return re.sub(r'([a-zçãõ])(\d)', r'\1 \2', n)


# ---------------------------------------------------------------- texto
def sem_acento(s):
    return ''.join(ch for ch in unicodedata.normalize('NFKD', str(s)) if not unicodedata.combining(ch))


def limpa(x):
    """Remove R$, espaços duplicados/extras e nbsp. Vazio vira None."""
    if isinstance(x, str):
        x = x.replace('\xa0', ' ').replace('R$', ' ')
        x = re.sub(r'\s+', ' ', x).strip()
        return x if x != '' else None
    return x


# ---------------------------------------------------------------- cores
# Cor base (define o código de 3 letras do SKU). Areia, café, lavanda e amarelo manteiga
# têm o código da cor base, mas continuam com nome próprio na coluna COR.
COLOR_SYN = {
    'BRANCO': ['branco', 'white', 'bco'],
    'OFF WHITE': ['off white', 'off-white', 'offwhite'],
    'BEGE': ['bege', 'beige', 'areia'],
    'AMARELO': ['amarelo', 'yellow', 'amarelo manteiga'],
    'CINZA MESCLA': ['cinza mescla', 'cz mescla', 'mescla', 'cinza'],
    'VERDE OLIVA': ['verde oliva', 'olive', 'vd oliva', 'oliva'],
    'AZUL MARINHO': ['azul marinho', 'navy', 'az marinho', 'marinho'],
    'PRETO': ['preto', 'black', 'pto'],
    'MARROM': ['marrom', 'brown', 'cafe'],
    'VINHO': ['vinho', 'bordo', 'burgundy'],
    'LILAS': ['lilas', 'lavanda'],
    'JEANS CLARO': ['jeans claro', 'light denim', 'jns claro'],
    'JEANS ESCURO': ['jeans escuro', 'dark denim', 'jns escuro'],
}
_COR_BASE = {x: k for k, v in COLOR_SYN.items() for x in v}
COD3 = {'AMARELO': 'AMA', 'AZUL MARINHO': 'AZM', 'BEGE': 'BEG', 'BRANCO': 'BRA', 'CINZA MESCLA': 'CIN',
        'JEANS CLARO': 'JCL', 'JEANS ESCURO': 'JES', 'LILAS': 'LIL', 'MARROM': 'MRR', 'OFF WHITE': 'OFF',
        'PRETO': 'PRE', 'VERDE OLIVA': 'OLI', 'VINHO': 'VIN'}
COD1 = {'A': 'AZUL MARINHO', 'B': 'BRANCO', 'C': 'CINZA MESCLA', 'E': 'JEANS ESCURO', 'G': 'BEGE', 'H': 'VINHO',
        'J': 'JEANS CLARO', 'L': 'LILAS', 'M': 'MARROM', 'O': 'OFF WHITE', 'P': 'PRETO', 'V': 'VERDE OLIVA',
        'Y': 'AMARELO'}
LETRA = {v: k for k, v in COD1.items()}
INV3 = {v: k for k, v in COD3.items()}

# Cor que aparece na coluna COR do catálogo (nome final). Grafias muito parecidas viram uma só,
# inglês vira português, tons realmente diferentes (areia, café, lavanda, amarelo manteiga) ficam separados.
MAPCOR = {
    'amarelo': 'amarelo', 'yellow': 'amarelo', 'amarelo manteiga': 'amarelo manteiga',
    'azul marinho': 'azul marinho', 'navy': 'azul marinho', 'az marinho': 'azul marinho', 'marinho': 'azul marinho',
    'bege': 'bege', 'beige': 'bege', 'areia': 'areia',
    'branco': 'branco', 'white': 'branco', 'bco': 'branco',
    'cinza mescla': 'cinza mescla', 'cz mescla': 'cinza mescla', 'mescla': 'cinza mescla', 'cinza': 'cinza mescla',
    'jeans claro': 'jeans claro', 'light denim': 'jeans claro', 'jns claro': 'jeans claro',
    'jeans escuro': 'jeans escuro', 'jns escuro': 'jeans escuro', 'dark denim': 'jeans escuro',
    'lilás': 'lilás', 'lilas': 'lilás', 'lavanda': 'lavanda',
    'marrom': 'marrom', 'brown': 'marrom', 'café': 'café', 'cafe': 'café',
    'off white': 'off white', 'off-white': 'off white', 'offwhite': 'off white',
    'preto': 'preto', 'black': 'preto', 'pto': 'preto',
    'verde oliva': 'verde oliva', 'vd oliva': 'verde oliva', 'olive': 'verde oliva', 'oliva': 'verde oliva',
    'vinho': 'vinho', 'bordô': 'vinho', 'bordo': 'vinho', 'burgundy': 'vinho',
}


def norm_cor_base(s):
    if s is None:
        return None
    return _COR_BASE.get(sem_acento(s).lower().strip())


def cor_catalogo(c):
    """Cor final da coluna COR. Devolve None se a grafia não tem regra (vai para os avisos)."""
    k = (limpa(c) or '').lower()
    return MAPCOR.get(k) if k else None


# ---------------------------------------------------------------- tamanho
SIZE_SET = ['PP', 'P', 'M', 'G', 'GG', 'U', '36', '38', '40', '42', '44', '46']
SIZE_SYN = {'S': 'P', 'L': 'G', 'XL': 'GG', 'UN': 'U', 'UNICO': 'U', 'TAM UNICO': 'U'}
TAMANHOS_FINAIS = {'PP', 'P', 'M', 'G', 'GG', 'U'}
NUM2L = {'38': 'P', '40': 'M', '42': 'G', '44': 'G', '46': 'GG'}


def norm_size(s):
    if s is None:
        return None
    t = sem_acento(s).upper().strip()
    if re.fullmatch(r'\d+\.0', t):
        t = t[:-2]
    return SIZE_SYN.get(t, t)


def tam_sku(t):
    """36 ou menos = PP, 38 = P, 40 = M, 42 e 44 = G, 46 = GG. Letras ficam como estão."""
    if t and t.isdigit():
        return 'PP' if int(t) <= 36 else NUM2L.get(t, t)
    return t


# ---------------------------------------------------------------- SKU
def parse_sku(s):
    """Devolve (formato, cat, num, cor_base, tamanho). Formatos: padrao, padrao_minusculo, extenso,
    curto_CD, curto_minusculo, modelo, vazio, invalido."""
    if s is None:
        return ('vazio', None, None, None, None)
    raw = str(s).strip()
    if raw == '' or raw.lower() == 'nan':
        return ('vazio', None, None, None, None)
    t = sem_acento(raw)
    m = re.fullmatch(r'(?i)vlt-([a-z]{3})-(\d{3})-([a-z]{3})-([a-z0-9]+)', t)
    if m:
        fmt = 'padrao' if raw == raw.upper() else 'padrao_minusculo'
        return (fmt, m.group(1).upper(), m.group(2), INV3.get(m.group(3).upper()), norm_size(m.group(4)))
    m = re.fullmatch(r'(?i)vlt[ _]([a-z]{3})[ _](\d{3})[ _](.+)', t)
    if m:
        rest = m.group(3).split()
        size = None
        if rest and norm_size(rest[-1]) in SIZE_SET and not (len(rest) >= 2 and norm_cor_base(' '.join(rest))):
            size = norm_size(rest[-1])
            rest = rest[:-1]
        return ('extenso', m.group(1).upper(), m.group(2), norm_cor_base(' '.join(rest)), size)
    m = re.fullmatch(r'([A-Z]{3})(\d{3})([A-Z])([A-Z0-9]+)', t.upper())
    if m:
        fmt = 'curto_CD' if raw == raw.upper() else 'curto_minusculo'
        return (fmt, m.group(1), m.group(2), COD1.get(m.group(3)), norm_size(m.group(4)))
    m = re.fullmatch(r'(?i)([a-z]{3})-?(\d{3})', t)
    if m:
        return ('modelo', m.group(1).upper(), m.group(2), None, None)
    return ('invalido', None, None, None, None)


# ---------------------------------------------------------------- dinheiro
def parse_money(x):
    if x is None:
        return (None, 'vazio')
    if isinstance(x, (int, float)):
        return (float(x), 'numero')
    s = str(x).strip()
    if s == '':
        return (None, 'vazio')
    s2 = s.replace('R$', '').strip()
    if re.fullmatch(r'-?\d+,\d+', s2):
        return (float(s2.replace(',', '.')), 'texto_virgula')
    if re.fullmatch(r'-?\d+\.\d+', s2):
        return (float(s2), 'texto_ponto')
    if re.fullmatch(r'-?\d+', s2):
        return (float(s2), 'texto_inteiro')
    if re.fullmatch(r'-?\d{1,3}(\.\d{3})+,\d+', s2):
        return (float(s2.replace('.', '').replace(',', '.')), 'texto_milhar_br')
    return (None, 'lixo:' + s)


def dinheiro(x):
    """-> ('XX.CC' ou None, aviso). O ponto vira vírgula só na hora de gravar a planilha."""
    x = limpa(x)
    if x is None:
        return None, 'vazio'
    v, _ = parse_money(x)
    if v is None:
        return None, f"era '{x}'"
    return f'{v:.2f}', ''


# ---------------------------------------------------------------- categoria
def _a(s):
    return sem_acento(s).lower().strip()


# Categorias em que o NOME DO PRODUTO decide (quando a categoria tinha duas opções).
GRUPOS = {
    'bermuda_short': ('Bermuda', {'bermuda/short', 'bermudas', 'shorts', 'bottoms > short', 'bermudas e shorts'}),
    'top_cropped': ('Top', {'top/cropped', 'tops', 'cropped', 'tops > cropped', 'tops e croppeds'}),
    'camiseta_regata': ('Camiseta', {'camiseta/regata', 'camisetas', 'camiseta', 'tops > camiseta', 'camiseta basica'}),
}
PERMIT = {'bermuda_short': {'Bermuda', 'Short'}, 'top_cropped': {'Top', 'Cropped'},
          'camiseta_regata': {'Camiseta', 'Regata'}}
FIXO = {
    'camisa': 'Camisa', 'camisas': 'Camisa', 'camisaria': 'Camisa', 'tops > camisa': 'Camisa',
    'calca': 'Calça', 'calcas': 'Calça', 'calca jeans': 'Calça', 'bottoms > calca': 'Calça',
    'moletom/hoodie': 'Moletom', 'moletons': 'Moletom', 'moletom': 'Moletom', 'tops > moletom': 'Moletom',
    'vestido': 'Vestido', 'vestidos': 'Vestido', 'vestidos midi': 'Vestido',
    'saia': 'Saia', 'saias': 'Saia', 'bottoms > saia': 'Saia',
    'jaqueta': 'Jaqueta', 'jaquetas': 'Jaqueta', 'casacos > jaqueta': 'Jaqueta', 'outerwear': 'Jaqueta',
    'trico': 'Tricô', 'tops > trico': 'Tricô', 'malharia': 'Tricô',
    'acessorio': 'Acessório', 'acessorios': 'Acessório', 'acessorios > bones': 'Acessório', 'bolsas': 'Acessório',
}


def tipo_produto(nome):
    n = _a(nome or '')
    if n.startswith('bermuda'):
        return 'Bermuda'
    if n.startswith('short'):
        return 'Short'
    if n.startswith('regata'):
        return 'Regata'
    if n.startswith('camiseta') or n.startswith('baby tee'):
        return 'Camiseta'
    if n.startswith('cropped'):
        return 'Cropped'
    if n.startswith('top ') or n.startswith('body'):
        return 'Top'
    return None


def categoria(cat, nome):
    """-> (categoria em minúsculas, mapeada?). Singular, sem subcategoria; o produto decide quando há duas opções."""
    k = _a(cat or '')
    for g, (dflt, ks) in GRUPOS.items():
        if k in ks:
            t = tipo_produto(nome)
            return (t if t in PERMIT[g] else dflt).lower(), True
    if k in FIXO:
        return FIXO[k].lower(), True
    return (cat or '').strip().lower(), False
