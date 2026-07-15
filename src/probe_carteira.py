"""
probe_carteira.py — Testa candidatos de PRG para a carteira de contratos via CGI.

Uso:
  fly ssh console -a eloca-crm-sync
  python src/probe_carteira.py

Analisa a resposta de cada PRG candidato e exibe:
  - Tamanho da resposta
  - Trecho do HTML (para identificar colunas/dados)
  - Se contém palavras-chave de contrato
"""

import asyncio
import json
import os
import sys

import httpx

SESSION_FILE = os.getenv("SESSION_FILE", "/data/eloca_session.json")
TOKEN_FILE   = os.getenv("TOKEN_FILE",   "/data/eloca_token.json")
CGI_BASE     = os.getenv("CGI_BASE",     "https://weback.app.otimogestor.com.br/cgi-bin/exec.cgi")
PROXY_URL    = os.getenv("PROXY_URL")

# PRG candidatos para carteira de contratos
CANDIDATOS = [
    "scp101",
    "scp101a1",
    "scp201",
    "scp201a1",
    "scp301",
    "scp301a1",
    "scp401",
    "scp401a1",
    "scp501",
    "scp501a1",
    "scp601",
    "scp601a1",
]

KEYWORDS_CONTRATO = [
    "contrato", "vigência", "vigencia", "cliente", "equipamento",
    "inicio", "término", "termino", "valor", "mensal", "locação"
]


def carregar_sessao():
    with open(SESSION_FILE) as f:
        state = json.load(f)
    cookies = {}
    for c in state.get("cookies", []):
        if "otimogestor" in c.get("domain", ""):
            cookies[c["name"]] = c["value"]
    return cookies


def carregar_token():
    with open(TOKEN_FILE) as f:
        data = json.load(f)
    return data


async def testar_prg(client, cookies, user_id, empresa, prg):
    params = [
        ("ISAJAX",  "S"),
        ("ACAO",    "25"),
        ("ID",      user_id),
        ("EMPRESA", empresa),
        ("PRG",     prg),
        (f"table{prg.capitalize()}New1_length", "999"),
    ]
    try:
        r = await client.get(CGI_BASE, params=params, cookies=cookies, timeout=20)
        html = r.text
        size = len(html)

        if size < 500:
            resumo = f"VAZIO ({size} chars)"
            score = 0
        elif "Erro de segurança" in html or "relogar" in html.lower():
            resumo = "SESSÃO INVÁLIDA"
            score = 0
        else:
            encontradas = [kw for kw in KEYWORDS_CONTRATO if kw.lower() in html.lower()]
            score = len(encontradas)
            trecho = html[200:500].replace("\n", " ").strip()
            resumo = f"{size} chars | keywords={encontradas} | trecho: {trecho[:150]}"

        return prg, score, resumo
    except Exception as e:
        return prg, -1, f"ERRO: {e}"


async def main():
    print("=" * 70)
    print("PROBE: Carteira de Contratos — testando PRG candidatos via CGI")
    print("=" * 70)

    cookies = carregar_sessao()
    token_data = carregar_token()
    user_id = token_data.get("user_id", "")
    empresa = token_data.get("empresa", "WEBACK")

    print(f"user_id={user_id}  empresa={empresa}  cookies={len(cookies)}\n")

    proxy_kwargs = {"proxy": PROXY_URL} if PROXY_URL else {}
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        follow_redirects=True,
        **proxy_kwargs,
    ) as client:
        resultados = []
        for prg in CANDIDATOS:
            print(f"  Testando {prg:12s} ...", end=" ", flush=True)
            prg_name, score, resumo = await testar_prg(client, cookies, user_id, empresa, prg)
            print(f"score={score}  {resumo[:120]}")
            resultados.append((score, prg_name, resumo))
            await asyncio.sleep(0.5)

    print("\n" + "=" * 70)
    print("RANKING (maior score = mais provável):")
    for score, prg, resumo in sorted(resultados, reverse=True):
        if score > 0:
            print(f"  [{score:2d}] {prg:12s} — {resumo[:100]}")

    print("\nSe score > 3, esse PRG é o candidato para carteira de contratos.")


if __name__ == "__main__":
    asyncio.run(main())
