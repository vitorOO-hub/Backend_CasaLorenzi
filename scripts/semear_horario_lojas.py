"""Preenche `loja.horario_funcionamento` com horarios de referencia para a demo da Entrega 4.

Nao sao os horarios oficiais: sao o padrao de mercado para cada tipo de loja, para o assistente do
cliente e o site terem o que responder. O admin corrige pela tela Gestao > Lojas (com auditoria).

- Shopping (BarraShopping, Patio Batel, Shopping Eldorado): seg a sab 10h-22h, dom 14h-20h.
- Rua (Centro, Savassi, Pinheiros): seg a sex 10h-19h, sab 10h-17h, dom fechada.
- CD, e-commerce, app e as lojas "guarda-chuva" de cada marca: sem horario (nao atendem no balcao).

So preenche loja sem horario; `--sobrescrever` troca tambem o que ja foi cadastrado.

    PYTHONPATH=. python scripts/semear_horario_lojas.py              # simula
    PYTHONPATH=. python scripts/semear_horario_lojas.py --aplicar    # grava
"""

import argparse
import json

from sqlalchemy import text

from app.core.config import Settings
from app.core.db import abrir_conexao
from app.core.horario import HorarioFuncionamento


def _semana(seg_sex: tuple[str, str], sab: tuple[str, str] | None, dom: tuple[str, str] | None):
    turno = lambda t: {"abre": t[0], "fecha": t[1]} if t else None  # noqa: E731
    dias = {d: turno(seg_sex) for d in ("seg", "ter", "qua", "qui", "sex")}
    return HorarioFuncionamento.model_validate({**dias, "sab": turno(sab), "dom": turno(dom)})


SHOPPING = _semana(("10:00", "22:00"), ("10:00", "22:00"), ("14:00", "20:00"))
RUA = _semana(("10:00", "19:00"), ("10:00", "17:00"), None)

HORARIOS = {
    "LOJA-BARRA": SHOPPING,
    "LOJA-VULTO-BATEL": SHOPPING,
    "LOJA-VULTO-SHOPPING-ELDORADO": SHOPPING,
    "LOJA-CENTRO": RUA,
    "LOJA-SAVASSI": RUA,
    "LOJA-VULTO-PINHEIROS": RUA,
    "LOJA-VULTO-SAVASSI": RUA,
}

GRAVAR = text(
    """
    UPDATE loja
    SET horario_funcionamento = CAST(:horario AS jsonb), atualizada_em = now()
    WHERE codigo = :codigo AND (:sobrescrever OR horario_funcionamento IS NULL)
    """
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aplicar", action="store_true", help="grava (sem isso, desfaz no fim)")
    parser.add_argument("--sobrescrever", action="store_true", help="troca horario ja cadastrado")
    args = parser.parse_args()

    with abrir_conexao(Settings()) as conexao:
        for codigo, horario in HORARIOS.items():
            alteradas = conexao.execute(
                GRAVAR,
                {
                    "codigo": codigo,
                    "horario": json.dumps(horario.model_dump()),
                    "sobrescrever": args.sobrescrever,
                },
            ).rowcount
            situacao = "gravado" if alteradas else "mantido (ja tinha horario ou nao existe)"
            print(f"{codigo}: {situacao}")
        if args.aplicar:
            conexao.commit()
        else:
            conexao.rollback()
            print("(simulacao: nada foi gravado)")


if __name__ == "__main__":
    main()
