"""
diagnostico_supabase_schema.py — Verifica o que existe no Supabase:
  - Quais tabelas existem e quantas linhas cada uma tem
  - Schema (colunas) das tabelas relevantes: assets, contract_items, ativos, carteira_contratos
  - Amostra de dados de cada tabela

Objetivo: entender de onde vem (ou deve vir) a ligação equipamento -> produto
"""
import os
import json
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL e SUPABASE_SERVICE_KEY são obrigatórios")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
SEP = "═" * 70

TABELAS = [
    "assets",
    "contract_items",
    "contracts",
    "ativos",
    "carteira_contratos",
    "bi_movimentacoes",
    "bi_ctprod",
    "bi_faturamento",
]

print(f"\n{SEP}")
print("DIAGNÓSTICO SUPABASE — TABELAS E CONTAGENS")
print(SEP)

for tabela in TABELAS:
    try:
        # count
        res = sb.table(tabela).select("*", count="exact").limit(0).execute()
        count = res.count if hasattr(res, "count") else "?"
        print(f"  {tabela:<30} {count:>8} linhas")
    except Exception as e:
        print(f"  {tabela:<30}   ERRO: {e}")

# ── Schema via information_schema ─────────────────────────────────────────────
print(f"\n{SEP}")
print("SCHEMA DAS TABELAS (information_schema)")
print(SEP)

# Supabase permite queries SQL via rpc ou via rest sobre information_schema
# Usamos o client diretamente via postgrest
for tabela in TABELAS:
    try:
        res = sb.table(tabela).select("*").limit(1).execute()
        if res.data:
            colunas = list(res.data[0].keys())
            print(f"\n  {tabela} — colunas ({len(colunas)}):")
            for col in colunas:
                val = res.data[0][col]
                tipo = type(val).__name__ if val is not None else "null"
                print(f"    {col:<35} exemplo: {str(val)[:60]}  ({tipo})")
        else:
            # tabela existe mas está vazia — pegar schema via select vazio
            print(f"\n  {tabela} — VAZIA (0 linhas, schema indisponível via REST)")
    except Exception as e:
        print(f"\n  {tabela} — ERRO ao ler: {e}")

# ── Amostra de assets ─────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("AMOSTRA: tabela 'assets' (10 primeiras linhas)")
print(SEP)
try:
    res = sb.table("assets").select("*").limit(10).execute()
    if res.data:
        for r in res.data:
            print(f"  {json.dumps(r, default=str, ensure_ascii=False)}")
    else:
        print("  (vazia)")
except Exception as e:
    print(f"  ERRO: {e}")

# ── Amostra de contract_items ─────────────────────────────────────────────────
print(f"\n{SEP}")
print("AMOSTRA: tabela 'contract_items' (10 primeiras linhas)")
print(SEP)
try:
    res = sb.table("contract_items").select("*").limit(10).execute()
    if res.data:
        for r in res.data:
            print(f"  {json.dumps(r, default=str, ensure_ascii=False)}")
    else:
        print("  (vazia)")
except Exception as e:
    print(f"  ERRO: {e}")

# ── Amostra de ativos ─────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("AMOSTRA: tabela 'ativos' (10 primeiras linhas)")
print(SEP)
try:
    res = sb.table("ativos").select("*").limit(10).execute()
    if res.data:
        for r in res.data:
            print(f"  {json.dumps(r, default=str, ensure_ascii=False)}")
    else:
        print("  (vazia)")
except Exception as e:
    print(f"  ERRO: {e}")

print(f"\n{SEP}")
print("✓ Diagnóstico concluído.")
