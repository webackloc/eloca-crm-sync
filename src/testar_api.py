"""
testar_api.py
Testa a conexão com a API do ELOCA usando o token já salvo.
Execute APÓS ter feito login com o inspecionar_eloca.py.

    python3 src/testar_api.py
"""

import asyncio
import json
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

TOKEN_FILE = os.getenv("TOKEN_FILE", "/tmp/eloca_token.json")
SESSION_FILE = os.getenv("SESSION_FILE", "/tmp/eloca_session.json")



async def main():
    # Tenta carregar o token salvo
    token_data = None

    from eloca_auth import obter_token
    print("Obtendo token (reutiliza se válido, ou faz login automático via 2captcha) …")
    try:
        token_data = await obter_token()
    except Exception as e:
        print(f"❌  Falha ao obter token: {e}")
        return

    api_token = token_data.get("api_token", "")
    user_id   = token_data.get("user_id", "")
    empresa   = token_data.get("empresa", "")

    if not api_token:
        print("❌  api_token não encontrado no arquivo de token.")
        print("    Execute: python3 src/inspecionar_eloca.py")
        return

    print(f"\napi_token: {api_token[:20]}…")
    print(f"user_id:   {user_id}")
    print(f"empresa:   {empresa}")

    from eloca_api import ElocaApiClient

    async with ElocaApiClient(api_token, user_id, empresa) as api:

        # 1. Valida usuário
        print("\n[1] Validando token …")
        try:
            user = await api.info_usuario()
            print(f"  ✓ Logado como: {user.get('usuario', user.get('name', 'N/A'))}")
            print(f"    Empresa: {user.get('sigla', user.get('empresa', 'N/A'))}")
        except Exception as e:
            if "401" in str(e) or "Unauthorized" in str(e):
                print("  Token expirado (401). Fazendo novo login …")
                # Remove token antigo e refaz login
                for f in [TOKEN_FILE, SESSION_FILE]:
                    if os.path.exists(f):
                        os.remove(f)
                print("\n  Execute novamente o inspecionar_eloca.py para obter um token fresco:")
                print("  python3 src/inspecionar_eloca.py")
                print("\n  Depois rode este script novamente.")
            else:
                print(f"  ✗ Erro: {e}")
            return

        # 2. Lista ativos
        print("\n[2] Buscando ativos …")
        try:
            ativos = await api.listar_ativos()
            print(f"  ✓ {len(ativos)} ativos encontrados")
            if ativos:
                a = ativos[0]
                print(f"    Exemplo: equip={a.equipamento} | série={a.serie_fabricante} | status={a.status}")
                print(f"    CSV preview:")
                csv = ElocaApiClient.ativos_para_csv(ativos[:3])
                for linha in csv.strip().split("\n"):
                    print(f"      {linha}")
        except Exception as e:
            print(f"  ✗ Erro: {e}")

        # 3. Lista OS (com debug do HTML bruto usando cookies de sessão)
        print("\n[3] Buscando ordens de serviço (últimos 30 dias) …")
        try:
            import httpx, json as _json
            from datetime import datetime, timedelta
            from eloca_api import CGI_BASE, _carregar_cookies_sessao

            session_cookies = _carregar_cookies_sessao()
            print(f"  Cookies de sessão carregados: {list(session_cookies.keys())}")

            hoje    = datetime.today()
            data_de = (hoje - timedelta(days=30)).strftime("%d/%m/%Y")
            data_ate = hoje.strftime("%d/%m/%Y")
            tipos   = ["*1*","*2*","*3*","*4*","*5*","*9*","*11*"]
            filtros = [f"*{i}*" for i in range(37)]

            params = [
                ("ISAJAX","S"),("LOCAL","0"),("CODSTATUS","A"),
                ("TIPO_DATA","0"),("DADATA",data_de),("ADATA",data_ate),
                ("DOCLIENTE","0"),("DOTECNICO","0"),("CODCONTRATO",""),
                ("NEXTFIELD",""),("ID",user_id),("ACAO","25"),
                ("EXTRECNO","0"),("PRG","scp102a1"),
                ("AOCLIENTE","99999999999999"),("AOTECNICO","99999999"),
                ("EMPRESA",empresa),("tableScp102a1New1_length","999"),
            ]
            for t in tipos:   params.append(("TIPO", t))
            for f in filtros: params.append(("FILTROS", f))

            # Chamada COM cookies de sessão
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
                r = await http.get(CGI_BASE, params=params, cookies=session_cookies)
                html = r.text
                print(f"  Status HTTP: {r.status_code} | Tamanho resposta: {len(html)} chars")
                # Salva resposta para análise
                with open("/tmp/eloca_os_raw.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("  Resposta salva em /tmp/eloca_os_raw.html")
                # Mostra primeiros 800 chars para diagnóstico
                print(f"\n  Resposta (primeiros 800 chars):\n  {html[:800]}")

            os_list = await api.listar_os(dias_atras=30)
            print(f"\n  ✓ {len(os_list)} OS parseadas")
            if os_list:
                o = os_list[0]
                print(f"    Exemplo: nº={o.numero} | tipo={o.tipo} | status={o.status} | cliente={o.cliente}")
        except Exception as e:
            print(f"  ✗ Erro: {e}")

        # 4. Tipos de OS
        print("\n[4] Tipos de OS disponíveis …")
        try:
            tipos = await api.listar_tipos_os()
            for t in tipos[:5]:
                print(f"  código={t.get('codigo')} | {t.get('descricao')}")
        except Exception as e:
            print(f"  ✗ Erro: {e}")

        # 5. Clientes
        print("\n[5] Clientes (primeiros 5) …")
        try:
            clientes = await api.listar_clientes()
            for c in clientes[:5]:
                print(f"  código={c.get('codigo')} | {c.get('razaosocial')}")
        except Exception as e:
            print(f"  ✗ Erro: {e}")

    print("\n✓ Teste concluído!")


if __name__ == "__main__":
    asyncio.run(main())
