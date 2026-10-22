"""Importa atendimentos historicos, vinculando somente clientes por identificadores exatos."""

import argparse
import csv
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid5

from dotenv import load_dotenv

from scripts.vulto_integracao.importador import (
    ImportacaoVultoError,
    validar_dsn_producao_supabase,
)

NAMESPACE_ATENDIMENTOS = UUID("b2495271-ae9a-4d83-9abd-98b163bb61dc")
ARQUIVO_PADRAO = Path.home() / "Downloads" / "atendimentos_FINAL_padronizado.csv"
CANAL_ORIGEM = {"whatsapp": "whatsapp", "e-mail": "email", "instagram": "instagram"}
STATUS_ORIGEM = {
    "aberto": "aberto",
    "em andamento": "em_andamento",
    "aguardando cliente": "aguardando_cliente",
    "resolvido": "resolvido",
}


def normalizar_texto(valor: str | None) -> str:
    texto = unicodedata.normalize("NFKD", (valor or "").strip().casefold())
    return "".join(caractere for caractere in texto if not unicodedata.combining(caractere))


def digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def telefone_nacional(valor: str | None) -> str:
    numero = digitos(valor)
    if numero.startswith("55") and len(numero) in (12, 13):
        numero = numero[2:]
    return numero if len(numero) in (10, 11) else ""


def categoria_origem(tags: str | None) -> str:
    tags_normalizadas = normalizar_texto(tags).replace("\ufffd", "")
    if "entrega" in tags_normalizadas or "atraso" in tags_normalizadas:
        return "entrega"
    if "pagamento" in tags_normalizadas or "financeiro" in tags_normalizadas:
        return "pagamento"
    if "troca" in tags_normalizadas or "tamanho" in tags_normalizadas:
        return "troca_devolucao"
    if tags_normalizadas.startswith(("pre", "pr")) and "venda" in tags_normalizadas:
        return "produto"
    return "outro"


def carregar_csv(caminho: Path) -> list[dict[str, str]]:
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        registros = list(csv.DictReader(arquivo, delimiter=";"))
    ids = [registro.get("id", "").strip() for registro in registros]
    if not registros or any(not identificador for identificador in ids):
        raise ImportacaoVultoError("CSV vazio ou com ID de origem em branco")
    if len(ids) != len(set(ids)):
        raise ImportacaoVultoError("CSV contem IDs de origem repetidos")
    obrigatorias = {"data_hora", "canal", "assunto", "mensagem", "status"}
    if not obrigatorias.issubset(registros[0]):
        raise ImportacaoVultoError("CSV nao contem todas as colunas obrigatorias")
    return registros


def resolver_clientes(conexao, registros: list[dict[str, str]]) -> dict[str, str]:
    with conexao.cursor() as cursor:
        cursor.execute(
            """
            SELECT u.id_usuario, u.documento, u.email, u.telefone
            FROM public.usuario u
            JOIN public.tipo_usuario t USING (id_tipo_usuario)
            WHERE t.codigo = 'cliente'
            """
        )
        usuarios = cursor.fetchall()

    por_cpf: dict[str, set[str]] = {}
    por_email: dict[str, set[str]] = {}
    por_telefone: dict[str, set[str]] = {}
    for id_usuario, documento, email, telefone in usuarios:
        cpf = digitos(documento)
        endereco = normalizar_texto(email)
        numero = telefone_nacional(telefone)
        if cpf:
            por_cpf.setdefault(cpf, set()).add(str(id_usuario))
        if endereco:
            por_email.setdefault(endereco, set()).add(str(id_usuario))
        if numero:
            por_telefone.setdefault(numero, set()).add(str(id_usuario))

    resolvidos: dict[str, str] = {}
    for registro in registros:
        cpf = digitos(registro.get("cpf_cliente"))
        candidatos = por_cpf.get(cpf, set()) if cpf else set()
        if not cpf:
            contato = (registro.get("contato") or "").strip()
            if "@" in contato:
                candidatos |= por_email.get(normalizar_texto(contato), set())
            telefone = telefone_nacional(contato)
            if telefone:
                candidatos |= por_telefone.get(telefone, set())
        if len(candidatos) == 1:
            resolvidos[registro["id"].strip()] = next(iter(candidatos))
    return resolvidos


def carregar_referencias(conexao, *, criar_instagram: bool = False) -> dict[str, dict[str, str]]:
    referencias: dict[str, dict[str, str]] = {}
    with conexao.cursor() as cursor:
        if criar_instagram:
            cursor.execute(
                """
                INSERT INTO public.canal_atendimento (codigo, nome, descricao, ordem)
                VALUES ('instagram', 'Instagram', 'Atendimento iniciado pelo Instagram.', 6)
                ON CONFLICT (codigo) DO NOTHING
                """
            )
        for tabela in (
            "canal_atendimento",
            "categoria_atendimento",
            "prioridade_atendimento",
            "status_atendimento",
        ):
            cursor.execute(f"SELECT codigo, id_{tabela} FROM public.{tabela} WHERE ativo")
            referencias[tabela] = {
                codigo: str(identificador) for codigo, identificador in cursor.fetchall()
            }
    if not criar_instagram and "instagram" not in referencias["canal_atendimento"]:
        referencias["canal_atendimento"]["instagram"] = "previsao"
    return referencias


