"""
sync_ativos.py — Weback
Lê CONTROLE_DE_ATIVOS.xlsx e envia para o Supabase via Edge Function.

Rodar:
    python3 sync_ativos.py
"""

import math, requests
from datetime import date
import pandas as pd

# ── Configuração ──────────────────────────────────────────────────────────────
EDGE_URL    = "https://dxkbqxualiqdhvsudshr.supabase.co/functions/v1/sync_controle_ativos_xlsx"
ANON_KEY    = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR4a2JxeHVhbGlxZGh2c3Vkc2hyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYwOTQ5MTQsImV4cCI6MjA5MTY3MDkxNH0.qtv-TUAl05Z3TDpIfH333ZTYtDwestYVh698MjGsGCU"
SYNC_TOKEN  = "723ffa10f209dd99b2c97c5aeb9e6056d40d274373493fb7"
XLSX_PATH   = "CONTROLE_DE_ATIVOS.xlsx"
BATCH_SIZE  = 500

HEADERS = {
    "Content-Type": "application/json",
    "apikey":        ANON_KEY,
    "x-sync-token":  SYNC_TOKEN,
}

# ── Leitura e limpeza ─────────────────────────────────────────────────────────
def ler_planilha():
    print("📂 Lendo CONTROLE_DE_ATIVOS.xlsx ...")
    df = pd.read_excel(XLSX_PATH, sheet_name="Ativos para locação", header=2)

    df = df.rename(columns={
        "CODIGO \nDO ATIVO":                    "codigo_ativo",
        "SERIAL":                               "serial",
        "DATA DA COMPRA":                       "data_compra",
        "DT DE ENTRADA ELOCA":                  "data_entrada_eloca",
        "MÊS DA COMPRA":                        "mes_compra",
        "FORNECEDOR":                           "fornecedor",
        "DESCRIÇÃO DO PRODUTO":                 "descricao_produto",
        "NF":                                   "numero_nf",
        "VALOR DA COMPRA + VL DE PEÇA E DIFAL": "valor_total_aquisicao",
        "VALOR DA COMPRA":                      "valor_compra",
        "VL COMPRA PEÇA\nCOMEÇANDO 15-06-26":  "valor_peca",
        "VL DIFAL\nCOMEÇANDO 15-06-26":        "valor_difal",
        "PMT":                                  "pmt",
        "CONTRATO":                             "contrato",
        "QT MESES DE DEPRECIAÇÃO":              "vida_util_meses",
        "DEPRECIAÇÃO ACUMULADA\n":              "depreciacao_acumulada",
        "VL DO EQUIP":                          "valor_liquido_contabil",
        "FORMA DE PGTO":                        "forma_pagamento",
        "ANOTAÇÃO":                             "anotacao",
    })

    df = df[df["codigo_ativo"].notna()].copy()
    df["codigo_ativo"] = df["codigo_ativo"].astype(str).str.strip()

    for col in ["data_compra", "data_entrada_eloca"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in ["valor_total_aquisicao","valor_compra","valor_peca","valor_difal",
                "pmt","vida_util_meses","depreciacao_acumulada","valor_liquido_contabil"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Vida útil
    def vida_util(row):
        if pd.notna(row.get("vida_util_meses")):
            return int(row["vida_util_meses"])
        desc = str(row.get("descricao_produto","")).upper()
        return 24 if any(x in desc for x in ["SAMSUNG","IPHONE","SMARTPHONE","MOTOROLA"]) else 60
    df["vida_util_meses"] = df.apply(vida_util, axis=1)

    # Categoria
    def categoria(desc):
        d = str(desc).upper()
        if "NOTEBOOK" in d or "LAPTOP" in d: return "NOTEBOOK"
        if "DESKTOP" in d or "COMPUTADOR" in d: return "DESKTOP"
        if "SERVIDOR" in d or "SERVER" in d: return "SERVIDOR"
        if "TABLET" in d or "IPAD" in d: return "TABLET"
        if "IMPRESSORA" in d: return "IMPRESSORA"
        if "MONITOR" in d: return "MONITOR"
        if any(x in d for x in ["SAMSUNG","IPHONE","SMARTPHONE","MOTOROLA"]): return "SMARTPHONE"
        return "OUTROS"
    df["categoria"] = df["descricao_produto"].apply(categoria)

    # Depreciação calculada
    hoje = date.today()
    def calc_depr(row):
        if pd.isna(row.get("data_compra")) or pd.isna(row.get("valor_total_aquisicao")):
            return None, None
        dc = row["data_compra"].date()
        meses = (hoje.year - dc.year)*12 + (hoje.month - dc.month)
        custo = row["valor_total_aquisicao"]
        vu = row.get("vida_util_meses") or 60
        d = round(min(custo, custo * meses / vu), 2)
        return d, round(max(0, custo - d), 2)
    df[["depreciacao_calculada","valor_liquido_calculado"]] = df.apply(
        lambda r: pd.Series(calc_depr(r)), axis=1)
    df["delta_depreciacao"] = (
        df["depreciacao_acumulada"].fillna(0) - df["depreciacao_calculada"].fillna(0)
    ).round(2)

    print(f"✅ {len(df)} ativos processados")
    print(f"   Custo total:   R$ {df['valor_total_aquisicao'].sum():>12,.2f}")
    print(f"   Valor líquido: R$ {df['valor_liquido_contabil'].sum():>12,.2f}")
    return df

# ── Serialização JSON-safe ────────────────────────────────────────────────────
def safe(v):
    if v is None: return None
    if isinstance(v, float) and math.isnan(v): return None
    if hasattr(v, "isoformat"): return v.isoformat()
    if isinstance(v, (int, float)): return round(float(v), 2)
    s = str(v).strip()
    return None if s in ("", "nan", "NaT", "None") else s

# ── Upload via Edge Function ──────────────────────────────────────────────────
def upload(df):
    cols = ["codigo_ativo","serial","data_compra","data_entrada_eloca",
            "mes_compra","fornecedor","descricao_produto","numero_nf","categoria",
            "vida_util_meses","valor_total_aquisicao","valor_compra","valor_peca",
            "valor_difal","pmt","contrato","depreciacao_acumulada",
            "valor_liquido_contabil","depreciacao_calculada","valor_liquido_calculado",
            "delta_depreciacao","forma_pagamento","anotacao"]

    records = [{c: safe(row.get(c)) for c in cols} for _, row in df.iterrows()]
    total   = len(records)
    lotes   = math.ceil(total / BATCH_SIZE)
    gravados = 0

    print(f"\n📤 Enviando {total} ativos em {lotes} lote(s) de {BATCH_SIZE}...")
    for i in range(0, total, BATCH_SIZE):
        lote   = records[i:i+BATCH_SIZE]
        n_lote = i // BATCH_SIZE + 1
        try:
            r = requests.post(EDGE_URL, headers=HEADERS, json=lote, timeout=180)
            r.raise_for_status()
            g = r.json().get("gravados", len(lote))
            gravados += g
            print(f"  ✅ Lote {n_lote}/{lotes} — {gravados}/{total} gravados")
        except Exception as e:
            print(f"  ❌ Lote {n_lote} erro: {e}")

    print(f"\n🎉 Concluído: {gravados}/{total} ativos sincronizados!")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Weback — Sync Controle de Ativos → Supabase WebackOne")
    print("=" * 55)
    df = ler_planilha()
    upload(df)
