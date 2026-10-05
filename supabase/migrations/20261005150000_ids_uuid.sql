-- Converte todas as chaves primárias e estrangeiras de public de bigint (identity) para uuid,
-- preservando os dados e os relacionamentos. Novas linhas recebem gen_random_uuid().
-- Nomes de constraints e índices são mantidos.
--
-- Deve rodar numa transação única (o Supabase CLI faz isso por arquivo): qualquer erro desfaz tudo.
-- As colunas de id passam a ficar no fim da tabela (o Postgres não reordena colunas).

-- 0. Pré-condição: aborta se o schema não for o esperado.
do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and column_name like 'id\_%'
      and data_type <> 'bigint'
  ) then
    raise exception 'Pré-condição falhou: há colunas id_* em public que não são bigint';
  end if;
end $$;

-- 1. Nova chave uuid em cada tabela (preenchida para as linhas existentes).
alter table public.loja                      add column id_loja_novo uuid not null default gen_random_uuid();
alter table public.tipo_usuario              add column id_tipo_usuario_novo uuid not null default gen_random_uuid();
alter table public.usuario                   add column id_usuario_novo uuid not null default gen_random_uuid();
alter table public.produto                   add column id_produto_novo uuid not null default gen_random_uuid();
alter table public.variacao_produto          add column id_variacao_novo uuid not null default gen_random_uuid();
alter table public.estoque                   add column id_estoque_novo uuid not null default gen_random_uuid();
alter table public.status_pedido             add column id_status_pedido_novo uuid not null default gen_random_uuid();
alter table public.pedido                    add column id_pedido_novo uuid not null default gen_random_uuid();
alter table public.item_pedido               add column id_item_pedido_novo uuid not null default gen_random_uuid();
alter table public.metodo_pagamento          add column id_metodo_pagamento_novo uuid not null default gen_random_uuid();
alter table public.status_pagamento          add column id_status_pagamento_novo uuid not null default gen_random_uuid();
alter table public.pagamento                 add column id_pagamento_novo uuid not null default gen_random_uuid();
alter table public.tipo_movimentacao_estoque add column id_tipo_movimentacao_estoque_novo uuid not null default gen_random_uuid();
alter table public.movimentacao_estoque      add column id_movimentacao_estoque_novo uuid not null default gen_random_uuid();

-- 2. Novas colunas de FK, preenchidas a partir da chave nova da tabela referenciada.
alter table public.usuario
  add column id_tipo_usuario_novo uuid,
  add column id_loja_novo uuid;
update public.usuario u set id_tipo_usuario_novo = t.id_tipo_usuario_novo
  from public.tipo_usuario t where t.id_tipo_usuario = u.id_tipo_usuario;
update public.usuario u set id_loja_novo = l.id_loja_novo
  from public.loja l where l.id_loja = u.id_loja;

alter table public.variacao_produto add column id_produto_novo uuid;
update public.variacao_produto v set id_produto_novo = p.id_produto_novo
  from public.produto p where p.id_produto = v.id_produto;

alter table public.estoque
  add column id_loja_novo uuid,
  add column id_variacao_novo uuid;
update public.estoque e set id_loja_novo = l.id_loja_novo
  from public.loja l where l.id_loja = e.id_loja;
update public.estoque e set id_variacao_novo = v.id_variacao_novo
  from public.variacao_produto v where v.id_variacao = e.id_variacao;

alter table public.pedido
  add column id_loja_novo uuid,
  add column id_cliente_novo uuid,
  add column id_usuario_responsavel_novo uuid,
  add column id_status_pedido_novo uuid;
update public.pedido p set id_loja_novo = l.id_loja_novo
  from public.loja l where l.id_loja = p.id_loja;
update public.pedido p set id_cliente_novo = u.id_usuario_novo
  from public.usuario u where u.id_usuario = p.id_cliente;
update public.pedido p set id_usuario_responsavel_novo = u.id_usuario_novo
  from public.usuario u where u.id_usuario = p.id_usuario_responsavel;
update public.pedido p set id_status_pedido_novo = s.id_status_pedido_novo
  from public.status_pedido s where s.id_status_pedido = p.id_status_pedido;

alter table public.item_pedido
  add column id_pedido_novo uuid,
  add column id_variacao_novo uuid;
update public.item_pedido i set id_pedido_novo = p.id_pedido_novo
  from public.pedido p where p.id_pedido = i.id_pedido;
update public.item_pedido i set id_variacao_novo = v.id_variacao_novo
  from public.variacao_produto v where v.id_variacao = i.id_variacao;

alter table public.pagamento
  add column id_pedido_novo uuid,
  add column id_metodo_pagamento_novo uuid,
  add column id_status_pagamento_novo uuid;
