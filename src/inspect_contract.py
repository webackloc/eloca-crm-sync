import pymssql, os
conn = pymssql.connect(
    server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
    port=1433, user="weback",
    password=os.environ["BI_PASSWORD"],
    database="biweback", timeout=60, charset="UTF-8"
)
cur = conn.cursor(as_dict=True)

print("=== Distribuição de status em docpag ===")
cur.execute("""
    SELECT status, COUNT(*) AS qtd, SUM(valoremissao) AS valor_total
    FROM docpag
    WHERE datavencto >= DATEADD(day, -120, GETDATE())
    GROUP BY status
    ORDER BY status
""")
for r in cur.fetchall():
    print(dict(r))

print("\n=== Exemplo de registro pago (status != 0) ===")
cur.execute("""
    SELECT TOP 3 numfatura, status, valoremissao, datavencto, dataprevpagto
    FROM docpag
    WHERE status != 0
    AND datavencto >= DATEADD(day, -120, GETDATE())
    ORDER BY recnum DESC
""")
for r in cur.fetchall():
    print(dict(r))
conn.close()
