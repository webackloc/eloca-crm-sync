"""
validar_supabase.py — Validação rápida das tabelas no Supabase

Rodar no terminal:
    cd "/Users/leonardo/Documents/Claude/Projects/Integracao ELOCA - CRM LOVABLE"
    python3 validar_supabase.py

Requer: pip install python-dotenv supabase
"""

import os
import sys
from dotenv import dotenv_values

cfg = dotenv_values(".env")
SUPABASE_URL = cfg.get("SUPABASE_URL", "")
SUPABASE_KEY = cfg.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERRO: SUPABASE_URL ou SUPABASE_SERVICE_KEY não encontrados no .env")
    sys.exit(1)

# Remove proxies do ambiente para não interferir
for k in ["PROXY_URL", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(k, None)

from supabase import create_client
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Contagem de registros por tabela ─────────────────────────────────────────

TABELAS = [
    ("carteira_contratos", ["id", "cliente_nome", "situacao", "data_inicio", "data_fim"]),
    ("ativos",             ["codigo", "descricao", "status", "cliente", "contrato", "situacao_os"]),
    ("ordens_servico",     ["numero", "tipo", "status", "cliente", "ativo_id", "data_abertura"]),
    ("bi_ativos",          ["codigo", "produto_descricao", "situacao", "contrato_atual", "ultimo_envret", "inconsistente"]),
    ("bi_movimentacoes",   ["recnum", "equipamento", "contrato", "envret", "data"]),
    ("bi_ctprod",          ["recnum", "contrato", "produto", "produto_descricao", "valorunitario"]),
    ("bi_faturamento",     ["numfatura", "contrato", "codigocliente", "cliente", "valoremissao", "dataemissao"]),
]

print("\n" + "═" * 90)
print(f"  VALIDAÇÃO SUPABASE — {SUPABASE_URL}")
print("═" * 90)
print(f"\n{'Tabela':<25} {'Registros':>10}  {'Última atualização / amostra':}")
print("-" * 90)

for tabela, cols in TABELAS:
    try:
        res = sb.table(tabela).select("*", count="exact").limit(3).execute()
        count = res.count
        rows  = res.data or []
        if rows:
            # pega valores da primeira linha para as colunas de interesse
            r = rows[0]
            sample_parts = []
            for c in cols[:4]:
                val = r.get(c, "")
                if val is not None and str(val).strip():
                    sample_parts.append(f"{c}={str(val)[:30]}")
            sample = " | ".join(sample_parts)
        else:
            sample = "(sem dados)"
        print(f"{tabela:<25} {count:>10}  {sample}")
    except Exception as e:
        print(f"{tabela:<25}      ERRO  {str(e)[:80]}")

# ── Detalhes: bi_ativos ───────────────────────────────────────────────────────
print("\n" + "─" * 90)
print("  bi_ativos — distribuição por situacao")
print("─" * 90)
try:
    res = sb.table("bi_ativos").select("situacao").execute()
    from collections import Counter
    conta = Counter(r.get("situacao", "?") for r in res.data)
    for sit, n in sorted(conta.items(), key=lambda x: -x[1]):
        print(f"  {sit:<30} {n:>6}")
except Exception as e:
    print(f"  ERRO: {e}")

# ── Detalhes: bi_ativos inconsistentes ───────────────────────────────────────
print("\n" + "─" * 90)
print("  bi_ativos — inconsistentes (INDISPONÍVEL + último mov = RETORNO)")
print("─" * 90)
try:
    res = sb.table("bi_ativos").select("codigo, situacao, ultimo_envret, contrato_atual, inconsistente") \
           .eq("inconsistente", True).limit(10).execute()
    inc = res.data or []
    if inc:
        print(f"  {'Código':<12} {'Situação':<20} {'Env/Ret':<8} {'Contrato'}")
        for r in inc:
            print(f"  {r.get('codigo',''):<12} {r.get('situacao',''):<20} {r.get('ultimo_envret',''):<8} {r.get('contrato_atual','')}")
    else:
        print("  Nenhuma inconsistência encontrada.")
except Exception as e:
    print(f"  ERRO: {e}")

# ── Detalhes: contratos ativos ────────────────────────────────────────────────
print("\n" + "─" * 90)
print("  carteira_contratos — 5 mais recentes")
print("─" * 90)
try:
    res = sb.table("carteira_contratos").select(
        "id, cliente_nome, situacao, data_inicio, data_fim"
    ).order("id", desc=True).limit(5).execute()
    for r in res.data or []:
        print(f"  Contrato {r.get('id','')} | {r.get('cliente_nome','')[:30]:<30} | {r.get('situacao','')} | {r.get('data_inicio','')} → {r.get('data_fim','')}")
except Exception as e:
    print(f"  ERRO: {e}")

# ── Detalhes: últimas OS ──────────────────────────────────────────────────────
print("\n" + "─" * 90)
print("  ordens_servico — 5 mais recentes")
print("─" * 90)
try:
    res = sb.table("ordens_servico").select(
        "numero, tipo, status, cliente, ativo_id, data_abertura"
    ).order("data_abertura", desc=True).limit(5).execute()
    for r in res.data or []:
        print(f"  OS {r.get('numero',''):<8} | {r.get('tipo',''):<15} | {r.get('status',''):<12} | {r.get('cliente','')[:25]:<25} | {r.get('data_abertura','')[:10]}")
except Exception as e:
    print(f"  ERRO: {e}")

print("\n" + "═" * 90 + "\n")
