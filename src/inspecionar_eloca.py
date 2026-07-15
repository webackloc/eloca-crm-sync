"""
inspecionar_eloca.py — v3
Intercepta as chamadas de API que o ELOCA faz enquanto você navega.
Objetivo: descobrir os endpoints reais para usar no lugar do scraping de DOM.

Execute:
    python3 src/inspecionar_eloca.py
"""

import asyncio
import json
import logging
import os
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Request, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

URL          = os.getenv("ELOCA_URL",    "https://weback.app.otimogestor.com.br/")
SESSION_FILE = os.getenv("SESSION_FILE", "/tmp/eloca_session.json")
TOKEN_FILE   = os.getenv("TOKEN_FILE",   "/tmp/eloca_token.json")
API_BASE     = os.getenv("API_BASE",     "https://api.otimogestor.com.br")
OUTPUT_DIR   = "/tmp/eloca_inspect"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Guarda todas as chamadas de API capturadas
api_calls: list = []
captured_token: dict = {}


def on_request(request: Request):
    """Registra toda chamada de rede que sair do browser."""
    url = request.url
    parsed = urlparse(url)

    # Filtra só chamadas relevantes (ignora imagens, fonts, etc.)
    ignorar = (".png", ".jpg", ".svg", ".ico", ".woff", ".css", ".js")
    if any(url.endswith(ext) for ext in ignorar):
        return

    entry = {
        "method":  request.method,
        "url":     url,
        "host":    parsed.netloc,
        "path":    parsed.path,
        "headers": dict(request.headers),
        "post_data": None,
    }
    try:
        entry["post_data"] = request.post_data
    except Exception:
        pass

    api_calls.append(entry)


async def on_response(response: Response):
    """Captura o corpo de respostas JSON da API e extrai o api_token."""
    global captured_token
    url = response.url
    if "api.otimogestor" not in url and "otimogestor.com.br" not in url:
        return
    ct = response.headers.get("content-type", "")
    if "json" not in ct:
        return
    try:
        body = await response.json()
        # Captura token da resposta de /api/user
        if "/api/user" in url and isinstance(body, dict) and "api_token" in body:
            captured_token = {
                "api_token": body["api_token"],
                "user_id":   str(body.get("id", "")),
                "empresa":   str(body.get("empresa", "")),
            }
        # Encontra o entry correspondente e adiciona o response
        for entry in reversed(api_calls):
            if entry["url"] == url and "response" not in entry:
                entry["response_preview"] = str(body)[:300]
                break
    except Exception:
        pass


async def salvar_screenshot(page, nome):
    path = f"{OUTPUT_DIR}/{nome}.png"
    await page.screenshot(path=path, full_page=True)
    log.info("  Screenshot salvo: %s", path)


async def esperar_rede_quieta(page):
    """Aguarda a rede ficar quieta (JS terminar de carregar dados)."""
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    await asyncio.sleep(1)  # pequena pausa extra


async def capturar_dom(page) -> dict:
    """Captura estrutura completa do DOM renderizado."""
    return await page.evaluate("""
        () => {
            // Tenta encontrar listas/grids de dados (não só <table>)
            const seletores = [
                'table', 'tbody tr', '[class*="grid"]', '[class*="list"]',
                '[class*="card"]', '[class*="row"]', '[class*="item"]',
                '[class*="registro"]', '[class*="equip"]', '[class*="ativo"]'
            ];

            const encontrados = {};
            for (const sel of seletores) {
                const els = document.querySelectorAll(sel);
                if (els.length > 0) {
                    encontrados[sel] = {
                        count: els.length,
                        primeiro_html: els[0]?.outerHTML?.slice(0, 400) || ''
                    };
                }
            }

            // Captura texto de todos os elementos com dados (primeiros 5)
            const textos = Array.from(document.querySelectorAll(
                '[class*="equip"], [class*="ativo"], [class*="os"], [class*="ordem"], ' +
                '[class*="servico"], [class*="contrato"], [class*="cliente"]'
            )).slice(0, 5).map(el => ({
                tag: el.tagName,
                classes: el.className.trim(),
                texto: el.innerText?.trim().slice(0, 200)
            }));

            // Captura o HTML completo do main/conteúdo principal
            const main = document.querySelector(
                'main, #app, #root, .app-content, .main-content, .content, [role="main"]'
            );

            return {
                url: window.location.href,
                encontrados,
                textos,
                main_classes: main?.className || '',
                main_html_preview: main?.innerHTML?.slice(0, 1000) || document.body?.innerHTML?.slice(0, 1000)
            };
        }
    """)


def aguardar_usuario(mensagem):
    log.info("\n" + "─" * 60)
    log.info(mensagem)
    log.info("─" * 60)
    input("  >>> Pressione ENTER para continuar: ")


