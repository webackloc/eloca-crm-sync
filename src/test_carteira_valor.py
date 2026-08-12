import pymssql, os
conn = pymssql.connect(
    server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
    port=1433, user="weback",
    password=os.environ["BI_PASSWORD"],
    database="biweback", timeout=60, charset="UTF-8"
)
cur = conn.cursor(as_dict=True)

print("=== Valor mensal por contrato (top 5) ===")
cur.execute("""
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
    )
    SELECT TOP 5
        lm.contrato,
        COUNT(lm.equipamento) AS qtd_equip,
        SUM(ISNULL(CONVERT(DECIMAL(18,2), cp.valorunitario), 0)) AS valor_mensal
    FROM last_move lm
    JOIN equip e ON CONVERT(VARCHAR(20), e.codigo) = lm.equipamento
    JOIN ctprod cp ON CONVERT(VARCHAR(20), cp.contrato) = lm.contrato
                  AND cp.produto = e.codigoproduto
    WHERE lm.rn = 1
      AND lm.envret = 'E'
      AND ISNULL(CONVERT(VARCHAR(50), e.situacao), '') NOT LIKE '%INATIV%'
    GROUP BY lm.contrato
    ORDER BY valor_mensal DESC
""")
for r in cur.fetchall():
    print(dict(r))

print("\n=== Total geral ===")
cur.execute("""
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
    )
    SELECT
        COUNT(DISTINCT lm.contrato) AS contratos,
        COUNT(lm.equipamento)       AS equipamentos,
        SUM(ISNULL(CONVERT(DECIMAL(18,2), cp.valorunitario), 0)) AS valor_total
    FROM last_move lm
    JOIN equip e ON CONVERT(VARCHAR(20), e.codigo) = lm.equipamento
    JOIN ctprod cp ON CONVERT(VARCHAR(20), cp.contrato) = lm.contrato
                  AND cp.produto = e.codigoproduto
    WHERE lm.rn = 1
      AND lm.envret = 'E'
      AND ISNULL(CONVERT(VARCHAR(50), e.situacao), '') NOT LIKE '%INATIV%'
""")
print(dict(cur.fetchone()))
conn.close()

print("\n=== ctprod simples — soma por contrato (top 5) ===")
cur2 = conn.cursor(as_dict=True)
conn2 = __import__('pymssql').connect(
    server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
    port=1433, user="weback",
    password=os.environ["BI_PASSWORD"],
    database="biweback", timeout=60, charset="UTF-8"
)
cur2 = conn2.cursor(as_dict=True)
cur2.execute("""
    SELECT TOP 5
        CONVERT(VARCHAR(20), cp.contrato) AS contrato,
        COUNT(*) AS linhas,
        SUM(ISNULL(CONVERT(DECIMAL(18,2), cp.valorunitario), 0)) AS valor_mensal
    FROM ctprod cp
    JOIN contract c ON c.codigo = cp.contrato
    WHERE c.situacao = '3'
    GROUP BY cp.contrato
    ORDER BY valor_mensal DESC
""")
for r in cur2.fetchall():
    print(dict(r))

cur2.execute("""
    SELECT
        COUNT(DISTINCT cp.contrato) AS contratos,
        SUM(ISNULL(CONVERT(DECIMAL(18,2), cp.valorunitario), 0)) AS valor_total
    FROM ctprod cp
    JOIN contract c ON c.codigo = cp.contrato
    WHERE c.situacao = '3'
""")
print("Total:", dict(cur2.fetchone()))
conn2.close()
