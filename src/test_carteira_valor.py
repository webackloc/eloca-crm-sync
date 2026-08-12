import pymssql, os
conn = pymssql.connect(
    server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
    port=1433, user="weback",
    password=os.environ["BI_PASSWORD"],
    database="biweback", timeout=60, charset="UTF-8"
)
cur = conn.cursor(as_dict=True)

print("=== Amostra ctprod — tipos e valores ===")
cur.execute("""
    SELECT TOP 5
        contrato,
        produto,
        valorunitario,
        quantidade,
        SQL_VARIANT_PROPERTY(valorunitario, 'BaseType') AS tipo_valorunitario,
        SQL_VARIANT_PROPERTY(quantidade, 'BaseType') AS tipo_quantidade
    FROM ctprod
    WHERE valorunitario IS NOT NULL AND valorunitario != 0
    ORDER BY recnum DESC
""")
for r in cur.fetchall():
    print(dict(r))

print("\n=== Soma por contrato (amostra 5) ===")
cur.execute("""
    SELECT TOP 5
        contrato,
        SUM(CAST(valorunitario AS DECIMAL(18,2)) * ISNULL(CAST(quantidade AS INT), 1)) AS valor_mensal
    FROM ctprod
    WHERE valorunitario IS NOT NULL
    GROUP BY contrato
    ORDER BY valor_mensal DESC
""")
for r in cur.fetchall():
    print(dict(r))

conn.close()
