"""Carga dos clientes Vulto+ padronizados no banco do sistema novo.

- Clientes -> `public.usuario` (tipo cliente, `origem_cadastro = 'vulto+'`), um por CPF (`documento`).
  `id_loja` é a loja de cadastro, procurada pelo nome na tabela `loja` (site = vulto ecommerce,
  app = vulto app). Sem nome: 'cliente vulto+ (nome a confirmar)'. Sem endereço: a migração
  20261021120000 deixa cliente importado do Vulto+ entrar sem endereço.
- Pontos -> `public.movimento_pontos`: o extrato com validade (cada crédito vence em 365 dias), já
  com o vencimento do que venceu até a data de referência. A soma do extrato é o saldo.
- Resgates -> `public.resgate_pontos`.

Pode ser repetida: atualiza os clientes importados que ainda não fizeram login e regrava o extrato
e os resgates de origem 'vulto+'. Nunca altera conta que não veio do Vulto+.
"""
import csv
import os
import re

from . import regras as r

ORIGEM = 'vulto+'
NOME_A_CONFIRMAR = 'cliente vulto+ (nome a confirmar)'

# loja_cadastro padronizada -> palavra que identifica a loja Vulto na tabela loja.
PALAVRA_DA_LOJA = {'site': 'ecommerce', 'app': 'app', 'pinheiros': 'pinheiros', 'eldorado': 'eldorado',
                   'savassi': 'savassi', 'batel': 'batel'}


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', r.sem_acento(s or '').lower())


def mapa_de_lojas(lojas):
    """{loja_cadastro: id_loja} a partir das linhas (id_loja, nome) da tabela loja, e os erros
    (loja sem correspondência ou com mais de uma)."""
    mapa, erros = {}, []
    for chave, palavra in PALAVRA_DA_LOJA.items():
        achadas = [(i, nome) for i, nome in lojas if _norm(nome).startswith('vulto') and palavra in _norm(nome)]
        if len(achadas) == 1:
            mapa[chave] = achadas[0][0]
        else:
            erros.append(f'loja "{chave}": {len(achadas)} lojas Vulto com "{palavra}" no nome na tabela loja '
                         f'({", ".join(n for _, n in achadas) or "nenhuma"})')
    return mapa, erros


def montar(res):
    """Linhas de usuario, movimento_pontos e resgate_pontos (chaveadas pelo CPF) e os erros de validação."""
    clientes, extrato, resgates, erros = [], [], [], []
    for c in res.abas['Clientes'][1]:
        clientes.append({
            'documento': c['cpf'],
            'nome': c['Nome'] or NOME_A_CONFIRMAR,
            'email': c['E-mail'],
            'telefone': c['Tel'],
            'criado_em': c['Data Cadastro'],
            'loja_cadastro': c['loja_cadastro'],
            'aceita_mensagem': c['aceita_msg'] == 'sim',
            'observacao': c['Obs'],
        })
        linhas = [x for x in res.extratos.get(c['cpf'], []) if x['pontos'] != 0]
        if sum(x['pontos'] for x in linhas) != (c['Pontos'] or 0):
            erros.append(f'cpf {c["cpf"]}: extrato soma {sum(x["pontos"] for x in linhas)}, saldo {c["Pontos"]}')
        extrato += [{'documento': c['cpf'], **x} for x in linhas]
    cpfs = {c['documento'] for c in clientes}
    for x in res.abas['Resgates'][1]:
        if x['cliente'] not in cpfs:
            erros.append(f'resgate de {x["data"][:10]}: cpf {x["cliente"]} não está na aba Clientes')
            continue
        resgates.append({'documento': x['cliente'], 'resgatado_em': x['data'], 'pontos': x['pontos usados'],
                         'desconto': x['desconto R$'], 'loja_cadastro': x['loja'], 'atendente': x['atendente'],
                         'observacao': x['observacao']})
    return clientes, extrato, resgates, erros


def gravar_csv(pasta, clientes, extrato, resgates, rel):
    os.makedirs(pasta, exist_ok=True)

    def w(nome, linhas, cab):
        with open(os.path.join(pasta, nome), 'w', newline='', encoding='utf-8') as f:
            wr = csv.DictWriter(f, fieldnames=cab, extrasaction='ignore')
            wr.writeheader()
            wr.writerows(linhas)

    w('usuario.csv', clientes, ['documento', 'nome', 'email', 'telefone', 'criado_em', 'loja_cadastro',
                                'aceita_mensagem', 'observacao'])
    w('movimento_pontos.csv', extrato, ['documento', 'tipo', 'pontos', 'ocorrido_em', 'vence_em', 'descricao'])
    w('resgate_pontos.csv', resgates, ['documento', 'resgatado_em', 'pontos', 'desconto', 'loja_cadastro',
                                       'atendente', 'observacao'])
    with open(os.path.join(pasta, 'relatorio_carga.csv'), 'w', newline='', encoding='utf-8') as f:
        wr = csv.writer(f)
        wr.writerow(['tipo', 'chave', 'detalhe'])
        wr.writerows(rel)


