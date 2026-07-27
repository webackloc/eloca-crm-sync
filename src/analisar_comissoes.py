"""
analisar_comissoes.py — Análise local de comissões a partir do BI
Período: 2º Trimestre 2026 (Abril, Maio, Junho)

Regra:
  - 1ª parcela (numsequencia=1): 10% do valoremissao
  - Demais parcelas: 1% do valoremissao
  - Base: apenas parcelas RECEBIDAS no trimestre (liquidado='S' e data no período)

Uso:
  BI_PASSWORD="..." python3 src/analisar_comissoes.py
"""

import os
import pymssql

# ── Conexão ───────────────────────────────────────────────────────────────────
conn = pymssql.connect(
    server   = os.getenv("BI_HOST", "og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com"),
    port     = int(os.getenv("BI_PORT", "1433")),
    user     = os.getenv("BI_USER", "weback"),
    password = os.getenv("BI_PASSWORD", ""),
    database = os.getenv("BI_DATABASE", "biweback"),
    timeout  = 120, charset="UTF-8",
)
cur = conn.cursor(as_dict=True)

# ── 1. Inspecionar docrec — colunas e amostra ─────────────────────────────────
print("\n=== COLUNAS docrec ===")
cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='docrec' ORDER BY ORDINAL_POSITION")
print([r['COLUMN_NAME'] for r in cur.fetchall()])

print("\n=== AMOSTRA docrec (5 linhas com contrato) ===")
cur.execute("""
    SELECT TOP 5 recnum, numfatura, numsequencia, codigocliente, cliente,
                 valoremissao, dataemissao, datavencto, dataprevpagto,
                 contrato, liquidado, status
    FROM docrec
    WHERE contrato IS NOT NULL AND contrato != ''
    ORDER BY recnum DESC
""")
for r in cur.fetchall():
    print(dict(r))

# ── 2. Valores distintos de liquidado e status ────────────────────────────────
print("\n=== VALORES DE liquidado ===")
cur.execute("SELECT DISTINCT liquidado, COUNT(*) as qtd FROM docrec GROUP BY liquidado")
for r in cur.fetchall(): print(dict(r))

print("\n=== VALORES DE status ===")
cur.execute("SELECT DISTINCT status, COUNT(*) as qtd FROM docrec GROUP BY status")
for r in cur.fetchall(): print(dict(r))

# ── 3. Parcelas do trimestre Apr-Jun 2026 ─────────────────────────────────────
print("\n=== PARCELAS TRIMESTRE (Abr-Jun 2026) — todos os status ===")
cur.execute("""
    SELECT TOP 20
        d.contrato,
        d.numsequencia,
        d.codigocliente,
        d.cliente,
        d.valoremissao,
        CONVERT(VARCHAR(10), d.dataemissao, 120) AS dataemissao,
        CONVERT(VARCHAR(10), d.datavencto,  120) AS datavencto,
        d.liquidado,
        d.status,
        c.representante,
        c.representante_nome
    FROM docrec d
    LEFT JOIN contract c ON c.codigo = d.contrato
    WHERE d.dataemissao >= '2026-04-01'
      AND d.dataemissao <= '2026-06-30'
    ORDER BY d.dataemissao, d.contrato, d.numsequencia
""")
rows = cur.fetchall()
print(f"Total no período (amostra 20): {len(rows)}")
for r in rows:
    print(dict(r))

# ── 4. Contagem total no trimestre ────────────────────────────────────────────
print("\n=== CONTAGEM TOTAL TRIMESTRE ===")
cur.execute("""
    SELECT COUNT(*) as total,
           COUNT(DISTINCT d.contrato) as contratos,
           COUNT(DISTINCT d.codigocliente) as clientes,
           SUM(d.valoremissao) as valor_total
    FROM docrec d
    WHERE d.dataemissao >= '2026-04-01'
      AND d.dataemissao <= '2026-06-30'
""")
for r in cur.fetchall(): print(dict(r))

# ── 5. Prévia do cálculo de comissão ─────────────────────────────────────────
print("\n=== PRÉVIA COMISSÕES (regra: 10% parcela 1, 1% demais) ===")
cur.execute("""
    SELECT
        d.contrato,
        c.representante_nome AS vendedor,
        d.codigocliente,
        d.cliente,
        d.numsequencia,
        d.valoremissao,
        CONVERT(VARCHAR(10), d.dataemissao, 120) AS dataemissao,
        d.liquidado,
        CASE WHEN d.numsequencia = 1
             THEN d.valoremissao * 0.10
             ELSE d.valoremissao * 0.01
        END AS comissao
    FROM docrec d
    LEFT JOIN contract c ON c.codigo = d.contrato
    WHERE d.dataemissao >= '2026-04-01'
      AND d.dataemissao <= '2026-06-30'
      AND d.contrato IS NOT NULL AND d.contrato != ''
    ORDER BY c.representante_nome, d.contrato, d.numsequencia
""")
rows = cur.fetchall()
print(f"Total de parcelas com contrato no período: {len(rows)}")

# Agrupamento por vendedor
from collections import defaultdict
por_vendedor = defaultdict(float)
for r in rows:
    vendedor = r['vendedor'] or 'SEM VENDEDOR'
    por_vendedor[vendedor] += float(r['comissao'] or 0)

print("\n--- Comissão por vendedor ---")
total_geral = 0
for vendedor, total in sorted(por_vendedor.items()):
    print(f"  {vendedor}: R$ {total:,.2f}")
    total_geral += total
print(f"\n  TOTAL GERAL: R$ {total_geral:,.2f}")

conn.close()
print("\n✓ Análise concluída.")