update public.pagamento g set id_pedido_novo = p.id_pedido_novo
  from public.pedido p where p.id_pedido = g.id_pedido;
update public.pagamento g set id_metodo_pagamento_novo = m.id_metodo_pagamento_novo
  from public.metodo_pagamento m where m.id_metodo_pagamento = g.id_metodo_pagamento;
update public.pagamento g set id_status_pagamento_novo = s.id_status_pagamento_novo
  from public.status_pagamento s where s.id_status_pagamento = g.id_status_pagamento;

alter table public.movimentacao_estoque
  add column id_loja_novo uuid,
  add column id_variacao_novo uuid,
  add column id_pedido_novo uuid,
  add column id_usuario_responsavel_novo uuid,
  add column id_tipo_movimentacao_estoque_novo uuid;
update public.movimentacao_estoque m set id_loja_novo = l.id_loja_novo
  from public.loja l where l.id_loja = m.id_loja;
update public.movimentacao_estoque m set id_variacao_novo = v.id_variacao_novo
  from public.variacao_produto v where v.id_variacao = m.id_variacao;
update public.movimentacao_estoque m set id_pedido_novo = p.id_pedido_novo
  from public.pedido p where p.id_pedido = m.id_pedido;
update public.movimentacao_estoque m set id_usuario_responsavel_novo = u.id_usuario_novo
  from public.usuario u where u.id_usuario = m.id_usuario_responsavel;
update public.movimentacao_estoque m set id_tipo_movimentacao_estoque_novo = t.id_tipo_movimentacao_estoque_novo
  from public.tipo_movimentacao_estoque t where t.id_tipo_movimentacao_estoque = m.id_tipo_movimentacao_estoque;

-- 3. Remove as FKs antigas (constraints, uniques compostos e índices nelas caem junto).
alter table public.usuario              drop column id_tipo_usuario, drop column id_loja;
alter table public.variacao_produto     drop column id_produto;
alter table public.estoque              drop column id_loja, drop column id_variacao;
alter table public.pedido               drop column id_loja, drop column id_cliente,
                                        drop column id_usuario_responsavel, drop column id_status_pedido;
alter table public.item_pedido          drop column id_pedido, drop column id_variacao;
alter table public.pagamento            drop column id_pedido, drop column id_metodo_pagamento,
                                        drop column id_status_pagamento;
alter table public.movimentacao_estoque drop column id_loja, drop column id_variacao, drop column id_pedido,
                                        drop column id_usuario_responsavel, drop column id_tipo_movimentacao_estoque;

-- 4. Remove as chaves primárias antigas (sem cascade: dependência inesperada aborta a migration).
alter table public.loja                      drop column id_loja;
alter table public.tipo_usuario              drop column id_tipo_usuario;
alter table public.usuario                   drop column id_usuario;
alter table public.produto                   drop column id_produto;
alter table public.variacao_produto          drop column id_variacao;
alter table public.estoque                   drop column id_estoque;
alter table public.status_pedido             drop column id_status_pedido;
alter table public.pedido                    drop column id_pedido;
alter table public.item_pedido               drop column id_item_pedido;
alter table public.metodo_pagamento          drop column id_metodo_pagamento;
alter table public.status_pagamento          drop column id_status_pagamento;
alter table public.pagamento                 drop column id_pagamento;
alter table public.tipo_movimentacao_estoque drop column id_tipo_movimentacao_estoque;
alter table public.movimentacao_estoque      drop column id_movimentacao_estoque;

