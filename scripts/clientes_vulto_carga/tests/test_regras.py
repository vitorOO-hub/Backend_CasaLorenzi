from datetime import datetime, timedelta

from clientes_vulto import pontos
from clientes_vulto.regras import (
    SP, aceita_msg, categoria, completa_o_nome, cpf, cpf_valido, cpfs_a_um_digito, data_cadastro,
    dono_do_email, email, loja, obs, pontos_da_planilha, telefone,
)

# CPF válido gerado para os testes (não é de ninguém).
CPF = '52998224725'


def test_cpf_volta_os_zeros_e_confere_os_digitos():
    assert cpf('529.982.247-25') == CPF and cpf(' 529 982 247 25') == CPF and cpf('529.982.247.25') == CPF
    assert cpf(1234567890) == '01234567890'          # o Excel cortou o zero à esquerda
    assert cpf_valido(CPF) and not cpf_valido('52998224726') and not cpf_valido('11111111111')
    assert CPF in cpfs_a_um_digito('52998224726')     # um dígito trocado tem correção


def test_telefone_e_ddd_da_loja():
    assert telefone('+55 11 98765-4321', 'site') == ('11987654321', False)
    assert telefone('(31) 98765-4321', 'app') == ('31987654321', False)
    assert telefone('98765-4321', 'savassi') == ('31987654321', False)   # DDD da cidade da loja
    assert telefone('98765-4321', 'site') == ('987654321', True)         # site/app: sem DDD


def test_datas():
    assert data_cadastro('44351') == '2021-06-04T00:00:00-03:00'          # número de série do Excel
    assert data_cadastro('04/06/2021') == data_cadastro('2021-06-04 00:00:00') == '2021-06-04T00:00:00-03:00'
    assert data_cadastro('jun/21') == '2021-06-16T00:00:00-03:00'        # só mês/ano: dia 16


def test_campos_de_texto():
    assert email(' Ana.Lima@GMIAL.com ') == 'ana.lima@gmail.com' and email('nao tem') is None
    assert email('x@uol.con.br') == 'x@uol.com.br' and email('y@hotmail.con') == 'y@hotmail.com'
    assert loja('eldorado shop') == 'eldorado' and loja('CWB') == 'batel' and loja('bh') == 'savassi'
    assert loja('ecommerce') == 'site'
    assert obs('Não ligar') == 'não ligar' and obs('VIP') is None and obs('ver com gerente') is None
    assert pontos_da_planilha('1.234') == 1234 and pontos_da_planilha('980 pts') == 980
    assert pontos_da_planilha('1,2k') == 1200 and pontos_da_planilha(None) == 0


def test_aceita_msg_na_duvida_e_nao():
    assert aceita_msg('S') == aceita_msg('1') == aceita_msg('sim') == 'sim'
    assert aceita_msg('x') == aceita_msg(None) == aceita_msg('0') == 'não'
    assert aceita_msg('sim', obs='não ligar') == 'não'                    # LGPD


def test_nomes_e_emails():
    assert completa_o_nome('joão b. teixeira', 'joão bastos teixeira')
    assert not completa_o_nome('joão b. teixeira', 'joão souza teixeira')
    assert dono_do_email('marta.ramos01@icloud.com', ['pedro ramos', 'marta duarte ramos']) == 'marta duarte ramos'
    assert dono_do_email('x.ramos@icloud.com', ['pedro ramos', 'marta ramos']) is None


def test_categoria_pelos_pontos_do_ano():
    assert [categoria(p) for p in (0, 1999, 2000, 4999, 5000)] == ['bronze', 'bronze', 'prata', 'prata', 'ouro']


def test_pontos_vencem_em_365_dias_e_resgate_usa_os_mais_antigos():
    ref = datetime(2026, 10, 19, 23, 59, tzinfo=SP)
    velho, novo = ref - timedelta(days=400), ref - timedelta(days=30)
    # resgate consome o crédito antigo primeiro; o que sobra dele vence
    assert pontos.saldo([(velho, 1000), (novo, 500), (novo + timedelta(days=1), -300)], ref) == 500
    assert pontos.saldo([(velho, 1000)], ref) == 0
    assert pontos.saldo([(novo, 100), (novo, -400)], ref) == 0           # nunca negativo
