"""
eloca_auth.py
Login automático no ELOCA via HTTP puro + 2captcha.
Sem Playwright, sem browser, sem intervenção manual.

Fluxo:
  1. GET api.otimogestor.com.br  → extrai CSRF token
  2. Envia reCAPTCHA para 2captcha → aguarda token (~15-30s)
  3. POST login com EMPRESA + LOGIN + SENHA + g-recaptcha-response
  4. GET /api/user → extrai api_token
  5. Salva api_token + cookies em disco

Custo: ~$3 / 1.000 logins (só faz login quando sessão expira, que é raro).
"""

import asyncio
import json
import logging
import os
import re

import httpx
from dotenv import load_dotenv

# Carrega o .env da pasta do projeto (funciona rodando de qualquer diretório)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)


def _cfg(key, default=""):
    """Lê variável de ambiente em tempo de execução (após load_dotenv)."""
    return os.getenv(key, default)


# ── Configuração (lida dinamicamente para pegar o .env) ──────────────────────
def _get_config():
    return {
        "LOGIN_URL":       _cfg("LOGIN_URL",          "https://api.otimogestor.com.br/"),
        "API_BASE":        _cfg("API_BASE",            "https://api.otimogestor.com.br"),
        "ELOCA_EMPRESA":   _cfg("ELOCA_EMPRESA"),
        "ELOCA_USER":      _cfg("ELOCA_USER"),
        "ELOCA_PASSWORD":  _cfg("ELOCA_PASSWORD"),
        "TWOCAPTCHA_KEY":  _cfg("TWOCAPTCHA_API_KEY"),
        "SESSION_FILE":    _cfg("SESSION_FILE",        "/tmp/eloca_session.json"),
        "TOKEN_FILE":      _cfg("TOKEN_FILE",          "/tmp/eloca_token.json"),
    }

# Mantém variáveis globais para compatibilidade com o resto do código
LOGIN_URL        = _cfg("LOGIN_URL",          "https://api.otimogestor.com.br/")
API_BASE         = _cfg("API_BASE",           "https://api.otimogestor.com.br")
SESSION_FILE     = _cfg("SESSION_FILE",       "/tmp/eloca_session.json")
TOKEN_FILE       = _cfg("TOKEN_FILE",         "/tmp/eloca_token.json")

# Sitekey do reCAPTCHA do ELOCA (extraída da inspeção)
RECAPTCHA_SITEKEY = "6LeL9dYrAAAAANo8yvYvxJG3jNum_0lVZdtHKkZE"

# User-agent realista
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ── Funções de persistência ───────────────────────────────────────────────────

