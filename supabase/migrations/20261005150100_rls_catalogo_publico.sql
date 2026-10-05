-- Catálogo público e endurecimento das permissões do front.
--
-- Regra (CLAUDE.md, seção 2 e 6): o front lê o catálogo direto pelo Supabase, protegido por RLS.
-- Compra e ações sensíveis passam pelo FastAPI, que exige login. Nenhuma escrita é liberada aqui:
-- sem policy de INSERT/UPDATE/DELETE, o front não grava em nenhuma tabela.

-- Visitante (anon) e usuário logado veem lojas, produtos e variações ativos.
create policy "loja: leitura publica de lojas ativas"
  on public.loja for select
  to anon, authenticated
  using (ativa);

create policy "produto: leitura publica de produtos ativos"
  on public.produto for select
  to anon, authenticated
  using (ativo);

create policy "variacao_produto: leitura publica de variacoes ativas de produtos ativos"
  on public.variacao_produto for select
  to anon, authenticated
  using (
    ativa
    and exists (
      select 1 from public.produto p
      where p.id_produto = variacao_produto.id_produto
        and p.ativo
    )
  );

-- Só logado: dados de apoio do checkout e do acompanhamento do pedido.
create policy "metodo_pagamento: leitura por usuarios logados"
  on public.metodo_pagamento for select
  to authenticated
  using (ativo);

create policy "status_pedido: leitura por usuarios logados"
  on public.status_pedido for select
  to authenticated
  using (ativo);

-- Defesa em profundidade: o visitante só lê (e só o que as policies acima liberam).
-- TRUNCATE, REFERENCES e TRIGGER não passam pelo RLS, então saem de anon e authenticated.
revoke insert, update, delete, truncate, references, trigger
  on all tables in schema public from anon;
revoke truncate, references, trigger
  on all tables in schema public from authenticated;

-- O mesmo para tabelas criadas daqui em diante (o padrão do Supabase concede tudo).
alter default privileges for role postgres in schema public
  revoke insert, update, delete, truncate, references, trigger on tables from anon;
alter default privileges for role postgres in schema public
  revoke truncate, references, trigger on tables from authenticated;
