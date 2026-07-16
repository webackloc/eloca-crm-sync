"""
eloca_bi.py — Leitura do banco BI SQL Server da ELOCA (AWS RDS)
Database: biweback
Tabelas: contract, ctmequip, ctprod, docpag, docrec, produtos

Atualizado diariamente pelo ELOCA (~lag de 24h).
"""

import logging
import os

import pymssql

logger = logging.getLogger(__name__)

BI_HOST     = os.getenv("BI_HOST",     "og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com")
BI_PORT     = int(os.getenv("BI_PORT", "1433"))
BI_DATABASE = os.getenv("BI_DATABASE", "biweback")
BI_USER     = os.getenv("BI_USER",     "weback")
BI_PASSWORD = os.getenv("BI_PASSWORD", "")


def _get_conn() -> pymssql.Connection:
    return pymssql.connect(
        server=BI_HOST,
        port=BI_PORT,
        user=BI_USER,
        password=BI_PASSWORD,
        database=BI_DATABASE,
        timeout=60,
        charset="UTF-8",
        appname="eloca-crm-sync",
    )


# ---------------------------------------------------------------------------
# Carteira de contratos
# ---------------------------------------------------------------------------

def fetch_carteira_contratos() -> list[dict]:
    """
    Retorna contratos ativos (situacao='3' = APROVADO) com nome do cliente.
    Um registro por contrato.

    Colunas retornadas:
      codigo, cliente, situacao, datavigini, datavigfim, cliente_nome
    """
    sql = """
        SELECT
            c.codigo,
            c.cliente,
            c.situacao,
            CONVERT(VARCHAR(10), c.datavigini, 120) AS datavigini,
            CONVERT(VARCHAR(10), c.datavigfim, 120) AS datavigfim,
            (
                SELECT TOP 1 d.cliente
                FROM docrec d
                WHERE d.codigocliente = c.cliente
                ORDER BY d.recnum DESC
            ) AS cliente_nome
        FROM contract c
        WHERE c.situacao = '3'
        ORDER BY c.codigo
    """
    logger.info("[BI] Buscando carteira de contratos (situacao=3) ...")
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql)
        rows = cur.fetchall()
        result = [dict(r) for r in rows]
        logger.info("[BI] Contratos ativos encontrados: %d", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar carteira de contratos: %s", e)
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Equipamentos ativos (para atualizar ativos.contrato / ativos.nome_fantasia)
# ---------------------------------------------------------------------------

def fetch_equipamentos_ativos() -> list[dict]:
    """
    Retorna equipamentos ativos:
      - Último movimento = 'E' (enviado ao cliente)
      - Contrato com situacao='3' (APROVADO)

    Usa Method 2: ROW_NUMBER() OVER (PARTITION BY equipamento ORDER BY data DESC, seq DESC)
    — mesmo método validado contra os 7.214 do ELOCA (diferença de ~36 = lag do BI).

    Colunas retornadas:
      equipamento, contrato, cliente (código), cliente_nome
    """
    sql = """
        WITH last_move AS (
            SELECT
                equipamento,
                contrato,
                envret,
                ROW_NUMBER() OVER (
                    PARTITION BY equipamento
                    ORDER BY data DESC, seq DESC
                ) AS rn
            FROM ctmequip
        )
        SELECT
            lm.equipamento,
            lm.contrato,
            c.cliente,
            (
                SELECT TOP 1 d.cliente
                FROM docrec d
                WHERE d.codigocliente = c.cliente
                ORDER BY d.recnum DESC
            ) AS cliente_nome
        FROM last_move lm
        JOIN contract c ON c.codigo = lm.contrato
        WHERE lm.rn = 1
          AND lm.envret = 'E'
          AND c.situacao = '3'
    """
    logger.info("[BI] Buscando equipamentos ativos ...")
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql)
        rows = cur.fetchall()
        result = [dict(r) for r in rows]
        logger.info("[BI] Equipamentos ativos encontrados: %d", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar equipamentos ativos: %s", e)
        raise
    finally:
        conn.close()
