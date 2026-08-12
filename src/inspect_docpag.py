import pymssql, os
conn = pymssql.connect(
    server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
    port=1433, user="weback",
    password=os.environ["BI_PASSWORD"],
    database="biweback", timeout=60, charset="UTF-8"
)
cur = conn.cursor(as_dict=True)
print("=== DOCPAG colunas ===")
cur.execute("SELECT TOP 2 * FROM docpag ORDER BY recnum DESC")
for r in cur.fetchall():
    for k, v in r.items():
        print(f"  {k}: {v}")
    print("---")
conn.close()
