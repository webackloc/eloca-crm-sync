"""
diagnostico_ativo.py — Consulta pontual no BI para validar ativos/contratos
Uso via GitHub Actions: python src/diagnostico_ativo.py

Verifica se os ativos/contratos existem no BI e no Supabase.
"""

import os, sys
import pymssql
from supabase import create_client

# ── Conexão BI ────────────────────────────────────────────────────────────────
def get_bi():
    return pymssql.connect(
        server=os.getenv("BI_HOST"),
        port=int(os.getenv("BI_PORT", "1433")),
        user=os.getenv("BI_USER"),
        password=os.getenv("BI_PASSWORD"),
        database=os.getenv("BI_DATABASE"),
        timeout=60,
        charset="UTF-8",
    )

# ── Conexão Supabase ──────────────────────────────────────────────────────────
def get_sb():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

def sep(title):
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print('═'*60)

# ─────────────────────────────────────────────────────────────────────────────
# 1. BI — Equipamentos 8001, 8002, 8003
# ─────────────────────────────────────────────────────────────────────────────
sep("BI — tabela equip (ativos 8001, 8002, 8003)")
try:
    conn = get_bi()
    cur  = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT
            CONVERT(VARCHAR(20), e.codigo)          AS codigo,
            ISNULL(CONVERT(VARCHAR(200), e.produto), '') AS produto,
            ISNULL(CONVERT(VARCHAR(50),  e.situacao),'') AS situacao,
            ISNULL(CONVERT(VARCHAR(200), e.seriefabricante),'') AS serial
        FROM equip e
        WHERE e.codigo IN (8001, 8002, 8003)
    """)
    rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  codigo={r['codigo']} | situacao={r['situacao']} | produto={r['produto'][:40]} | serial={r['serial']}")
    else:
        print("  ⚠️  Nenhum dos ativos 8001/8002/8003 encontrado no BI (ainda não sincronizou)")
    conn.close()
except Exception as e:
    print(f"  ERRO BI equip: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. BI — Contrato 326
# ─────────────────────────────────────────────────────────────────────────────
sep("BI — tabela contract (contrato 326)")
try:
    conn = get_bi()
    cur  = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT
            CONVERT(VARCHAR(20), c.codigo)     AS codigo,
            CONVERT(VARCHAR(20), c.cliente)    AS cliente,
            CONVERT(VARCHAR(10), c.situacao)   AS situacao,
            CONVERT(VARCHAR(10), c.datavigini, 120) AS inicio,
            CONVERT(VARCHAR(10), c.datavigfim, 120) AS fim
        FROM contract c
        WHERE c.codigo = 326
    """)
    rows = cur.fetchall()
    if rows:
        r = rows[0]
        print(f"  contrato={r['codigo']} | cliente={r['cliente']} | situacao={r['situacao']} | {r['inicio']} → {r['fim']}")
        if r['situacao'] != '3':
            print(f"  ⚠️  Situação NÃO é APROVADO (3) — contrato não vai aparecer na carteira_contratos")
    else:
        print("  ⚠️  Contrato 326 NÃO encontrado no BI")
    conn.close()
except Exception as e:
    print(f"  ERRO BI contract: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. BI — Últimas movimentações dos ativos 8001/8002/8003
# ─────────────────────────────────────────────────────────────────────────────
sep("BI — ctmequip (movimentações 8001, 8002, 8003)")
try:
    conn = get_bi()
    cur  = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT TOP 10
            CONVERT(VARCHAR(20), recnum)      AS recnum,
            CONVERT(VARCHAR(20), equipamento) AS equipamento,
            CONVERT(VARCHAR(20), contrato)    AS contrato,
            CONVERT(VARCHAR(1),  envret)      AS envret,
            CONVERT(VARCHAR(10), data, 120)   AS data,
            CONVERT(VARCHAR(20), numos)       AS numos
        FROM ctmequip
        WHERE equipamento IN (8001, 8002, 8003)
        ORDER BY recnum DESC
    """)
    rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  recnum={r['recnum']} | equip={r['equipamento']} | contrato={r['contrato']} | {r['envret']} | {r['data']} | OS={r['numos']}")
    else:
        print("  ⚠️  Nenhuma movimentação encontrada para 8001/8002/8003 no BI")
    conn.close()
except Exception as e:
    print(f"  ERRO BI ctmequip: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 4. Supabase — bi_ativos
# ─────────────────────────────────────────────────────────────────────────────
sep("Supabase — bi_ativos (8001, 8002, 8003)")
try:
    sb  = get_sb()
    res = sb.table("bi_ativos").select(
        "codigo, produto_descricao, situacao, contrato_atual, ultimo_envret, data_ultimo_mov, inconsistente"
    ).in_("codigo", ["8001","8002","8003"]).execute()
    if res.data:
        for r in res.data:
            print(f"  {r['codigo']} | {r['situacao']} | envret={r['ultimo_envret']} | contrato={r['contrato_atual']} | {r['data_ultimo_mov']}")
    else:
        print("  ⚠️  Nenhum dos ativos encontrado no Supabase bi_ativos")
except Exception as e:
    print(f"  ERRO Supabase bi_ativos: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Supabase — carteira_contratos
# ─────────────────────────────────────────────────────────────────────────────
sep("Supabase — carteira_contratos (326)")
try:
    sb  = get_sb()
    res = sb.table("carteira_contratos").select("*").eq("id", "326").execute()
    if res.data:
        r = res.data[0]
        print(f"  contrato={r.get('id')} | cliente={r.get('cliente_nome')} | situacao={r.get('situacao')} | {r.get('data_inicio')} → {r.get('data_fim')}")
    else:
        print("  ⚠️  Contrato 326 NÃO encontrado no Supabase carteira_contratos")
except Exception as e:
    print(f"  ERRO Supabase carteira_contratos: {e}")

print("\n" + "═"*60 + "\n")
