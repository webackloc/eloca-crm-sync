"""
check_ativo.py — Consulta rápida de um ativo específico no Supabase
Uso: python3 check_ativo.py 7382
"""
import os, sys
from dotenv import dotenv_values

EQUIPAMENTO = sys.argv[1] if len(sys.argv) > 1 else "7382"

cfg = dotenv_values(".env")
for k in ["PROXY_URL","HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"]:
    os.environ.pop(k, None)

from supabase import create_client
sb = create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_KEY"])

print(f"\n{'═'*70}")
print(f"  ATIVO {EQUIPAMENTO}")
print(f"{'═'*70}")

# ── bi_ativos ────────────────────────────────────────────────────────────────
print("\n[ bi_ativos ]")
res = sb.table("bi_ativos").select("*").eq("codigo", EQUIPAMENTO).execute()
for r in res.data:
    for k, v in r.items():
        if v not in (None, "", "False", "false", False):
            print(f"  {k:<30} {v}")

# ── ativos (ELOCA API) ────────────────────────────────────────────────────────
print("\n[ ativos (ELOCA) ]")
res = sb.table("ativos").select(
    "codigo, descricao, status, cliente, contrato, nome_fantasia, "
    "localizacao, setor, valor_compra, valor_mercado, data_instalacao"
).eq("codigo", EQUIPAMENTO).execute()
for r in res.data:
    for k, v in r.items():
        if v not in (None, ""):
            print(f"  {k:<30} {v}")

# ── bi_ctprod — valor unitário do contrato ────────────────────────────────────
print("\n[ bi_ctprod — valor unitário por contrato ]")
# primeiro pega o contrato atual do ativo
res_a = sb.table("bi_ativos").select("contrato_atual, codigoproduto").eq("codigo", EQUIPAMENTO).execute()
if res_a.data:
    contrato = res_a.data[0].get("contrato_atual", "")
    produto  = res_a.data[0].get("codigoproduto", "")
    print(f"  contrato_atual: {contrato}  |  codigoproduto: {produto}")
    if contrato:
        res_cp = sb.table("bi_ctprod").select(
            "recnum, contrato, produto, produto_descricao, valorunitario, valor"
        ).eq("contrato", contrato).eq("produto", produto).execute()
        for r in res_cp.data:
            print(f"  valorunitario={r.get('valorunitario')}  valor={r.get('valor')}  produto={r.get('produto_descricao','')[:40]}")

# ── bi_movimentacoes — últimos 5 movimentos ───────────────────────────────────
print("\n[ bi_movimentacoes — últimos 5 movimentos ]")
res = sb.table("bi_movimentacoes").select(
    "recnum, equipamento, contrato, envret, data"
).eq("equipamento", EQUIPAMENTO).order("recnum", desc=True).limit(5).execute()
for r in res.data:
    print(f"  {r.get('data','')}  envret={r.get('envret','')}  contrato={r.get('contrato','')}")

print(f"\n{'═'*70}\n")
