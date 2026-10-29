# E-mails ao cliente pelo n8n

Três e-mails automáticos, enviados pelo Gmail da loja através de um fluxo do n8n que só recebe
webhooks. Quem decide quem recebe é o backend (`app/automacoes/emails.py`); o n8n monta a mensagem
(`montar_email.js`) e envia.

| E-mail | Quando sai | Quem chama o n8n |
|---|---|---|
| Resumo da compra (`pos_compra`) | logo depois de uma venda na loja ou de um pedido no site | a rota da venda, em segundo plano |
| Pontos a vencer (`pontos`) | lotes que vencem nos próximos 7 dias (`EMAILS_DIAS_AVISO_PONTOS`) | o disparo diário |
| Quase na próxima categoria (`categoria`) | faltam até 20% dos pontos da próxima categoria | o disparo diário |

O e-mail de pontos também mostra quanto falta para a próxima categoria e as vantagens dela; quem o
recebeu não ganha um segundo e-mail de categoria no mesmo ano.

## Como funciona

1. O backend manda um `POST` para `N8N_WEBHOOK_EMAILS` com o cabeçalho `X-Chave-Automacao` (o
   mesmo valor de `CHAVE_AUTOMACAO`) e o corpo do e-mail (`tipo`, `para`, dados do pedido ou dos
   pontos).
2. O nó **Webhook do backend** recusa (403) qualquer chamada sem a chave certa.
3. **Montar e-mail** monta assunto e HTML (textos do banco escapados).
4. **Enviar pelo Gmail** envia como "Casa Lorenzi".
5. **Responder ao backend** devolve `{"ok": true}`. Se algo falhar antes disso, o n8n responde erro
   e o backend registra a falha para tentar de novo.

Nunca em dobro: o resumo e a categoria ficam na tabela `aviso_cliente` (reservados antes de enviar,
`enviado` ou `falhou` depois); os pontos, em `aviso_pontos`, gravados só quando o n8n confirma. O
disparo diário reenvia os resumos que falharam nos últimos 3 dias (até 5 tentativas).

## Configurar (uma vez)

No n8n (`https://vitorjunior.app.n8n.cloud`), fluxo **Casa Lorenzi - e-mails ao cliente**:

1. Nó **Webhook do backend** → Credential → *Create new* (**Header Auth**): Name
   `X-Chave-Automacao`, Value = o valor de `CHAVE_AUTOMACAO` do backend.
2. Nó **Enviar pelo Gmail** → Credential → *Create new* (**Gmail OAuth2**) → *Sign in with Google*
   com o Gmail da loja.
3. **Publish** (ativa o fluxo). A URL de produção do webhook é
   `https://vitorjunior.app.n8n.cloud/webhook/casa-lorenzi-emails`.

No backend: `N8N_WEBHOOK_EMAILS` com essa URL (no Render já está em `render.yaml`) e
`CHAVE_AUTOMACAO`.

No GitHub (repositório do backend): segredo `CHAVE_AUTOMACAO` para o agendamento
`.github/workflows/avisos-diarios.yml` (todo dia às 9h de Brasília).

## Testar na mão

```bash
# Quem receberia hoje, sem enviar nada:
curl -X POST -H "X-Chave-Automacao: $CHAVE" "$API/api/v1/automacoes/disparar-emails?simular=true"
# Disparo de verdade:
curl -X POST -H "X-Chave-Automacao: $CHAVE" "$API/api/v1/automacoes/disparar-emails"
# Reenviar o resumo de uma compra (sai uma vez só):
curl -X POST -H "X-Chave-Automacao: $CHAVE" "$API/api/v1/automacoes/resumo-da-compra/<id_pedido>"
```

Mudou `montar_email.js`? Cole o conteúdo de novo no nó **Montar e-mail** (ou reimporte
`fluxo_emails.json` e refaça as duas credenciais).

## Relatório semanal (teste)

O arquivo `fluxo_relatorio_semanal.json` é um workflow separado do envio de e-mails a clientes.
Ele roda às sextas-feiras às 8h de São Paulo, busca o resumo da rede para o admin e depois busca
um resumo filtrado por loja para cada gerente. Durante os testes, ambos os tipos de relatório são
enviados para `2020.vitor.oliveira@gmail.com`; os assuntos começam com `TESTE`.

1. Importe `fluxo_relatorio_semanal.json` pelo menu de workflows do n8n.
2. Nos dois nós **Buscar resumo**, configure a credencial **Header Auth** com nome
   `X-Chave-Automacao` e o valor de `CHAVE_AUTOMACAO` configurado no backend.
3. Nos dois nós **Enviar e-mail**, selecione a credencial Gmail usada para enviar os e-mails Casa
   Lorenzi.
4. Execute manualmente e confira os e-mails. O fluxo vem desativado e não dispara até ser ativado.
5. Depois de validar, troque o destinatário temporário pela lista definitiva de admin/gerentes e
   ative o workflow.

O endpoint por loja precisa estar publicado no backend. A API usada pelo fluxo é
`https://backend-casalorenzi.onrender.com/api/v1/automacoes/resumo-semanal`; o relatório individual
usa `?id_loja=<UUID>` e não inclui pontos a vencer, que são um indicador da rede.

Os HTMLs dos relatórios ficam em `codigo_email_relatorio_admin.js` e
`codigo_email_relatorio_gerente.js`. Ao atualizar o workflow que já foi importado no n8n, copie o
conteúdo de cada arquivo para o nó **Preparar e-mail** correspondente e publique a revisão. O logo
é carregado do site Casa Lorenzi; se o cliente de e-mail bloquear imagens remotas, o texto alternativo
continua identificando a marca.