async def main():
    log.info("=" * 60)
    log.info("ELOCA Inspector v3 — Interceptador de API")
    log.info("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=100,
            args=["--no-sandbox"],
        )

        context_opts = dict(
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE) as f:
                context_opts["storage_state"] = json.load(f)
            log.info("Sessão carregada de %s", SESSION_FILE)

        context = await browser.new_context(**context_opts)
        page    = await context.new_page()
        page.set_default_timeout(60_000)

        # Ativa interceptação de rede
        page.on("request",  on_request)
        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))

        # ── PASSO 1: Abre / Login ────────────────────────────────────────
        log.info("\n[PASSO 1] Abrindo o ELOCA …")
        await page.goto(URL, wait_until="networkidle")
        await salvar_screenshot(page, "01_inicio")

        em_login = await page.query_selector('input[name="LOGIN"], input[name="SENHA"]') is not None
        if em_login:
            aguardar_usuario(
                "Você está na tela de LOGIN.\n"
                "Faça login manualmente (preencha empresa, usuário, senha e CAPTCHA).\n"
                "Após entrar no sistema, pressione ENTER."
            )
            await esperar_rede_quieta(page)
            state = await context.storage_state()
            with open(SESSION_FILE, "w") as f:
                json.dump(state, f)
            log.info("  ✓ Sessão salva em: %s", SESSION_FILE)
        else:
            log.info("  Já está logado!")

        # Aguarda /api/user ser chamado para capturar o token
        await esperar_rede_quieta(page)
        if captured_token:
            with open(TOKEN_FILE, "w") as f:
                json.dump(captured_token, f)
            log.info("  ✓ Token salvo em: %s  (api_token=%s…)",
                     TOKEN_FILE, captured_token["api_token"][:20])

        await salvar_screenshot(page, "02_pos_login")
        log.info("\n  Chamadas de API registradas até agora: %d", len(api_calls))

        # ── PASSO 2: Equipamentos ────────────────────────────────────────
        api_calls_antes = len(api_calls)
        aguardar_usuario(
            "Navegue até EQUIPAMENTOS / ATIVOS no menu do ELOCA.\n"
            "Aguarde a lista carregar completamente e pressione ENTER."
        )
        await esperar_rede_quieta(page)
        await salvar_screenshot(page, "03_equipamentos")

        novas_chamadas = api_calls[api_calls_antes:]
        log.info("\n[PASSO 2] Chamadas de API durante navegação para Equipamentos: %d", len(novas_chamadas))
        for c in novas_chamadas:
            log.info("  %s %s", c["method"], c["url"])
            if c.get("post_data"):
                log.info("    POST body: %s", str(c["post_data"])[:200])
            if c.get("response_preview"):
                log.info("    Response:  %s", c["response_preview"][:200])

        dom_equip = await capturar_dom(page)
        log.info("\n  DOM Equipamentos:")
        log.info("    URL:     %s", dom_equip["url"])
        log.info("    Elementos encontrados: %s", list(dom_equip["encontrados"].keys()))
        for sel, info in dom_equip["encontrados"].items():
            log.info("    [%s] count=%d  html_preview=%s", sel, info["count"], info["primeiro_html"][:150])
        log.info("    Main HTML preview: %s", dom_equip["main_html_preview"][:400])

        # Salva HTML completo
        with open(f"{OUTPUT_DIR}/equipamentos.html", "w", encoding="utf-8") as f:
            f.write(await page.content())

        # ── PASSO 3: Ordens de Serviço ───────────────────────────────────
        api_calls_antes = len(api_calls)
        aguardar_usuario(
            "Navegue até ORDENS DE SERVIÇO no menu do ELOCA.\n"
            "Aguarde a lista carregar completamente e pressione ENTER."
        )
        await esperar_rede_quieta(page)
        await salvar_screenshot(page, "04_ordens_servico")

        novas_chamadas = api_calls[api_calls_antes:]
        log.info("\n[PASSO 3] Chamadas de API durante navegação para OS: %d", len(novas_chamadas))
        for c in novas_chamadas:
            log.info("  %s %s", c["method"], c["url"])
            if c.get("post_data"):
                log.info("    POST body: %s", str(c["post_data"])[:200])
            if c.get("response_preview"):
                log.info("    Response:  %s", c["response_preview"][:200])

        dom_os = await capturar_dom(page)
        log.info("\n  DOM Ordens de Serviço:")
        log.info("    URL:     %s", dom_os["url"])
        for sel, info in dom_os["encontrados"].items():
            log.info("    [%s] count=%d  html=%s", sel, info["count"], info["primeiro_html"][:150])
        log.info("    Main HTML preview: %s", dom_os["main_html_preview"][:400])

        with open(f"{OUTPUT_DIR}/ordens_servico.html", "w", encoding="utf-8") as f:
            f.write(await page.content())

        # ── Salva todas as chamadas de API ───────────────────────────────
        with open(f"{OUTPUT_DIR}/api_calls.json", "w", encoding="utf-8") as f:
            json.dump(api_calls, f, ensure_ascii=False, indent=2)

        log.info("\n" + "=" * 60)
        log.info("TOTAL de chamadas de API capturadas: %d", len(api_calls))
        log.info("Salvas em: %s/api_calls.json", OUTPUT_DIR)
        log.info("=" * 60)

        # Imprime resumo das chamadas únicas
        urls_unicas = sorted(set(c["url"] for c in api_calls))
        log.info("\nURLs únicas de API chamadas:")
        for u in urls_unicas:
            log.info("  %s", u)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
