"""Mascara de dados pessoais no que fica gravado (historico do chat e auditoria) e nos logs.

O vendedor recebe a resposta inteira na hora; o que vai para o banco guarda so o final do CPF e do
telefone e a primeira letra do e-mail. Assim o historico salvo e o log nunca tem esses dados em
texto puro.
"""

import re
from typing import Any

_EMAIL = re.compile(r"([\w.+-])[\w.+-]*@([\w-]+(?:\.[\w-]+)+)")
_CPF = re.compile(r"(?<![\d*])\d{3}\.\d{3}\.\d{3}-(\d{2})(?!\d)")
_TELEFONE = re.compile(r"(?<![\d*])(?:\(?\d{2}\)?\s?)?\d{4,5}-\d{2}(\d{2})(?!\d)")
# CPF ou telefone sem pontuacao (10 ou 11 digitos seguidos).
_DIGITOS = re.compile(r"(?<![\d*])\d{8,9}(\d{2})(?!\d)")


def mascarar_texto(texto: str) -> str:
    texto = _EMAIL.sub(lambda m: f"{m[1]}***@{m[2]}", texto)
    texto = _CPF.sub(lambda m: f"***.***.***-{m[1]}", texto)
    texto = _TELEFONE.sub(lambda m: f"(**) *****-**{m[1]}", texto)
    return _DIGITOS.sub(lambda m: f"*********{m[1]}", texto)


def mascarar(valor: Any) -> Any:
    """O mesmo, dentro de dicionarios e listas (argumentos e resultados de ferramenta)."""
    if isinstance(valor, str):
        return mascarar_texto(valor)
    if isinstance(valor, dict):
        return {k: mascarar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [mascarar(v) for v in valor]
    return valor