def carregar_token():
    path = _cfg("TOKEN_FILE", "/tmp/eloca_token.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def salvar_token(dados: dict):
    path = _cfg("TOKEN_FILE", "/tmp/eloca_token.json")
    pasta = os.path.dirname(path)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(path, "w") as f:
        json.dump(dados, f)
    logger.info("Token salvo em %s", path)


def salvar_cookies(cookies: dict):
    path = _cfg("SESSION_FILE", "/tmp/eloca_session.json")
    state = {"cookies": [{"name": k, "value": v, "domain": "otimogestor.com.br"} for k, v in cookies.items()]}
    with open(path, "w") as f:
        json.dump(state, f)
    logger.info("Cookies de sessão salvos em %s", path)


def carregar_cookies() -> dict:
    path = _cfg("SESSION_FILE", "/tmp/eloca_session.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            state = json.load(f)
        return {c["name"]: c["value"] for c in state.get("cookies", [])}
    except Exception:
        return {}


# ── 2captcha ──────────────────────────────────────────────────────────────────

async def resolver_recaptcha_v2(page_url: str, sitekey: str) -> str:
    TWOCAPTCHA_KEY = _cfg("TWOCAPTCHA_API_KEY")
    """
    Resolve reCAPTCHA v2 via 2captcha.
    Retorna o token para injetar no formulário.
    Tempo médio: 15-30 segundos.
    """
    if not TWOCAPTCHA_KEY:
        raise ValueError("TWOCAPTCHA_API_KEY não configurada no .env")

    logger.info("Enviando reCAPTCHA para 2captcha (sitekey=%s…)", sitekey[:20])

    async with httpx.AsyncClient(timeout=120, headers={"User-Agent": UA}) as client:
        # 1. Submete o desafio
        r = await client.post(
            "https://2captcha.com/in.php",
            data={
                "key":       TWOCAPTCHA_KEY,
                "method":    "userrecaptcha",
                "googlekey": sitekey,
                "pageurl":   page_url,
                "json":      1,
            },
        )
        resp = r.json()
        if resp.get("status") != 1:
            raise RuntimeError(f"2captcha rejeitou: {resp}")

        captcha_id = resp["request"]
        logger.info("CAPTCHA submetido (id=%s). Aguardando resolução …", captcha_id)

        # 2. Aguarda resolução com poll a cada 5s (máx 2 min)
        for tentativa in range(24):
            await asyncio.sleep(5)
            res = await client.get(
                "https://2captcha.com/res.php",
                params={"key": TWOCAPTCHA_KEY, "action": "get",
                        "id": captcha_id, "json": 1},
            )
            result = res.json()
            if result.get("status") == 1:
                token = result["request"]
                logger.info("CAPTCHA resolvido em ~%ds.", (tentativa + 1) * 5)
                return token
            if "ERROR" in str(result.get("request", "")):
                raise RuntimeError(f"2captcha erro: {result['request']}")
            logger.debug("  2captcha: aguardando… tentativa %d/24", tentativa + 1)

        raise TimeoutError("2captcha: timeout aguardando resolução do CAPTCHA.")


# ── Login HTTP puro ───────────────────────────────────────────────────────────

def _extrair_sitekey(html: str) -> str:
    """Extrai a sitekey do reCAPTCHA do HTML da página de login."""
    padroes = [
        r'data-sitekey=["\']([^"\']+)["\']',
        r'grecaptcha\.execute\(["\']([^"\']+)["\']',
        r'sitekey["\s:=]+["\']([^"\']+)["\']',
        r'"sitekey"\s*:\s*"([^"]+)"',
        r'recaptcha[^>]+k=([A-Za-z0-9_-]{30,50})',
    ]
    for padrao in padroes:
        m = re.search(padrao, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


async def fazer_login() -> dict:
    cfg = _get_config()
    """
    Faz login completo no ELOCA via HTTP puro + 2captcha.
    Retorna: {"api_token": "...", "user_id": "...", "empresa": "..."}
    """
    logger.info("Iniciando login automático no ELOCA …")

    headers = {
        "User-Agent":                UA,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language":           "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding":           "gzip, deflate, br",
        "DNT":                       "1",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Sec-Fetch-User":            "?1",
        "Cache-Control":             "max-age=0",
    }

    # Proxy opcional (para contornar bloqueio de IP em datacenters)
    proxy_url = _cfg("PROXY_URL")
    proxy_kwargs = {"proxy": proxy_url} if proxy_url else {}
    if proxy_url:
        logger.info("Usando proxy: %s…", proxy_url[:30])

    async with httpx.AsyncClient(
        timeout=60,
        headers=headers,
        follow_redirects=True,
        **proxy_kwargs,
    ) as client:

        # ── Passo 1: GET página de login → extrai CSRF token ──────────────
        logger.info("Carregando página de login …")
        r = await client.get(cfg["LOGIN_URL"])
        r.raise_for_status()

        csrf = re.search(r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']', r.text)
        if not csrf:
            csrf = re.search(r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']', r.text)
        csrf_token = csrf.group(1) if csrf else ""
        logger.info("CSRF token: %s…", csrf_token[:20] if csrf_token else "NÃO ENCONTRADO")

        # Extrai sitekey do reCAPTCHA diretamente do HTML da página de login
        sitekey = _extrair_sitekey(r.text) or RECAPTCHA_SITEKEY
        logger.info("reCAPTCHA sitekey: %s…", sitekey[:30])

        # ── Passo 2: Resolve reCAPTCHA via 2captcha ───────────────────────
        captcha_token = await resolver_recaptcha_v2(cfg["LOGIN_URL"], sitekey)

        # ── Passo 3: POST do formulário de login ──────────────────────────
        logger.info("Submetendo login …")
        payload = {
            "_token":               csrf_token,
            "EMPRESA":              cfg["ELOCA_EMPRESA"],
            "LOGIN":                cfg["ELOCA_USER"],
            "SENHA":                cfg["ELOCA_PASSWORD"],
            "g-recaptcha-response": captcha_token,
        }
        r_login = await client.post(cfg["LOGIN_URL"], data=payload)

        # Verifica se o login foi bem-sucedido (deve ter redirecionado para o app)
        logger.info("URL após POST de login: %s", r_login.url)
        if "weback.app.otimogestor.com.br" not in str(r_login.url):
            # Mostra os primeiros 400 chars da resposta para diagnóstico
            preview = r_login.text[:400].replace("\n", " ").strip()
            logger.error("Resposta do servidor: %s", preview)
            if "incorreto" in r_login.text.lower() or "inválido" in r_login.text.lower():
                raise RuntimeError(
                    f"Login falhou — verifique ELOCA_EMPRESA, ELOCA_USER e ELOCA_PASSWORD no .env\n"
                    f"Resposta do servidor: {preview[:200]}"
                )
            if "recaptcha" in r_login.text.lower():
                raise RuntimeError("Login falhou: CAPTCHA rejeitado pelo servidor.")
            raise RuntimeError(f"Login não redirecionou para o app. Resposta: {preview[:200]}")

        # Salva os cookies de sessão (necessários para o CGI de OS)
        session_cookies = dict(client.cookies)
        salvar_cookies(session_cookies)
        logger.info("Login realizado. %d cookies salvos.", len(session_cookies))

        # ── Passo 4: Extrai api_token da URL de redirect ───────────────────
        # O ELOCA redireciona para:
        # /php/logins.php?token={user_id}&api_token={api_token}
        api_token = None
        user_id   = ""

        # Varre o histórico de redirecionamentos para achar a URL com api_token
        for resp in r_login.history + [r_login]:
            url_str = str(resp.url)
            if "api_token=" in url_str:
                from urllib.parse import urlparse, parse_qs
                params    = parse_qs(urlparse(url_str).query)
                api_token = params.get("api_token", [None])[0]
                user_id   = params.get("token", [""])[0]
                logger.info("api_token extraído da URL de redirect.")
                break

        # Fallback: tenta /api/user com os cookies
        if not api_token:
            logger.info("api_token não encontrado no redirect — tentando /api/user com cookies …")
            try:
                r_user = await client.get(
                    f"{cfg['API_BASE']}/api/user",
                    cookies=session_cookies,
                )
                if r_user.status_code == 200:
                    user_data = r_user.json()
                    api_token = user_data.get("api_token")
                    user_id   = str(user_data.get("id", ""))
            except Exception as e:
                logger.warning("Fallback /api/user falhou: %s", e)

        if not api_token:
            raise RuntimeError(
                "Não foi possível extrair o api_token após login bem-sucedido."
            )

        token_data = {
            "api_token": api_token,
            "user_id":   user_id,
            "empresa":   cfg["ELOCA_EMPRESA"],
        }
        salvar_token(token_data)
        logger.info("api_token obtido! user_id=%s", user_id)
        return token_data


# ── Verificação de token ──────────────────────────────────────────────────────

async def token_valido(api_token: str) -> bool:
    """Verifica se o api_token ainda é aceito."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{API_BASE}/api/user", params={"api_token": api_token})
            return r.status_code == 200 and "api_token" in r.json()
    except Exception:
        return False


# ── Interface principal ───────────────────────────────────────────────────────

async def obter_token(forcar_novo_login: bool = False, max_tentativas: int = 3) -> dict:
    """
    Retorna um token válido.
    - Se já existe token válido em disco, reutiliza.
    - Caso contrário, faz login automático via 2captcha (até max_tentativas).
    """
    if not forcar_novo_login:
        dados = carregar_token()
        if dados and await token_valido(dados["api_token"]):
            logger.info("Token reutilizado (user_id=%s).", dados.get("user_id"))
            return dados
        if dados:
            logger.info("Token expirado. Renovando via 2captcha …")

    ultimo_erro = None
    for tentativa in range(1, max_tentativas + 1):
        try:
            if tentativa > 1:
                logger.info("Tentativa %d/%d …", tentativa, max_tentativas)
                await asyncio.sleep(5)
            return await fazer_login()
        except Exception as e:
            ultimo_erro = e
            logger.warning("Tentativa %d falhou: %s", tentativa, e)

    raise RuntimeError(f"Login falhou após {max_tentativas} tentativas. Último erro: {ultimo_erro}")


# ── Teste standalone ──────────────────────────────────────────────────────────

async def _main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    dados = await obter_token(forcar_novo_login=True)
    print(f"\n✓ api_token: {dados['api_token'][:30]}…")
    print(f"  user_id:   {dados['user_id']}")
    print(f"  empresa:   {dados['empresa']}")


if __name__ == "__main__":
    asyncio.run(_main())
