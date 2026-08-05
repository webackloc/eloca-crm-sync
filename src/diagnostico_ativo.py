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
        WHERE CONVERT(VARCHAR(20), e.codigo) IN ('8001', '8002', '8003')
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
        WHERE CONVERT(VARCHAR(20), equipamento) IN ('8001', '8002', '8003')
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
# 4. Supabase — bi_ativos via RPC
# ─────────────────────────────────────────────────────────────────────────────
sep("Supabase — bi_ativos (8001, 8002, 8003) via RPC")
try:
    sb  = get_sb()
    res = sb.rpc("diagnostico_bi_ativos", {"p_codigos": ["8001","8002","8003"]}).execute()
    if res.data:
        for r in res.data:
            print(f"  {r['codigo']} | {r['situacao']} | envret={r['ultimo_envret']} | contrato={r['contrato_atual']} | {r['data_ultimo_mov']}")
    else:
        print("  ⚠️  Nenhum dos ativos encontrado no Supabase bi_ativos")
except Exception as e:
    # fallback: tenta com postgrest usando service key (bypass RLS)
    try:
        import httpx, json
        url = os.getenv("SUPABASE_URL").rstrip("/")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        r = httpx.get(
            f"{url}/rest/v1/bi_ativos",
            params={"codigo": "in.(8001,8002,8003)", "select": "codigo,situacao,contrato_atual,ultimo_envret,data_ultimo_mov"},
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=15
        )
        rows = r.json()
        if isinstance(rows, list) and rows:
            for row in rows:
                print(f"  {row.get('codigo')} | {row.get('situacao')} | envret={row.get('ultimo_envret')} | contrato={row.get('contrato_atual')} | {row.get('data_ultimo_mov')}")
        elif isinstance(rows, list):
            print("  ⚠️  Nenhum dos ativos encontrado no Supabase bi_ativos")
        else:
            print(f"  ERRO REST: {rows}")
    except Exception as e2:
        print(f"  ERRO Supabase bi_ativos: {e} | {e2}")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Supabase — carteira_contratos via REST
# ─────────────────────────────────────────────────────────────────────────────
sep("Supabase — carteira_contratos (326)")
try:
    import httpx
    url = os.getenv("SUPABASE_URL").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    r = httpx.get(
        f"{url}/rest/v1/carteira_contratos",
        params={"id": "eq.326", "select": "*"},
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=15
    )
    rows = r.json()
    if isinstance(rows, list) and rows:
        row = rows[0]
        print(f"  contrato={row.get('id')} | cliente={row.get('cliente_nome')} | situacao={row.get('situacao')} | {row.get('data_inicio')} → {row.get('data_fim')}")
    elif isinstance(rows, list):
        print("  ⚠️  Contrato 326 NÃO encontrado no Supabase carteira_contratos")
    else:
        print(f"  ERRO REST: {rows}")
except Exception as e:
    print(f"  ERRO Supabase carteira_contratos: {e}")

print("\n" + "═"*60 + "\n")