def conferir_no_banco(cur, clientes):
    """Lê o banco (sem gravar) e separa o que a carga faria com cada cliente.

    Devolve (mapa de lojas, erros, relatório, conflitos): conflito é CPF que já pertence a uma conta
    que não veio do Vulto+ (fica de fora); e-mail já usado por outra conta entra vazio."""
    cur.execute('SELECT id_loja, nome FROM public.loja')
    mapa, erros = mapa_de_lojas(cur.fetchall())
    cur.execute('SELECT documento, origem_cadastro, auth_user_id IS NOT NULL FROM public.usuario '
                'WHERE documento = ANY(%s)', ([c['documento'] for c in clientes],))
    existentes = {doc: (origem, com_login) for doc, origem, com_login in cur.fetchall()}
    cur.execute('SELECT lower(email), documento FROM public.usuario WHERE lower(email) = ANY(%s)',
                ([c['email'] for c in clientes if c['email']],))
    dono_do_email = dict(cur.fetchall())
    rel, conflitos = [], set()
    for c in clientes:
        doc = c['documento']
        if doc in existentes and existentes[doc][0] != ORIGEM:
            conflitos.add(doc)
            rel.append(('cpf já cadastrado fora do vulto+', doc, 'cliente e pontos ficam de fora; decidir caso a caso'))
            continue
        if c['email'] and dono_do_email.get(c['email'], doc) != doc:
            rel.append(('e-mail já usado por outra conta', doc, f'{c["email"]}: cliente entra sem e-mail'))
        if doc in existentes and existentes[doc][1]:
            rel.append(('cliente já fez login', doc, 'cadastro mantido; extrato e resgates regravados'))
    return mapa, erros, rel, conflitos


def aplicar(clientes, extrato, resgates, database_url):
    """Grava numa única transação (tudo ou nada). Devolve as contagens e o relatório."""
    import psycopg

    n = dict(cliente_novo=0, cliente_atualizado=0, cliente_fora=0, movimento=0, resgate=0)
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        mapa, erros, rel, conflitos = conferir_no_banco(cur, clientes)
        if erros:
            raise RuntimeError('; '.join(erros))
        cur.execute("SELECT id_tipo_usuario FROM public.tipo_usuario WHERE codigo = 'cliente'")
        (tipo_cliente,) = cur.fetchone()
        sem_email = {d for t, d, _ in rel if t == 'e-mail já usado por outra conta'}
        ids = {}
        for c in clientes:
            doc = c['documento']
            if doc in conflitos:
                n['cliente_fora'] += 1
                continue
            email = None if doc in sem_email else c['email']
            valores = (c['nome'], email, c['telefone'], mapa.get(c['loja_cadastro']), c['aceita_mensagem'],
                       c['observacao'])
            cur.execute('SELECT id_usuario FROM public.usuario WHERE documento = %s', (doc,))
            linha = cur.fetchone()
            if linha:
                # Só atualiza o cadastro de quem ainda não fez login: depois disso os dados são do cliente.
                cur.execute(
                    'UPDATE public.usuario SET nome = %s, email = %s, telefone = %s, id_loja = %s, '
                    'aceita_mensagem = %s, observacao = %s, atualizado_em = now() '
                    'WHERE id_usuario = %s AND auth_user_id IS NULL', (*valores, linha[0]))
                ids[doc] = linha[0]
                n['cliente_atualizado'] += 1
            else:
                cur.execute(
                    'INSERT INTO public.usuario (id_tipo_usuario, documento, nome, email, telefone, id_loja, '
                    'aceita_mensagem, observacao, origem_cadastro, criado_em) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, now())) RETURNING id_usuario',
                    (tipo_cliente, doc, *valores, ORIGEM, c['criado_em']))
                ids[doc] = cur.fetchone()[0]
                n['cliente_novo'] += 1
        todos = list(ids.values())
        cur.execute('DELETE FROM public.movimento_pontos WHERE origem = %s AND id_usuario = ANY(%s)', (ORIGEM, todos))
        cur.execute('DELETE FROM public.resgate_pontos WHERE origem = %s AND id_usuario = ANY(%s)', (ORIGEM, todos))
        linhas = [(ids[x['documento']], x['tipo'], x['pontos'], x['ocorrido_em'], x['vence_em'], x['descricao'], ORIGEM)
                  for x in extrato if x['documento'] in ids]
        cur.executemany('INSERT INTO public.movimento_pontos (id_usuario, tipo, pontos, ocorrido_em, vence_em, '
                        'descricao, origem) VALUES (%s, %s, %s, %s, %s, %s, %s)', linhas)
        n['movimento'] = len(linhas)
        linhas = [(ids[x['documento']], x['resgatado_em'], x['pontos'], x['desconto'], mapa.get(x['loja_cadastro']),
                   x['atendente'], x['observacao'], ORIGEM) for x in resgates if x['documento'] in ids]
        cur.executemany('INSERT INTO public.resgate_pontos (id_usuario, resgatado_em, pontos, desconto, id_loja, '
                        'atendente, observacao, origem) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', linhas)
        n['resgate'] = len(linhas)
    return n, rel
