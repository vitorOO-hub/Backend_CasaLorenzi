from catalogo_vulto.regras import (categoria, colecao_da_aba, cor_catalogo, dinheiro, norm_size, parse_sku, tam_sku)


def test_tamanho():
    assert [tam_sku(t) for t in ('36', '38', '40', '42', '44', '46')] == ['PP', 'P', 'M', 'G', 'G', 'GG']
    assert tam_sku('M') == 'M' and norm_size('un') == 'U'


def test_cor():
    assert cor_catalogo('vd oliva') == 'verde oliva' and cor_catalogo('Olive') == 'verde oliva'
    assert cor_catalogo('Brown') == 'marrom' and cor_catalogo('Bordô') == 'vinho'
    assert cor_catalogo('Areia') == 'areia' and cor_catalogo('BEGE') == 'bege'      # tons diferentes continuam separados
    assert cor_catalogo('turquesa') is None                                         # sem regra: vai para os avisos


def test_categoria():
    assert categoria('moletom/hoodie', 'Moletom Zíper Fleece') == ('moletom', True)
    assert categoria('Tops > Moletom', 'Moletom Canguru Fleece') == ('moletom', True)
    assert categoria('BERMUDA/SHORT', 'Short Jeans Clássica') == ('short', True)
    assert categoria('Bermudas', 'Bermuda Cargo') == ('bermuda', True)
    assert categoria('Camiseta/Regata', 'Regata Canelada') == ('regata', True)
    assert categoria('Bolsas', 'Ecobag') == ('acessório', True)
    assert categoria('Malharia', 'Suéter') == ('tricô', True)
    assert categoria('Pijama', 'x')[1] is False


def test_sku():
    assert parse_sku('vlt cam 012 verde oliva p') == ('extenso', 'CAM', '012', 'VERDE OLIVA', 'P')
    assert parse_sku('CAL001V36')[:4] == ('curto_CD', 'CAL', '001', 'VERDE OLIVA')
    assert parse_sku('VLT-CAL-001-OLI-38')[3] == 'VERDE OLIVA'
    assert parse_sku('COLEÇÃO INVERNO 2025')[0] == 'invalido'


def test_dinheiro_e_colecao():
    assert dinheiro('R$ 129,90') == ('129.90', '') and dinheiro(149.9) == ('149.90', '')
    assert dinheiro(None)[0] is None
    assert colecao_da_aba('inverno25') == 'inverno 25' and colecao_da_aba('Verão 26') == 'verão 26'


def test_ean13():
    from catalogo_vulto.carga import ean13_valido
    assert ean13_valido('7897969295881')
    assert not ean13_valido('7896883000000')   # cortado pelo Excel
    assert not ean13_valido('789')
    assert not ean13_valido(None)