-- 5. Devolve os nomes originais.
alter table public.loja                      rename column id_loja_novo to id_loja;
alter table public.tipo_usuario              rename column id_tipo_usuario_novo to id_tipo_usuario;
alter table public.usuario                   rename column id_usuario_novo to id_usuario;
alter table public.usuario                   rename column id_tipo_usuario_novo to id_tipo_usuario;
alter table public.usuario                   rename column id_loja_novo to id_loja;
alter table public.produto                   rename column id_produto_novo to id_produto;
alter table public.variacao_produto          rename column id_variacao_novo to id_variacao;
alter table public.variacao_produto          rename column id_produto_novo to id_produto;
alter table public.estoque                   rename column id_estoque_novo to id_estoque;
alter table public.estoque                   rename column id_loja_novo to id_loja;
alter table public.estoque                   rename column id_variacao_novo to id_variacao;
alter table public.status_pedido             rename column id_status_pedido_novo to id_status_pedido;
alter table public.pedido                    rename column id_pedido_novo to id_pedido;
alter table public.pedido                    rename column id_loja_novo to id_loja;
alter table public.pedido                    rename column id_cliente_novo to id_cliente;
alter table public.pedido                    rename column id_usuario_responsavel_novo to id_usuario_responsavel;
alter table public.pedido                    rename column id_status_pedido_novo to id_status_pedido;
alter table public.item_pedido               rename column id_item_pedido_novo to id_item_pedido;
alter table public.item_pedido               rename column id_pedido_novo to id_pedido;
alter table public.item_pedido               rename column id_variacao_novo to id_variacao;
alter table public.metodo_pagamento          rename column id_metodo_pagamento_novo to id_metodo_pagamento;
alter table public.status_pagamento          rename column id_status_pagamento_novo to id_status_pagamento;
alter table public.pagamento                 rename column id_pagamento_novo to id_pagamento;
alter table public.pagamento                 rename column id_pedido_novo to id_pedido;
alter table public.pagamento                 rename column id_metodo_pagamento_novo to id_metodo_pagamento;
alter table public.pagamento                 rename column id_status_pagamento_novo to id_status_pagamento;
alter table public.tipo_movimentacao_estoque rename column id_tipo_movimentacao_estoque_novo to id_tipo_movimentacao_estoque;
alter table public.movimentacao_estoque      rename column id_movimentacao_estoque_novo to id_movimentacao_estoque;
alter table public.movimentacao_estoque      rename column id_loja_novo to id_loja;
alter table public.movimentacao_estoque      rename column id_variacao_novo to id_variacao;
alter table public.movimentacao_estoque      rename column id_pedido_novo to id_pedido;
alter table public.movimentacao_estoque      rename column id_usuario_responsavel_novo to id_usuario_responsavel;
alter table public.movimentacao_estoque      rename column id_tipo_movimentacao_estoque_novo to id_tipo_movimentacao_estoque;

-- 6. Chaves primárias.
alter table public.loja                      add constraint pk_loja primary key (id_loja);
alter table public.tipo_usuario              add constraint pk_tipo_usuario primary key (id_tipo_usuario);
alter table public.usuario                   add constraint pk_usuario primary key (id_usuario);
alter table public.produto                   add constraint pk_produto primary key (id_produto);
alter table public.variacao_produto          add constraint pk_variacao_produto primary key (id_variacao);
alter table public.estoque                   add constraint pk_estoque primary key (id_estoque);
alter table public.status_pedido             add constraint pk_status_pedido primary key (id_status_pedido);
alter table public.pedido                    add constraint pk_pedido primary key (id_pedido);
alter table public.item_pedido               add constraint pk_item_pedido primary key (id_item_pedido);
alter table public.metodo_pagamento          add constraint pk_metodo_pagamento primary key (id_metodo_pagamento);
alter table public.status_pagamento          add constraint pk_status_pagamento primary key (id_status_pagamento);
alter table public.pagamento                 add constraint pk_pagamento primary key (id_pagamento);
alter table public.tipo_movimentacao_estoque add constraint pk_tipo_movimentacao_estoque primary key (id_tipo_movimentacao_estoque);
alter table public.movimentacao_estoque      add constraint pk_movimentacao_estoque primary key (id_movimentacao_estoque);

-- 7. Obrigatoriedade das FKs (as opcionais continuam aceitando nulo:
--    usuario.id_loja, pedido.id_usuario_responsavel, movimentacao_estoque.id_pedido
--    e movimentacao_estoque.id_usuario_responsavel).
alter table public.usuario              alter column id_tipo_usuario set not null;
alter table public.variacao_produto     alter column id_produto set not null;
alter table public.estoque              alter column id_loja set not null,
                                        alter column id_variacao set not null;
alter table public.pedido               alter column id_loja set not null,
                                        alter column id_cliente set not null,
                                        alter column id_status_pedido set not null;
alter table public.item_pedido          alter column id_pedido set not null,
                                        alter column id_variacao set not null;
alter table public.pagamento            alter column id_pedido set not null,
                                        alter column id_metodo_pagamento set not null,
                                        alter column id_status_pagamento set not null;
alter table public.movimentacao_estoque alter column id_loja set not null,
                                        alter column id_variacao set not null,
                                        alter column id_tipo_movimentacao_estoque set not null;

-- 8. Chaves estrangeiras (mesmos nomes e regras de antes).
alter table public.usuario
  add constraint fk_usuario_tipo_usuario foreign key (id_tipo_usuario)
    references public.tipo_usuario (id_tipo_usuario) on update cascade on delete restrict,
  add constraint fk_usuario_loja foreign key (id_loja)
    references public.loja (id_loja) on update cascade on delete restrict;
alter table public.variacao_produto
  add constraint fk_variacao_produto_produto foreign key (id_produto)
    references public.produto (id_produto) on update cascade on delete restrict;
alter table public.estoque
  add constraint fk_estoque_loja foreign key (id_loja)
    references public.loja (id_loja) on update cascade on delete restrict,
  add constraint fk_estoque_variacao_produto foreign key (id_variacao)
    references public.variacao_produto (id_variacao) on update cascade on delete restrict;
