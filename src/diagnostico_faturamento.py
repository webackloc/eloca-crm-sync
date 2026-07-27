"""
diagnostico_faturamento.py — Diagnóstico do faturamento 2026
Objetivo: encontrar por que o total está divergindo dos R$ 8,9M esperados

Uso:
  BI_PASSWORD="..." python3 src/diagnostico_faturamento.py
"""
import os
import pymssql

conn = pymssql.connect(
    server   = os.getenv("BI_HOST", "og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com"),
    port     = int(os.getenv("BI_PORT", "1433")),
    user     = os.getenv("BI_USER", "weback"),
    password = os.getenv("BI_PASSWORD", ""),
    database = os.getenv("BI_DATABASE", "biweback"),
    timeout  = 120, charset="UTF-8",
)
cur = conn.cursor(as_dict=True)
SEP = "═" * 60

# 1. Total geral no docrec por ano
print(f"\n{SEP}")
print("1. TOTAL FATURADO POR ANO (todos os registros docrec)")
print(SEP)
cur.execute("""
    SELECT
        YEAR(dataemissao) AS ano,
        COUNT(*) AS qtd_notas,
        SUM(CONVERT(FLOAT, valoremissao)) AS total
    FROM docrec
    WHERE dataemissao IS NOT NULL
    GROUP BY YEAR(dataemissao)
    ORDER BY ano
""")
for r in cur.fetchall():
    print(f"  {r['ano']}: {r['qtd_notas']} notas  →  R$ {float(r['total'] or 0):,.2f}")

# 2. Total 2026 por mês
print(f"\n{SEP}")
print("2. FATURAMENTO 2026 POR MÊS")
print(SEP)
cur.execute("""
    SELECT
        MONTH(dataemissao) AS mes,
        COUNT(*) AS qtd_notas,
        SUM(CONVERT(FLOAT, valoremissao)) AS total,
        SUM(CASE WHEN LTRIM(RTRIM(ISNULL(liquidado,''))) = 'S'
                 THEN CONVERT(FLOAT, valoremissao) ELSE 0 END) AS liquidado,
        SUM(CASE WHEN LTRIM(RTRIM(ISNULL(liquidado,''))) != 'S'
                 THEN CONVERT(FLOAT, valoremissao) ELSE 0 END) AS em_aberto
    FROM docrec
    WHERE dataemissao >= '2026-01-01' AND dataemissao <= '2026-12-31'
    GROUP BY MONTH(dataemissao)
    ORDER BY mes
""")
total_2026 = 0.0
for r in cur.fetchall():
    meses = ['','Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
    t = float(r['total'] or 0)
    total_2026 += t
    print(f"  {meses[r['mes']]}/2026: {r['qtd_notas']:>3} notas  →  R$ {t:>12,.2f}  (liq: R$ {float(r['liquidado'] or 0):>12,.2f}  aberto: R$ {float(r['em_aberto'] or 0):>10,.2f})")
print(f"\n  TOTAL 2026: R$ {total_2026:,.2f}")

# 3. Verificar duplicatas por numfatura
print(f"\n{SEP}")
print("3. VERIFICAÇÃO DE DUPLICATAS (numfatura)")
print(SEP)
cur.execute("""
    SELECT
        COUNT(*) AS total_registros,
        COUNT(DISTINCT numfatura) AS numfatura_unicos,
        COUNT(*) - COUNT(DISTINCT numfatura) AS possiveis_duplicatas
    FROM docrec
    WHERE dataemissao >= '2026-01-01'
""")
print(dict(cur.fetchone()))

# 4. numfatura duplicado — quais são?
cur.execute("""
    SELECT TOP 10
        numfatura,
        COUNT(*) AS ocorrencias,
        SUM(CONVERT(FLOAT, valoremissao)) AS valor_total
    FROM docrec
    WHERE dataemissao >= '2026-01-01'
    GROUP BY numfatura
    HAVING COUNT(*) > 1
    ORDER BY ocorrencias DESC
""")
rows = cur.fetchall()
if rows:
    print("\nNumfaturas duplicados em 2026:")
    for r in rows:
        print(f"  numfatura={r['numfatura']}: {r['ocorrencias']}x  →  R$ {float(r['valor_total'] or 0):,.2f}")
else:
    print("Nenhuma duplicata encontrada.")

# 5. Por tipo de documento
print(f"\n{SEP}")
print("4. FATURAMENTO 2026 POR TIPO DE DOCUMENTO")
print(SEP)
cur.execute("""
    SELECT
        ISNULL(tipodocumento, 'SEM TIPO') AS tipodocumento,
        COUNT(*) AS qtd,
        SUM(CONVERT(FLOAT, valoremissao)) AS total
    FROM docrec
    WHERE dataemissao >= '2026-01-01'
    GROUP BY tipodocumento
    ORDER BY total DESC
""")
for r in cur.fetchall():
    print(f"  {r['tipodocumento']:<30}: {r['qtd']:>4} notas  →  R$ {float(r['total'] or 0):>12,.2f}")

# 6. Por numsequencia
print(f"\n{SEP}")
print("5. FATURAMENTO 2026 POR NUMSEQUENCIA (parcela)")
print(SEP)
cur.execute("""
    SELECT
        numsequencia,
        COUNT(*) AS qtd,
        SUM(CONVERT(FLOAT, valoremissao)) AS total
    FROM docrec
    WHERE dataemissao >= '2026-01-01'
    GROUP BY numsequencia
    ORDER BY numsequencia
""")
for r in cur.fetchall():
    print(f"  sequencia={r['numsequencia']}: {r['qtd']:>4} notas  →  R$ {float(r['total'] or 0):>12,.2f}")

# 7. Amostra dos maiores valores individuais em 2026
print(f"\n{SEP}")
print("6. TOP 15 MAIORES FATURAS INDIVIDUAIS 2026")
print(SEP)
cur.execute("""
    SELECT TOP 15
        CONVERT(VARCHAR(30), d.numfatura) AS numfatura,
        d.numsequencia,
        ISNULL(d.contrato, '') AS contrato,
        ISNULL(d.cliente, '') AS cliente,
        d.valoremissao,
        CONVERT(VARCHAR(10), d.dataemissao, 120) AS dataemissao,
        d.liquidado,
        d.tipodocumento
    FROM docrec d
    WHERE d.dataemissao >= '2026-01-01'
    ORDER BY CONVERT(FLOAT, d.valoremissao) DESC
""")
for r in cur.fetchall():
    liq = 'SIM' if str(r['liquidado']).strip() == 'S' else 'NÃO'
    print(f"  Fatura {r['numfatura']:>12} | seq={r['numsequencia']} | {r['cliente'][:35]:<35} | R$ {float(r['valoremissao'] or 0):>12,.2f} | {r['dataemissao']} | liq={liq}")

conn.close()
print(f"\n{'═'*60}")
print("✓ Diagnóstico concluído.")
