"""Grava em `usuario.aceita_mensagens` a coluna `aceita_msg` da planilha de clientes da Vulto.

Regra (decisao do time para a Entrega 4): sem informacao, o cliente aceita (`true`, o default da
coluna). So fica `false` quem a planilha marca como nao (`N`, `nao`, `0`) ou tem "nao ligar" na
observacao. Quem ja escolheu no proprio perfil (origem `cliente`) nao e alterado. Casa pelo CPF.

    PYTHONPATH=. python scripts/importar_aceita_mensagens.py planilha.xlsx            # simula
    PYTHONPATH=. python scripts/importar_aceita_mensagens.py planilha.xlsx --aplicar  # grava

A planilha tem dados pessoais: nao a coloque no repositorio.
"""

import argparse
import re
import unicodedata
from collections import Counter

import openpyxl
from sqlalchemy import text

from app.core.config import Settings
from app.core.db import abrir_conexao

ABA = "Clientes"
SIM = {"sim", "s", "1", "true", "yes"}
NAO = {"nao", "n", "0", "false", "no"}


def _normal(valor: object) -> str:
    if valor is None:
        return ""
    texto = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    return texto.strip().lower()


def cpf(valor: object) -> str | None:
    """So os numeros, com os zeros a esquerda que o Excel corta."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    if 9 <= len(digitos) <= 11:
        return digitos.zfill(11)
    return None


def aceita(valor: object, obs: object = None) -> bool | None:
    """True/False quando a planilha diz; None quando nao se sabe (fica o default, que e sim)."""
    if "nao ligar" in _normal(obs):
        return False
    s = _normal(valor)
    if s in NAO:
        return False
    if s in SIM:
        return True
    return None


def ler_planilha(caminho: str) -> dict[str, bool | None]:
    planilha = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    linhas = planilha[ABA].iter_rows(values_only=True)
    cabecalho = [_normal(c) for c in next(linhas)]
    i_cpf, i_aceita, i_obs = (cabecalho.index(c) for c in ("cpf", "aceita_msg", "obs"))
    escolhas: dict[str, bool | None] = {}
    for linha in linhas:
        documento = cpf(linha[i_cpf])
        if documento:
            escolhas[documento] = aceita(linha[i_aceita], linha[i_obs])
    return escolhas


ATUALIZAR = text(
    """
    UPDATE usuario u
    SET aceita_mensagens = :aceita, aceita_mensagens_origem = 'planilha_vulto',
        aceita_mensagens_em = now()
    FROM tipo_usuario t
    WHERE t.id_tipo_usuario = u.id_tipo_usuario AND t.codigo = 'cliente'
      AND u.documento = ANY(CAST(:documentos AS text[]))
      AND u.aceita_mensagens_origem <> 'cliente'
    """
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("planilha", help="clientes_fidelidade_FINAL_v3.xlsx")
    parser.add_argument("--aplicar", action="store_true", help="grava (sem isso, desfaz no fim)")
    args = parser.parse_args()

    escolhas = ler_planilha(args.planilha)
    contagem = Counter(
        {True: "sim", False: "nao", None: "sem informacao (fica sim)"}[v] for v in escolhas.values()
    )
    print(f"{len(escolhas)} CPFs na planilha: {dict(contagem)}")

    with abrir_conexao(Settings()) as conexao:
        alterados = 0
        for valor in (True, False):
            documentos = [d for d, v in escolhas.items() if v is valor]
            alterados += conexao.execute(
                ATUALIZAR, {"aceita": valor, "documentos": documentos}
            ).rowcount
        if args.aplicar:
            conexao.commit()
        else:
            conexao.rollback()
    print(
        f"{alterados} clientes atualizados"
        + ("" if args.aplicar else " (simulacao: nada foi gravado)")
    )


if __name__ == "__main__":
    main()
