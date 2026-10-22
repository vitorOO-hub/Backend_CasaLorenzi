"""Padrao dos dados gravados no banco (o mesmo das funcoes SQL `texto_padrao` e `telefone_padrao`).

- Texto: minusculas, sem espaco nas pontas e com um espaco so entre as palavras.
- Telefone: so digitos, DDD + numero, sem o codigo do pais (55) nem o zero de operadora.
- CPF e outros codigos numericos: so digitos, guardados como texto (preserva o zero inicial).

Vale para os dados cadastrais (nomes, cidades, enderecos, produto). Codigos (SKU, numero do pedido,
protocolo), URLs e textos escritos pelas pessoas (mensagens, observacoes) ficam como vieram.
"""

import re

_ESPACOS = re.compile(r"\s+")
_NAO_DIGITO = re.compile(r"\D")


def texto_padrao(valor: str | None) -> str | None:
    """"  Fernanda   K. " -> "fernanda k.". Vazio vira None."""
    if valor is None:
        return None
    limpo = _ESPACOS.sub(" ", valor).strip().lower()
    return limpo or None


def so_digitos(valor: str | None) -> str | None:
    if valor is None:
        return None
    return _NAO_DIGITO.sub("", valor) or None


def telefone_padrao(valor: str | None) -> str | None:
    """"+55 (11) 99999-0001" -> "11999990001". Numero sem DDD fica so com os digitos que tem."""
    digitos = so_digitos(valor)
    if digitos is None:
        return None
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) in (11, 12) and digitos.startswith("0"):
        digitos = digitos[1:]
    return digitos
