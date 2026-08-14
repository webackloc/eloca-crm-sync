import pymssql, os
conn = pymssql.connect(
    server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
    port=1433, user="weback",
    password=os.environ["BI_PASSWORD"],
    database="biweback", timeout=60, charset="UTF-8"
)
cur = conn.cursor(as_dict=True)

print("=== dataprevpagto vs datavencto — quantos tem data de pagamento? ===")
cur.execute("""
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN dataprevpagto IS NOT NULL AND dataprevpagto <= GETDATE() THEN 1 ELSE 0 END) AS com_pagamento_realizado,
        SUM(CASE WHEN dataprevpagto IS NULL THEN 1 ELSE 0 END) AS sem_data_pagamento
    FROM docpag
    WHERE datavencto >= DATEADD(day, -120, GETDATE())
""")
print(dict(cur.fetchone()))

print("\n=== Existe campo datapagamento (diferente de dataprevpagto)? ===")
cur.execute("""
    SELECT TOP 3
        numfatura, datavencto, dataprevpagto,
        valoremissao, status, numbordero
    FROM docpag
    WHERE datavencto < GETDATE()
    AND datavencto >= DATEADD(day, -30, GETDATE())
    ORDER BY recnum DESC
""")
for r in cur.fetchall():
    print(dict(r))
conn.close()