alter table public.pedido
  add constraint fk_pedido_loja foreign key (id_loja)
    references public.loja (id_loja) on update cascade on delete restrict,
  add constraint fk_pedido_cliente foreign key (id_cliente)
    references public.usuario (id_usuario) on update cascade on delete restrict,
  add constraint fk_pedido_usuario_responsavel foreign key (id_usuario_responsavel)
    references public.usuario (id_usuario) on update cascade on delete restrict,
  add constraint fk_pedido_status_pedido foreign key (id_status_pedido)
    references public.status_pedido (id_status_pedido) on update cascade on delete restrict;
alter table public.item_pedido
  add constraint fk_item_pedido_pedido foreign key (id_pedido)
    references public.pedido (id_pedido) on update cascade on delete restrict,
  add constraint fk_item_pedido_variacao_produto foreign key (id_variacao)
    references public.variacao_produto (id_variacao) on update cascade on delete restrict;
alter table public.pagamento
  add constraint fk_pagamento_pedido foreign key (id_pedido)
    references public.pedido (id_pedido) on update cascade on delete restrict,
  add constraint fk_pagamento_metodo_pagamento foreign key (id_metodo_pagamento)
    references public.metodo_pagamento (id_metodo_pagamento) on update cascade on delete restrict,
  add constraint fk_pagamento_status_pagamento foreign key (id_status_pagamento)
    references public.status_pagamento (id_status_pagamento) on update cascade on delete restrict;
alter table public.movimentacao_estoque
  add constraint fk_movimentacao_estoque_loja foreign key (id_loja)
    references public.loja (id_loja) on update cascade on delete restrict,
  add constraint fk_movimentacao_estoque_variacao_produto foreign key (id_variacao)
    references public.variacao_produto (id_variacao) on update cascade on delete restrict,
  add constraint fk_movimentacao_estoque_pedido foreign key (id_pedido)
    references public.pedido (id_pedido) on update cascade on delete restrict,
  add constraint fk_movimentacao_estoque_usuario_responsavel foreign key (id_usuario_responsavel)
    references public.usuario (id_usuario) on update cascade on delete restrict,
  add constraint fk_movimentacao_estoque_tipo_movimentacao foreign key (id_tipo_movimentacao_estoque)
    references public.tipo_movimentacao_estoque (id_tipo_movimentacao_estoque) on update cascade on delete restrict;

-- 9. Uniques compostos que envolviam ids.
alter table public.variacao_produto add constraint uq_variacao_produto_grade unique (id_produto, cor, tamanho);
alter table public.estoque          add constraint uq_estoque_loja_variacao unique (id_loja, id_variacao);
alter table public.item_pedido      add constraint uq_item_pedido_pedido_variacao unique (id_pedido, id_variacao);
alter table public.pagamento        add constraint uq_pagamento_pedido_tentativa unique (id_pedido, tentativa);

-- 10. Índices das FKs.
create index idx_usuario_id_loja on public.usuario (id_loja);
create index idx_usuario_id_tipo_usuario on public.usuario (id_tipo_usuario);
create index idx_variacao_produto_id_produto on public.variacao_produto (id_produto);
create index idx_estoque_id_variacao on public.estoque (id_variacao);
create index idx_pedido_id_loja on public.pedido (id_loja);
create index idx_pedido_id_cliente on public.pedido (id_cliente);
create index idx_pedido_id_usuario_responsavel on public.pedido (id_usuario_responsavel);
create index idx_pedido_id_status_pedido on public.pedido (id_status_pedido);
create index idx_item_pedido_id_variacao on public.item_pedido (id_variacao);
create index idx_pagamento_id_pedido on public.pagamento (id_pedido);
create index idx_pagamento_id_metodo_pagamento on public.pagamento (id_metodo_pagamento);
create index idx_pagamento_id_status_pagamento on public.pagamento (id_status_pagamento);
create index idx_movimentacao_estoque_id_loja on public.movimentacao_estoque (id_loja);
create index idx_movimentacao_estoque_id_variacao on public.movimentacao_estoque (id_variacao);
create index idx_movimentacao_estoque_id_pedido on public.movimentacao_estoque (id_pedido);
create index idx_movimentacao_estoque_id_usuario_responsavel on public.movimentacao_estoque (id_usuario_responsavel);
create index idx_movimentacao_estoque_id_tipo_movimentacao on public.movimentacao_estoque (id_tipo_movimentacao_estoque);

-- 11. Pós-condição: nenhuma coluna id_* ficou fora de uuid.
do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and column_name like 'id\_%'
      and data_type <> 'uuid'
  ) then
    raise exception 'Pós-condição falhou: ainda há colunas id_* que não são uuid';
  end if;
end $$;
