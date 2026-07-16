"""
inspect_bi_tables.py — Inspeciona tabelas do BI SQL Server
Rode via: python src/inspect_bi_tables.py
"""
import pymssql, os

conn = pymssql.connect(
    server   = os.getenv("BI_HOST", "og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com"),
    port     = int(os.getenv("BI_PORT", "1433")),
    user     = os.getenv("BI_USER", "weback"),
    password = os.getenv("BI_PASSWORD", ""),
    database = os.getenv("BI_DATABASE", "biweback"),
    timeout  = 60, charset="UTF-8",
)
cur = conn.cursor()

# 1. Todas as tabelas
cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME")
tabelas = [r[0] for r in cur.fetchall()]
print("\n=== TABELAS ===")
print(tabelas)

# 2. Colunas das tabelas de interesse
for tabela in tabelas:
    cur.execute(f"SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='{tabela}' ORDER BY ORDINAL_POSITION")
    colunas = cur.fetchall()
    print(f"\n--- {tabela} ({len(colunas)} colunas) ---")
    print([c[0] for c in colunas])

# 3. Contagem de registros
print("\n=== CONTAGENS ===")
for tabela in tabelas:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {tabela}")
        n = cur.fetchone()[0]
        print(f"  {tabela}: {n:,}")
    except Exception as e:
        print(f"  {tabela}: ERRO - {e}")

conn.close()
