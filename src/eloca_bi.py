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

def fetch_bi_movimentacoes() -> list[dict]:
    """
    Retorna todos os registros de ctmequip (movimentações de equipamentos).
    Colunas: recnum, equipamento, contrato, envret, data, setor, numos,
             local, seq, quantidade, valor, horimetro, observacao
    """
    sql = """
        SELECT
            CONVERT(VARCHAR(20), recnum)     AS recnum,
            CONVERT(VARCHAR(20), equipamento) AS equipamento,
            CONVERT(VARCHAR(20), contrato)   AS contrato,
            CONVERT(VARCHAR(1),  envret)     AS envret,
            CONVERT(VARCHAR(10), data, 120)  AS data,
            ISNULL(CONVERT(VARCHAR(500), setor), '') AS setor,
            CONVERT(VARCHAR(20), numos)      AS numos,
            CONVERT(VARCHAR(10), seq)        AS seq
        FROM ctmequip
        ORDER BY recnum
    """
    logger.info("[BI] Buscando ctmequip (movimentações) ...")
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql)
        rows = cur.fetchall()
        result = [dict(r) for r in rows]
        logger.info("[BI] ctmequip: %d registros.", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar ctmequip: %s", e)
        raise
    finally:
        conn.close()


def fetch_bi_ctprod() -> list[dict]:
    """
    Retorna todos os registros de ctprod com descrição do produto (join).
    Colunas: recnum, contrato, produto, produto_descricao, setor,
             valor, valorunitario, seqequip
    """
    sql = """
        SELECT
            CONVERT(VARCHAR(20), cp.recnum)        AS recnum,
            CONVERT(VARCHAR(20), cp.contrato)      AS contrato,
            CONVERT(VARCHAR(20), cp.produto)       AS produto,
            ISNULL(CONVERT(VARCHAR(500), p.descricao), cp.produto) AS produto_descricao,
            ISNULL(CONVERT(VARCHAR(500), cp.setor), '') AS setor,
            CONVERT(VARCHAR(30), cp.valor)         AS valor,
            CONVERT(VARCHAR(30), cp.valorunitario) AS valorunitario
        FROM ctprod cp
        LEFT JOIN produtos p ON p.codigo = cp.produto
        ORDER BY cp.recnum
    """
    logger.info("[BI] Buscando ctprod ...")
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql)
        rows = cur.fetchall()
        result = [dict(r) for r in rows]
        logger.info("[BI] ctprod: %d registros.", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar ctprod: %s", e)
        raise
    finally:
        conn.close()


def fetch_bi_faturamento() -> list[dict]:
    """
    Retorna todos os registros de docrec com representante (join).
    Colunas: numfatura, numsequencia, contrato, codigocliente, cliente,
             valoremissao, dataemissao, datavencto, liquidado, tipodocumento,
             representante, representante_nome
    """
    sql = """
        SELECT
            CONVERT(VARCHAR(30), d.numfatura)    AS numfatura,
            CONVERT(VARCHAR(10), d.numsequencia) AS numsequencia,
            NULLIF(LTRIM(RTRIM(ISNULL(CONVERT(VARCHAR(20), d.contrato), ''))), '') AS contrato,
            CONVERT(VARCHAR(20), d.codigocliente) AS codigocliente,
            ISNULL(CONVERT(VARCHAR(200), d.cliente), '') AS cliente,
            CONVERT(VARCHAR(30), d.valoremissao) AS valoremissao,
            CONVERT(VARCHAR(10), d.dataemissao, 120) AS dataemissao,
            CONVERT(VARCHAR(10), d.datavencto,  120) AS datavencto,
            ISNULL(CONVERT(VARCHAR(1), d.liquidado), ' ') AS liquidado,
            ISNULL(CONVERT(VARCHAR(100), d.tipodocumento), '') AS tipodocumento,
            ISNULL(CONVERT(VARCHAR(20), c.representante), '') AS representante,
            ISNULL(CONVERT(VARCHAR(200), c.representante_nome), '') AS representante_nome
        FROM docrec d
        LEFT JOIN contract c ON c.codigo = d.contrato
        ORDER BY d.numfatura
    """
    logger.info("[BI] Buscando docrec (faturamento) ...")
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql)
        rows = cur.fetchall()
        result = [dict(r) for r in rows]
        logger.info("[BI] docrec: %d registros.", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar docrec: %s", e)
        raise
    finally:
        conn.close()


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
