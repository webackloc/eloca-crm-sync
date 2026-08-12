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
        result = [{k: float(v) if hasattr(v, "__round__") and not isinstance(v, int) else v for k, v in dict(r).items()} for r in rows]
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

def fetch_bi_movimentacoes(ultimo_recnum: int = 0) -> list[dict]:
    """
    Retorna movimentações de equipamentos (ctmequip) — sync incremental.

    Se ultimo_recnum > 0: busca apenas registros novos (recnum > ultimo_recnum).
    Se ultimo_recnum == 0: full sync (primeira execução).

    Colunas: recnum, equipamento, contrato, envret, data, setor, numos, seq
    """
    sql = """
        SELECT
            CONVERT(VARCHAR(20), recnum)      AS recnum,
            CONVERT(VARCHAR(20), equipamento) AS equipamento,
            CONVERT(VARCHAR(20), contrato)    AS contrato,
            CONVERT(VARCHAR(1),  envret)      AS envret,
            CONVERT(VARCHAR(10), data, 120)   AS data,
            ISNULL(CONVERT(VARCHAR(500), setor), '') AS setor,
            CONVERT(VARCHAR(20), numos)       AS numos,
            CONVERT(VARCHAR(10), seq)         AS seq
        FROM ctmequip
        WHERE recnum > %(ultimo_recnum)s
        ORDER BY recnum
    """
    modo = f"incremental (recnum > {ultimo_recnum})" if ultimo_recnum else "full sync"
    logger.info("[BI] Buscando ctmequip (%s) ...", modo)
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql, {"ultimo_recnum": ultimo_recnum})
        rows = cur.fetchall()
        result = [{k: float(v) if hasattr(v, "__round__") and not isinstance(v, int) else v for k, v in dict(r).items()} for r in rows]
        logger.info("[BI] ctmequip: %d registros novos.", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar ctmequip: %s", e)
        raise
    finally:
        conn.close()


def fetch_bi_ctprod(ultimo_recnum: int = 0) -> list[dict]:
    """
    Retorna registros de ctprod — sync incremental por recnum.

    Se ultimo_recnum > 0: busca apenas registros novos.
    Se ultimo_recnum == 0: full sync (primeira execução).

    Colunas: recnum, contrato, produto, produto_descricao, setor, valor, valorunitario
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
        WHERE cp.recnum > %(ultimo_recnum)s
        ORDER BY cp.recnum
    """
    modo = f"incremental (recnum > {ultimo_recnum})" if ultimo_recnum else "full sync"
    logger.info("[BI] Buscando ctprod (%s) ...", modo)
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql, {"ultimo_recnum": ultimo_recnum})
        rows = cur.fetchall()
        result = [{k: float(v) if hasattr(v, "__round__") and not isinstance(v, int) else v for k, v in dict(r).items()} for r in rows]
        logger.info("[BI] ctprod: %d registros novos.", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar ctprod: %s", e)
        raise
    finally:
        conn.close()


def fetch_bi_faturamento(janela_dias: int = 90) -> list[dict]:
    """
    Retorna faturas (docrec) — janela deslizante de N dias.

    Estratégia: sempre rebusca os últimos janela_dias para capturar atualizações
    no campo 'liquidado' (faturas pagas após emissão).
    Padrão: 90 dias (~3 meses de histórico vivo).

    Colunas: numfatura, numsequencia, contrato, codigocliente, cliente,
             valoremissao, dataemissao, datavencto, liquidado, tipodocumento,
             representante, representante_nome
    """
    sql = """
        SELECT
            CONVERT(VARCHAR(30), d.numfatura)     AS numfatura,
            CONVERT(VARCHAR(10), d.numsequencia)  AS numsequencia,
            NULLIF(LTRIM(RTRIM(ISNULL(CONVERT(VARCHAR(20), d.contrato), ''))), '') AS contrato,
            CONVERT(VARCHAR(20), d.codigocliente) AS codigocliente,
            ISNULL(CONVERT(VARCHAR(200), d.cliente), '') AS cliente,
            CONVERT(VARCHAR(30), d.valoremissao)  AS valoremissao,
            CONVERT(VARCHAR(10), d.dataemissao, 120) AS dataemissao,
            CONVERT(VARCHAR(10), d.datavencto,  120) AS datavencto,
            ISNULL(CONVERT(VARCHAR(1), d.liquidado), ' ') AS liquidado,
            ISNULL(CONVERT(VARCHAR(100), d.tipodocumento), '') AS tipodocumento,
            ISNULL(CONVERT(VARCHAR(20), c.representante), '') AS representante,
            ISNULL(CONVERT(VARCHAR(200), c.representante_nome), '') AS representante_nome
        FROM docrec d
        LEFT JOIN contract c ON c.codigo = d.contrato
        WHERE d.dataemissao >= DATEADD(day, -%(janela_dias)s, GETDATE())
        ORDER BY d.numfatura
    """
    logger.info("[BI] Buscando docrec (últimos %d dias) ...", janela_dias)
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql, {"janela_dias": janela_dias})
        rows = cur.fetchall()
        result = [{k: float(v) if hasattr(v, "__round__") and not isinstance(v, int) else v for k, v in dict(r).items()} for r in rows]
        logger.info("[BI] docrec: %d registros.", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar docrec: %s", e)
        raise
    finally:
        conn.close()


def fetch_bi_ativos() -> list[dict]:
    """
    Retorna catálogo completo de equipamentos (tabela equip) com:
      - Dados do produto (grupo_descricao, grupo2_descricao via join produtos)
      - Posição atual (contrato + envret via último movimento de ctmequip)
      - Flag de inconsistência quando situacao × envret divergem

    Colunas: codigo, codigoproduto, produto_descricao, serial_fabricante,
             situacao, tipo_equipamento, subtipo_equipamento,
             contrato_atual, ultimo_envret, data_ultimo_mov,
             inconsistente, bi_updated_at
    """
    sql = """
        WITH last_move AS (
            SELECT
                CONVERT(VARCHAR(20), equipamento) AS equipamento,
                CONVERT(VARCHAR(20), contrato)    AS contrato,
                CONVERT(VARCHAR(1),  envret)      AS envret,
                CONVERT(VARCHAR(10), data, 120)   AS data_mov,
                ROW_NUMBER() OVER (
                    PARTITION BY equipamento
                    ORDER BY data DESC, seq DESC
                ) AS rn
            FROM ctmequip
        )
        SELECT
            CONVERT(VARCHAR(20),  e.codigo)                         AS codigo,
            ISNULL(CONVERT(VARCHAR(20),  e.codigoproduto), '')      AS codigoproduto,
            ISNULL(CONVERT(VARCHAR(500), e.produto), '')            AS produto_descricao,
            ISNULL(CONVERT(VARCHAR(200), e.seriefabricante), '')    AS serial_fabricante,
            ISNULL(CONVERT(VARCHAR(50),  e.situacao), '')           AS situacao,
            ISNULL(CONVERT(VARCHAR(200), p.grupo_descricao), '')    AS tipo_equipamento,
            ISNULL(CONVERT(VARCHAR(200), p.grupo2_descricao), '')   AS subtipo_equipamento,
            ISNULL(lm.contrato, '')                                 AS contrato_atual,
            ISNULL(lm.envret,   '')                                 AS ultimo_envret,
            ISNULL(lm.data_mov, '')                                 AS data_ultimo_mov,
            CONVERT(VARCHAR(19), e.created_at, 120)                 AS bi_updated_at
        FROM equip e
        LEFT JOIN produtos p  ON p.codigo  = e.codigoproduto
        LEFT JOIN last_move lm ON lm.equipamento = CONVERT(VARCHAR(20), e.codigo)
                               AND lm.rn = 1
        -- Exclui INATIVO: equipamento desativado não deve entrar em nenhum cálculo de carteira
        WHERE ISNULL(CONVERT(VARCHAR(50), e.situacao), '') NOT LIKE '%INATIV%'
        ORDER BY e.codigo
    """
    logger.info("[BI] Buscando catálogo de ativos (equip + produtos + posição) ...")
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql)
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            sit = (d.get('situacao') or '').upper()
            er  = (d.get('ultimo_envret') or '').upper()
            # Inconsistente: INDISPONÍVEL mas último mov é R, ou DISPONÍVEL mas último mov é E
            indisp = 'INDISPON' in sit
            d['inconsistente'] = (indisp and er == 'R') or (not indisp and er == 'E' and er != '')
            result.append(d)
        logger.info("[BI] bi_ativos: %d equipamentos.", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar bi_ativos: %s", e)
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
        result = [{k: float(v) if hasattr(v, "__round__") and not isinstance(v, int) else v for k, v in dict(r).items()} for r in rows]
        logger.info("[BI] Equipamentos ativos encontrados: %d", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar equipamentos ativos: %s", e)
        raise
    finally:
        conn.close()


def fetch_bi_contas_pagar(janela_dias: int = 120) -> list[dict]:
    sql = """
        SELECT
            CONVERT(VARCHAR(30), dp.numfatura)          AS numfatura,
            CONVERT(VARCHAR(30), dp.recnum)             AS recnum,
            NULLIF(LTRIM(RTRIM(
                ISNULL(CONVERT(VARCHAR(20), dp.contrato), '')
            )), '')                                      AS contrato,
            CONVERT(VARCHAR(20), dp.codigofornecedor)   AS codigofornecedor,
            ISNULL(CONVERT(VARCHAR(200), dp.fornecedor), '') AS fornecedor,
            CONVERT(VARCHAR(30), dp.valoremissao)       AS valorpagamento,
            CONVERT(VARCHAR(10), dp.dataemissao, 120)   AS dataemissao,
            CONVERT(VARCHAR(10), dp.datavencto,  120)   AS datavencto,
            CONVERT(VARCHAR(10), dp.dataprevpagto, 120) AS datapagamento,
            CONVERT(VARCHAR(1),  dp.status)             AS liquidado,
            ISNULL(CONVERT(VARCHAR(100), dp.tipodocumento), '') AS tipodocumento,
            ISNULL(CONVERT(VARCHAR(200), dp.tipodespesa), '')   AS historico,
            ISNULL(CONVERT(VARCHAR(100), dp.centrocusto), '')   AS centrocusto
        FROM docpag dp
        WHERE dp.datavencto >= DATEADD(day, -%(janela_dias)s, GETDATE())
        ORDER BY dp.recnum
    """
    logger.info("[BI] Buscando docpag (últimos %d dias) ...", janela_dias)
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql, {"janela_dias": janela_dias})
        rows = cur.fetchall()
        result = [{k: float(v) if hasattr(v, "__round__") and not isinstance(v, int) else v for k, v in dict(r).items()} for r in rows]
        logger.info("[BI] docpag: %d registros.", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar docpag: %s", e)
        raise
    finally:
        conn.close()


def fetch_bi_carteira_valor() -> list[dict]:
    sql = """
        WITH last_move AS (
            SELECT
                CONVERT(VARCHAR(20), equipamento) AS equipamento,
                CONVERT(VARCHAR(20), contrato)    AS contrato,
                CONVERT(VARCHAR(1),  envret)      AS envret,
                ROW_NUMBER() OVER (
                    PARTITION BY equipamento
                    ORDER BY data DESC, seq DESC
                ) AS rn
            FROM ctmequip
        ),
        equip_em_contrato AS (
            SELECT lm.contrato, COUNT(lm.equipamento) AS qtd_equipamentos
            FROM last_move lm
            JOIN equip e ON CONVERT(VARCHAR(20), e.codigo) = lm.equipamento
            WHERE lm.rn = 1
              AND lm.envret = 'E'
              AND ISNULL(CONVERT(VARCHAR(50), e.situacao), '') NOT LIKE '%INATIV%'
            GROUP BY lm.contrato
        ),
        valor_contrato AS (
            -- Valor mensal correto: join por (contrato, produto, setor)
            -- setor em ctmequip = tabela de preco do equipamento
            -- Validado: total R$1.643.691 vs R$1.644.935 real (diff 0.07%)
            SELECT
                lm.contrato,
                SUM(ISNULL(CONVERT(DECIMAL(18,2), cp.valorunitario), 0)) AS valor_mensal_total
            FROM last_move lm
            JOIN equip e ON CONVERT(VARCHAR(20), e.codigo) = lm.equipamento
            LEFT JOIN ctprod cp ON CONVERT(VARCHAR(20), cp.contrato) = lm.contrato
                               AND cp.produto = e.codigoproduto
                               AND ISNULL(CONVERT(VARCHAR(500), cp.setor), '') = lm.setor
            WHERE lm.rn = 1
              AND lm.envret = 'E'
              AND ISNULL(CONVERT(VARCHAR(50), e.situacao), '') NOT LIKE '%INATIV%'
            GROUP BY lm.contrato
        )
        SELECT
            c.codigo                                AS contrato,
            c.cliente                               AS cliente_codigo,
            (SELECT TOP 1 d.cliente FROM docrec d
             WHERE d.codigocliente = c.cliente
             ORDER BY d.recnum DESC)                AS cliente_nome,
            ISNULL(ec.qtd_equipamentos, 0)          AS qtd_equipamentos,
            ISNULL(vc.valor_mensal_total, 0)        AS valor_mensal_total,
            CONVERT(VARCHAR(10), c.datavigini, 120) AS datavigini,
            CONVERT(VARCHAR(10), c.datavigfim, 120) AS datavigfim
        FROM contract c
        LEFT JOIN equip_em_contrato ec ON ec.contrato = c.codigo
        LEFT JOIN valor_contrato     vc ON vc.contrato = c.codigo
        WHERE c.situacao = '3'
        ORDER BY vc.valor_mensal_total DESC
    """
    logger.info("[BI] Buscando valor real por contrato ...")
    conn = _get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql)
        rows = cur.fetchall()
        result = [{k: float(v) if hasattr(v, "__round__") and not isinstance(v, int) else v for k, v in dict(r).items()} for r in rows]
        logger.info("[BI] Carteira com valor: %d contratos.", len(result))
        return result
    except Exception as e:
        logger.error("[BI] Erro ao buscar carteira com valor: %s", e)
        raise
    finally:
        conn.close()