def classificar(
    registros: list[dict[str, str]],
    clientes: dict[str, str],
    referencias: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], Counter[str]]:
    prontos: list[dict[str, str]] = []
    pendencias: Counter[str] = Counter()
    for registro in registros:
        origem_id = registro["id"].strip()
        canal = CANAL_ORIGEM.get(normalizar_texto(registro.get("canal")))
        status = STATUS_ORIGEM.get(normalizar_texto(registro.get("status")))
        categoria = categoria_origem(registro.get("tags"))
        if origem_id not in clientes:
            pendencias["cliente_sem_correspondencia_exata"] += 1
        elif canal not in referencias["canal_atendimento"]:
            pendencias["canal_sem_mapeamento"] += 1
        elif status not in referencias["status_atendimento"]:
            pendencias["status_sem_mapeamento"] += 1
        elif categoria not in referencias["categoria_atendimento"]:
            pendencias["categoria_sem_mapeamento"] += 1
        elif not registro.get("mensagem", "").strip():
            pendencias["mensagem_vazia"] += 1
        else:
            prontos.append(registro)
    return prontos, pendencias


def importar(conexao, registros: list[dict[str, str]]) -> tuple[int, Counter[str]]:
    clientes = resolver_clientes(conexao, registros)
    referencias = carregar_referencias(conexao, criar_instagram=True)
    prontos, pendencias = classificar(registros, clientes, referencias)
    inseridos = 0
    with conexao.cursor() as cursor:
        for registro in prontos:
            origem_id = registro["id"].strip()
            id_atendimento = uuid5(NAMESPACE_ATENDIMENTOS, f"atendimento:{origem_id}")
            id_mensagem = uuid5(NAMESPACE_ATENDIMENTOS, f"mensagem:{origem_id}")
            canal = CANAL_ORIGEM[normalizar_texto(registro["canal"])]
            status = STATUS_ORIGEM[normalizar_texto(registro["status"])]
            categoria = categoria_origem(registro.get("tags"))
            aberto_em = datetime.fromisoformat(registro["data_hora"].strip())
            cursor.execute(
                """
                INSERT INTO public.atendimento (
                    id_atendimento, id_cliente, id_canal_atendimento,
                    id_categoria_atendimento, id_prioridade_atendimento,
                    id_status_atendimento, aberto_em, assunto
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_atendimento) DO NOTHING
                RETURNING id_atendimento
                """,
                (
                    id_atendimento,
                    clientes[origem_id],
                    referencias["canal_atendimento"][canal],
                    referencias["categoria_atendimento"][categoria],
                    referencias["prioridade_atendimento"]["media"],
                    referencias["status_atendimento"][status],
                    aberto_em,
                    registro["assunto"].strip() or None,
                ),
            )
            if cursor.fetchone() is None:
                continue
            cursor.execute(
                """
                INSERT INTO public.mensagem (
                    id_mensagem, id_atendimento, id_usuario_remetente, texto, enviada_em
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id_mensagem) DO NOTHING
                """,
                (
                    id_mensagem,
                    id_atendimento,
                    clientes[origem_id],
                    registro["mensagem"].strip(),
                    aberto_em,
                ),
            )
            # Historico da Vulto fica fora das filas (migration 20261023110000). A marca vem depois
            # da mensagem porque mensagem nova num atendimento marcado tira a marca.
            cursor.execute(
                "UPDATE public.atendimento SET historico_vulto = true WHERE id_atendimento = %s",
                (id_atendimento,),
            )
            inseridos += 1
    return inseridos, pendencias


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=ARQUIVO_PADRAO)
    parser.add_argument("--aplicar-producao", action="store_true")
    parser.add_argument("--confirmar-producao", action="store_true")
    args = parser.parse_args()
    if not args.csv.is_file():
        parser.error(f"CSV nao encontrado: {args.csv}")
    if args.aplicar_producao != args.confirmar_producao:
        parser.error("para gravar, informe --aplicar-producao --confirmar-producao juntos")

    for raiz in Path(__file__).resolve().parents:
        arquivo_env = raiz / ".env"
        if arquivo_env.is_file():
            load_dotenv(arquivo_env)
            break
    dsn = os.environ.get("DATABASE_URL", "")
    try:
        validar_dsn_producao_supabase(dsn)
        import psycopg

        registros = carregar_csv(args.csv)
        if args.aplicar_producao:
            validar_dsn_producao_supabase(dsn)
        opcoes_conexao = (
            {} if args.aplicar_producao else {"options": "-c default_transaction_read_only=on"}
        )
        with psycopg.connect(dsn, autocommit=False, **opcoes_conexao) as conexao:
            clientes = resolver_clientes(conexao, registros)
            referencias = carregar_referencias(conexao)
            prontos, pendencias = classificar(registros, clientes, referencias)
            print(f"Atendimentos no arquivo: {len(registros)}")
            print(f"Com cliente vinculado por correspondencia exata: {len(prontos)}")
            print(f"Pendentes sem cliente/mapeamento seguro: {sum(pendencias.values())}")
            for motivo, quantidade in sorted(pendencias.items()):
                print(f"  {motivo}: {quantidade}")
            print("Pedido e responsavel: sem correspondencia exata; serao mantidos nulos.")
            print("Prioridade ausente na origem: sera usada media.")
            if not args.aplicar_producao:
                conexao.rollback()
                print("Previa somente; nenhum dado gravado.")
                return 0
            conexao.rollback()
        with psycopg.connect(dsn, autocommit=False) as conexao:
            inseridos, pendencias = importar(conexao, registros)
            conexao.commit()
        print(f"Atendimentos importados: {inseridos}")
        print(f"Registros mantidos fora da tabela atendimento: {sum(pendencias.values())}")
        return 0
    except (ImportacaoVultoError, OSError, ValueError) as erro:
        parser.error(str(erro))
    except ImportError as erro:
        parser.error("instale psycopg[binary] antes da importacao")
        raise erro
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
