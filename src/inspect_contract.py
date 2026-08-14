import pymssql, os
conn = pymssql.connect(
    server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
    port=1433, user="weback",
    password=os.environ["BI_PASSWORD"],
    database="biweback", timeout=60, charset="UTF-8"
)
cur = conn.cursor(as_dict=True)

print("=== numbordero — distribuição ===")
cur.execute("""
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN numbordero > 0 THEN 1 ELSE 0 END) AS com_bordero_pago,
        SUM(CASE WHEN numbordero = 0 THEN 1 ELSE 0 END) AS sem_bordero_aberto,
        SUM(CASE WHEN numbordero > 0 THEN valoremissao ELSE 0 END) AS valor_pago,
        SUM(CASE WHEN numbordero = 0 THEN valoremissao ELSE 0 END) AS valor_aberto
    FROM docpag
    WHERE datavencto >= DATEADD(day, -120, GETDATE())
""")
print(dict(cur.fetchone()))
conn.close()
