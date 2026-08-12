import pymssql, os
conn = pymssql.connect(
    server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
    port=1433, user="weback",
    password=os.environ["BI_PASSWORD"],
    database="biweback", timeout=60, charset="UTF-8"
)
cur = conn.cursor(as_dict=True)

print("=== Contrato 51 — join com setor do ctmequip ===")
cur.execute("""
    WITH last_move AS (
        SELECT
            CONVERT(VARCHAR(20), equipamento) AS equipamento,
            CONVERT(VARCHAR(20), contrato)    AS contrato,
            CONVERT(VARCHAR(1),  envret)      AS envret,
            ISNULL(CONVERT(VARCHAR(500), setor), '') AS setor,
            ROW_NUMBER() OVER (
                PARTITION BY equipamento
                ORDER BY data DESC, seq DESC
            ) AS rn
        FROM ctmequip
    )
    SELECT
        COUNT(lm.equipamento)                              AS qtd_equip,
        SUM(ISNULL(CONVERT(DECIMAL(18,2), cp.valorunitario), 0)) AS valor_mensal
    FROM last_move lm
    JOIN equip e ON CONVERT(VARCHAR(20), e.codigo) = lm.equipamento
    LEFT JOIN ctprod cp ON CONVERT(VARCHAR(20), cp.contrato) = lm.contrato
                       AND cp.produto = e.codigoproduto
                       AND ISNULL(CONVERT(VARCHAR(500), cp.setor), '') = lm.setor
    WHERE lm.rn = 1
      AND lm.contrato = '51'
      AND lm.envret = 'E'
      AND ISNULL(CONVERT(VARCHAR(50), e.situacao), '') NOT LIKE '%INATIV%'
""")
print(dict(cur.fetchone()))

print("\n=== Total geral com join por setor ===")
cur.execute("""
    WITH last_move AS (
        SELECT
            CONVERT(VARCHAR(20), equipamento) AS equipamento,
            CONVERT(VARCHAR(20), contrato)    AS contrato,
            CONVERT(VARCHAR(1),  envret)      AS envret,
            ISNULL(CONVERT(VARCHAR(500), setor), '') AS setor,
            ROW_NUMBER() OVER (
                PARTITION BY equipamento
                ORDER BY data DESC, seq DESC
            ) AS rn
        FROM ctmequip
    )
    SELECT
        COUNT(DISTINCT lm.contrato)                            AS contratos,
        COUNT(lm.equipamento)                                  AS equipamentos,
        SUM(ISNULL(CONVERT(DECIMAL(18,2), cp.valorunitario), 0)) AS valor_total
    FROM last_move lm
    JOIN equip e ON CONVERT(VARCHAR(20), e.codigo) = lm.equipamento
    JOIN contract c ON c.codigo = lm.contrato AND c.situacao = '3'
    LEFT JOIN ctprod cp ON CONVERT(VARCHAR(20), cp.contrato) = lm.contrato
                       AND cp.produto = e.codigoproduto
                       AND ISNULL(CONVERT(VARCHAR(500), cp.setor), '') = lm.setor
    WHERE lm.rn = 1
      AND lm.envret = 'E'
      AND ISNULL(CONVERT(VARCHAR(50), e.situacao), '') NOT LIKE '%INATIV%'
""")
print(dict(cur.fetchone()))
conn.close()
