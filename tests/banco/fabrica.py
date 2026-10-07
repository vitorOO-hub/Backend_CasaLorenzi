"""Fabrica de dados para os testes de banco. Roda como superusuario, antes de trocar de papel."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Usuario:
    id: UUID
    auth: UUID
    tipo: str
    loja: UUID | None


class Fabrica:
    def __init__(self, conn) -> None:
        self.conn = conn
        self._contador = 0

    def _proximo(self) -> int:
        self._contador += 1
        return self._contador

    def _um(self, comando: str, parametros: tuple = ()):
        return self.conn.execute(comando, parametros).fetchone()[0]

    def loja(self, *, ativa: bool = True) -> UUID:
        n = self._proximo()
        return self._um(
            "INSERT INTO loja (codigo, nome, ativa) VALUES (%s, %s, %s) RETURNING id_loja",
            (f"L{n}", f"Loja {n}", ativa),
        )

    def usuario(self, tipo: str, *, loja: UUID | None = None, ativo: bool = True) -> Usuario:
        n = self._proximo()
        auth = uuid4()
        id_usuario = self._um(
            """
            INSERT INTO usuario (id_tipo_usuario, id_loja, auth_user_id, nome, email, ativo)
            VALUES (
                (SELECT id_tipo_usuario FROM tipo_usuario WHERE codigo = %s),
                %s, %s, %s, %s, %s
            )
            RETURNING id_usuario
            """,
            (tipo, loja, auth, f"Usuario {n}", f"u{n}@teste.local", ativo),
        )
        return Usuario(id=id_usuario, auth=auth, tipo=tipo, loja=loja)

    def pedido(self, *, loja: UUID, cliente: Usuario) -> UUID:
        n = self._proximo()
        return self._um(
            """
            INSERT INTO pedido (numero_pedido, id_loja, id_cliente, id_status_pedido)
            VALUES (
                %s, %s, %s,
                (SELECT id_status_pedido FROM status_pedido WHERE codigo = 'criado')
            )
            RETURNING id_pedido
            """,
            (f"PD-{n}", loja, cliente.id),
        )

    def atendimento(
        self,
        *,
        cliente: Usuario,
        loja: UUID | None = None,
        pedido: UUID | None = None,
        status: str = "aberto",
        canal: str | None = None,
        categoria: str | None = None,
        prioridade: str | None = None,
        aberto_em: datetime | None = None,
        assunto: str | None = None,
    ) -> UUID:
        """Cria um chamado. Sem codigos, usa a primeira opcao (menor `ordem`) de cada tabela."""
        return self._um(
            """
            INSERT INTO atendimento (
                id_cliente, id_loja, id_pedido, id_canal_atendimento,
                id_categoria_atendimento, id_prioridade_atendimento, id_status_atendimento,
                aberto_em, assunto
            )
            VALUES (
                %(cliente)s, %(loja)s, %(pedido)s,
                (SELECT id_canal_atendimento FROM canal_atendimento
                 WHERE codigo = coalesce(%(canal)s, (
                     SELECT codigo FROM canal_atendimento ORDER BY ordem LIMIT 1))),
                (SELECT id_categoria_atendimento FROM categoria_atendimento
                 WHERE codigo = coalesce(%(categoria)s, (
                     SELECT codigo FROM categoria_atendimento ORDER BY ordem LIMIT 1))),
                (SELECT id_prioridade_atendimento FROM prioridade_atendimento
                 WHERE codigo = coalesce(%(prioridade)s, (
                     SELECT codigo FROM prioridade_atendimento ORDER BY ordem LIMIT 1))),
                (SELECT id_status_atendimento FROM status_atendimento WHERE codigo = %(status)s),
                coalesce(%(aberto_em)s, now()), %(assunto)s
            )
            RETURNING id_atendimento
            """,
            {
                "cliente": cliente.id,
                "loja": loja,
                "pedido": pedido,
                "status": status,
                "canal": canal,
                "categoria": categoria,
                "prioridade": prioridade,
                "aberto_em": aberto_em,
                "assunto": assunto,
            },
        )

    def mensagem(
        self,
        *,
        atendimento: UUID,
        remetente: Usuario,
        texto: str = "ola",
        enviada_em: datetime | None = None,
    ) -> UUID:
        return self._um(
            """
            INSERT INTO mensagem (id_atendimento, id_usuario_remetente, texto, enviada_em)
            VALUES (%s, %s, %s, coalesce(%s, now()))
            RETURNING id_mensagem
            """,
            (atendimento, remetente.id, texto, enviada_em),
        )

    def variacao(self) -> UUID:
        n = self._proximo()
        id_produto = self._um(
            "INSERT INTO produto (nome, preco_base) VALUES (%s, 10) RETURNING id_produto",
            (f"Produto {n}",),
        )
        return self._um(
            """
            INSERT INTO variacao_produto (id_produto, sku, cor, tamanho, preco_venda)
            VALUES (%s, %s, 'azul', 'M', 10)
            RETURNING id_variacao
            """,
            (id_produto, f"SKU-{n}"),
        )

    def estoque(self, *, loja: UUID, variacao: UUID | None = None, quantidade: int = 5) -> UUID:
        variacao = variacao or self.variacao()
        return self._um(
            """
            INSERT INTO estoque (id_loja, id_variacao, quantidade)
            VALUES (%s, %s, %s)
            RETURNING id_estoque
            """,
            (loja, variacao, quantidade),
        )

    def item_pedido(self, *, pedido: UUID, variacao: UUID | None = None) -> UUID:
        variacao = variacao or self.variacao()
        return self._um(
            """
            INSERT INTO item_pedido (id_pedido, id_variacao, quantidade, preco_unitario)
            VALUES (%s, %s, 1, 10)
            RETURNING id_item_pedido
            """,
            (pedido, variacao),
        )

    def pagamento(self, *, pedido: UUID, valor: int = 10) -> UUID:
        return self._um(
            """
            INSERT INTO pagamento (id_pedido, id_metodo_pagamento, id_status_pagamento, valor)
            VALUES (
                %s,
                (SELECT id_metodo_pagamento FROM metodo_pagamento WHERE codigo = 'pix'),
                (SELECT id_status_pagamento FROM status_pagamento WHERE codigo = 'pendente'),
                %s
            )
            RETURNING id_pagamento
            """,
            (pedido, valor),
        )

    def movimentacao(self, *, loja: UUID, variacao: UUID | None = None) -> UUID:
        variacao = variacao or self.variacao()
        return self._um(
            """
            INSERT INTO movimentacao_estoque (
                id_loja, id_variacao, id_tipo_movimentacao_estoque,
                quantidade, quantidade_anterior, quantidade_posterior
            )
            VALUES (
                %s, %s,
                (SELECT id_tipo_movimentacao_estoque FROM tipo_movimentacao_estoque
                 WHERE codigo = 'entrada'),
                1, 0, 1
            )
            RETURNING id_movimentacao_estoque
            """,
            (loja, variacao),
        )
