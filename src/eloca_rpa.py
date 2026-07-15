"""
ELOCA RPA - Robotic Process Automation
Acessa o ERP ELOCA via browser headless (Playwright) para:
  - Extrair relatório de ativos/equipamentos
  - Extrair ordens de serviço (OS)
  - Criar novas ordens de serviço

Configurado para rodar no Fly.io (Linux, sem interface gráfica).
"""

import asyncio
import csv
import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

ELOCA_URL      = os.getenv("ELOCA_URL", "https://weback.app.otimogestor.com.br/")
ELOCA_EMPRESA     = os.getenv("ELOCA_EMPRESA", "WEBACK")
ELOCA_USER     = os.getenv("ELOCA_USER", "LEONARDO")
ELOCA_PASSWORD = os.getenv("ELOCA_PASSWORD", "Ferrari32@")

# Aguarda até X segundos por elementos antes de lançar erro
DEFAULT_TIMEOUT = int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "30000"))

# ── Estratégia de CAPTCHA ────────────────────────────────────────────────────
# Opções: "cookies" (padrão) | "2captcha" | "stealth"
#   cookies  → reutiliza sessão salva; só resolve CAPTCHA uma vez manualmente
#   2captcha → resolve automaticamente via API (requer TWOCAPTCHA_API_KEY)
#   stealth  → usa playwright-stealth para se passar por humano (sem API key)
CAPTCHA_STRATEGY = os.getenv("CAPTCHA_STRATEGY", "cookies")

# Arquivo onde os cookies de sessão são persistidos (pode ser volume no Fly.io)
SESSION_FILE = os.getenv("SESSION_FILE", "/tmp/eloca_session.json")

# Chave da API do 2captcha (https://2captcha.com) — só necessária se CAPTCHA_STRATEGY=2captcha
TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY", "")


# ---------------------------------------------------------------------------
# Modelos de dados
# ---------------------------------------------------------------------------

@dataclass
class Ativo:
    id: str = ""
    codigo: str = ""
    descricao: str = ""
    numero_serie: str = ""
    cliente: str = ""
    contrato: str = ""
    localizacao: str = ""
    status: str = ""
    data_instalacao: str = ""
    extras: dict = field(default_factory=dict)


@dataclass
class OrdemServico:
    id: str = ""
    numero: str = ""
    tipo: str = ""
    status: str = ""
    cliente: str = ""
    ativo_id: str = ""
    descricao: str = ""
    tecnico: str = ""
    data_abertura: str = ""
    data_fechamento: str = ""
    extras: dict = field(default_factory=dict)


@dataclass
class NovaOS:
    """Dados para criação de uma nova OS no ELOCA."""
    cliente: str
    ativo_id: str
    tipo_servico: str
    descricao: str
    tecnico: str = ""
    data_prevista: str = ""
    prioridade: str = "Normal"


# ---------------------------------------------------------------------------
# Cliente RPA
# ---------------------------------------------------------------------------

class ElocaRPA:
    """
    Controla o browser para interagir com o ELOCA.
    Use como context manager:

        async with ElocaRPA() as rpa:
            ativos = await rpa.extrair_ativos()
            os_list = await rpa.extrair_ordens_servico()
    """

    def __init__(
        self,
        url: str = ELOCA_URL,
        usuario: str = ELOCA_USER,
        senha: str = ELOCA_PASSWORD,
        headless: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
        captcha_strategy: str = CAPTCHA_STRATEGY,
        session_file: str = SESSION_FILE,
        twocaptcha_key: str = TWOCAPTCHA_API_KEY,
    ):
        self.url = url.rstrip("/")
        self.usuario = usuario
        self.senha = senha
        self.headless = headless
        self.timeout = timeout
        self.captcha_strategy = captcha_strategy
        self.session_file = session_file
        self.twocaptcha_key = twocaptcha_key

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self):
        await self._iniciar()
        return self

    async def __aexit__(self, *_):
        await self._encerrar()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def _iniciar(self):
        self._playwright = await async_playwright().start()

        launch_args = ["--no-sandbox", "--disable-dev-shm-usage"]

        # Stealth: argumentos adicionais para parecer mais com browser humano
        if self.captcha_strategy == "stealth":
            launch_args += [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ]

        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
        )

        context_opts = dict(
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            # User-agent realista para evitar detecção de bot
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        # Carrega cookies de sessão salva (estratégia "cookies")
        cookies_salvos = self._ler_cookies_salvos()
        if cookies_salvos:
            context_opts["storage_state"] = cookies_salvos
            logger.info("Sessão anterior carregada de %s", self.session_file)

        self._context = await self._browser.new_context(**context_opts)

        # Stealth: esconde navigator.webdriver e outras marcas de automação
        if self.captcha_strategy == "stealth":
            await self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt'] });
                window.chrome = { runtime: {} };
            """)

        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout)
        logger.info("Browser iniciado (estratégia CAPTCHA: %s).", self.captcha_strategy)

    async def _encerrar(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser encerrado.")

    # ------------------------------------------------------------------
    # Login (com suporte a CAPTCHA)
    # ------------------------------------------------------------------

    async def login(self) -> bool:
        """
        Faz login no ELOCA com suporte a CAPTCHA.

        Estratégias (controladas por CAPTCHA_STRATEGY):
          - cookies  → verifica se a sessão salva ainda é válida; se não,
                       pede intervenção manual UMA vez e salva os cookies.
          - 2captcha → resolve o reCAPTCHA automaticamente via API 2captcha.
          - stealth  → tenta login sem resolver o CAPTCHA, confiando no
                       disfarce de browser humano (funciona em alguns casos).
        """
        # Tenta reutilizar sessão existente antes de qualquer coisa
        if await self._sessao_valida():
            logger.info("Sessão ativa reaproveitada — sem necessidade de login.")
            return True

        logger.info("Sessão inválida ou inexistente — iniciando login …")
        page = self._page
        await page.goto(self.url, wait_until="networkidle")

        # -----------------------------------------------------------------
        # ATENÇÃO: seletores abaixo precisam ser confirmados inspecionando
        # o HTML real do ELOCA (rode com headless=False na primeira vez).
        # -----------------------------------------------------------------

        # Preenche usuário com delay humano
        await page.fill('input[name="login"], input[type="email"], #usuario', "")
        await page.type('input[name="login"], input[type="email"], #usuario',
                        self.usuario, delay=80)

        # Preenche senha com delay humano
        await page.fill('input[name="password"], input[type="password"], #senha', "")
        await page.type('input[name="password"], input[type="password"], #senha',
                        self.senha, delay=80)

        # ── Tratamento do CAPTCHA ─────────────────────────────────────────
        captcha_resolvido = await self._resolver_captcha()
        if not captcha_resolvido:
            logger.error("Não foi possível resolver o CAPTCHA.")
            await page.screenshot(path="/tmp/eloca_captcha_erro.png")
            return False

        # Submete formulário
        await page.click('button[type="submit"], input[type="submit"], .btn-login, #entrar')

        # Aguarda indicador de sessão autenticada
        try:
            await page.wait_for_selector(
                '.menu-principal, #dashboard, .sidebar, nav.main-nav, [data-autenticado]',
                timeout=20000,
            )
        except Exception:
            logger.error("Falha no login — verifique credenciais ou seletores.")
            await page.screenshot(path="/tmp/eloca_login_erro.png")
            return False

        # Salva sessão para os próximos ciclos
        await self._salvar_cookies()
        logger.info("Login realizado com sucesso. Sessão salva em %s", self.session_file)
        return True

    # ------------------------------------------------------------------
    # Métodos auxiliares de CAPTCHA
    # ------------------------------------------------------------------

    async def _resolver_captcha(self) -> bool:
        """
        Despacha para a estratégia de CAPTCHA configurada.
        Retorna True se o CAPTCHA foi resolvido (ou não há CAPTCHA).
        """
        page = self._page

        # Detecta se há CAPTCHA na página
        tem_recaptcha = await page.query_selector(
            'iframe[src*="recaptcha"], .g-recaptcha, div[class*="captcha"]'
        ) is not None

        if not tem_recaptcha:
            logger.info("Nenhum CAPTCHA detectado — prosseguindo.")
            return True

        logger.info("CAPTCHA detectado. Estratégia: %s", self.captcha_strategy)

        if self.captcha_strategy == "2captcha":
            return await self._resolver_com_2captcha()

        if self.captcha_strategy == "stealth":
            # Nada a fazer — o disfarce já foi aplicado ao iniciar o browser.
            # Se mesmo assim aparecer CAPTCHA, faz uma pausa breve e tenta.
            logger.warning(
                "Stealth ativo mas CAPTCHA ainda apareceu. "
                "Considere usar a estratégia '2captcha' ou 'cookies'."
            )
            await asyncio.sleep(2)
            return True  # Tenta submeter mesmo assim

        # Estratégia padrão: "cookies"
        return await self._resolver_captcha_manual()

    async def _resolver_com_2captcha(self) -> bool:
        """
        Resolve reCAPTCHA v2 via API do 2captcha.
        Documentação: https://2captcha.com/api-docs/recaptcha-v2

        Custo: ~$3 por 1.000 CAPTCHAs.
        Tempo médio: 15–30 segundos por resolução.
        """
        if not self.twocaptcha_key:
            logger.error("TWOCAPTCHA_API_KEY não configurada.")
            return False

        page = self._page

        # Captura sitekey do reCAPTCHA
        sitekey = await page.evaluate("""
            () => {
                const el = document.querySelector('.g-recaptcha, [data-sitekey]');
                return el ? el.getAttribute('data-sitekey') : null;
            }
        """)

        if not sitekey:
            logger.error("Não foi possível extrair o sitekey do reCAPTCHA.")
            return False

        logger.info("Sitekey: %s — enviando para 2captcha …", sitekey)
        page_url = page.url

        async with httpx.AsyncClient(timeout=120) as http:
            # 1. Envia o CAPTCHA para resolução
            resp = await http.post(
                "https://2captcha.com/in.php",
                data={
                    "key": self.twocaptcha_key,
                    "method": "userrecaptcha",
                    "googlekey": sitekey,
                    "pageurl": page_url,
                    "json": 1,
                },
            )
            data = resp.json()
            if data.get("status") != 1:
                logger.error("2captcha rejeitou a solicitação: %s", data)
                return False

            captcha_id = data["request"]
            logger.info("CAPTCHA enviado (id=%s). Aguardando resolução …", captcha_id)

            # 2. Aguarda a resolução (poll a cada 5s por até 120s)
            token = None
            for _ in range(24):
                await asyncio.sleep(5)
                res = await http.get(
                    "https://2captcha.com/res.php",
                    params={"key": self.twocaptcha_key, "action": "get",
                            "id": captcha_id, "json": 1},
                )
                result = res.json()
                if result.get("status") == 1:
                    token = result["request"]
                    break
                if result.get("request") == "ERROR_CAPTCHA_UNSOLVABLE":
                    logger.error("2captcha: CAPTCHA insolúvel.")
                    return False
                logger.debug("2captcha: ainda aguardando … (%s)", result.get("request"))

            if not token:
                logger.error("2captcha: timeout na resolução.")
                return False

        logger.info("Token reCAPTCHA obtido. Injetando …")

        # 3. Injeta o token na página
        await page.evaluate(f"""
            () => {{
                const el = document.getElementById('g-recaptcha-response');
                if (el) {{
                    el.innerHTML = '{token}';
                    el.style.display = 'block';
                }}
                // Dispara callback do reCAPTCHA se existir
                if (window.___grecaptcha_cfg) {{
                    const clients = Object.values(window.___grecaptcha_cfg.clients || {{}});
                    for (const client of clients) {{
                        const callback = Object.values(client).find(v => typeof v === 'function');
                        if (callback) callback('{token}');
                    }}
                }}
            }}
        """)

        logger.info("Token reCAPTCHA injetado com sucesso.")
        return True

    async def _resolver_captcha_manual(self) -> bool:
        """
        Estratégia 'cookies': pausa e aguarda intervenção humana UMA vez.

        Como usar:
          1. Rode o script com headless=False na primeira vez.
          2. Resolva o CAPTCHA manualmente na janela do browser.
          3. O script salva os cookies em SESSION_FILE.
          4. Nas execuções seguintes, a sessão é reutilizada automaticamente.

        No Fly.io, após resolver manualmente num ambiente local, copie o
        arquivo de sessão gerado para um Fly Volume montado em /data.
        """
        page = self._page

        if self.headless:
            logger.error(
                "CAPTCHA manual não funciona em modo headless!\n"
                "Execute com headless=False para resolver o CAPTCHA pela primeira vez.\n"
                "Depois os cookies serão reutilizados automaticamente."
            )
            return False

        logger.info(
            "⚠️  AÇÃO NECESSÁRIA: Resolva o CAPTCHA na janela do browser.\n"
            "   O script aguardará até 3 minutos …"
        )

        try:
            # Aguarda desaparecimento do CAPTCHA ou aparecimento do dashboard
            await page.wait_for_selector(
                '.menu-principal, #dashboard, .sidebar, nav.main-nav, [data-autenticado]',
                timeout=180_000,  # 3 minutos
            )
            logger.info("CAPTCHA resolvido pelo usuário.")
            return True
        except Exception:
            logger.error("Tempo esgotado aguardando resolução manual do CAPTCHA.")
            return False

    # ------------------------------------------------------------------
    # Persistência de sessão (cookies)
    # ------------------------------------------------------------------

    def _ler_cookies_salvos(self) -> Optional[dict]:
        """Lê o storage_state salvo em disco. Retorna None se não existir."""
        if not os.path.exists(self.session_file):
            return None
        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Não foi possível ler session file: %s", e)
            return None

    async def _salvar_cookies(self):
        """Persiste o storage_state atual em disco."""
        try:
            state = await self._context.storage_state()
            os.makedirs(os.path.dirname(self.session_file) or ".", exist_ok=True)
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
            logger.info("Sessão salva em %s", self.session_file)
        except Exception as e:
            logger.warning("Não foi possível salvar session file: %s", e)

    async def _sessao_valida(self) -> bool:
        """
        Verifica se a sessão atual ainda é válida tentando acessar
        uma página protegida e checando se foi redirecionado para login.
        """
        page = self._page
        try:
            await page.goto(f"{self.url}/dashboard", wait_until="networkidle", timeout=15000)
            # Se chegou no dashboard sem ser mandado para login, sessão é válida
            em_login = await page.query_selector(
                'input[type="password"], .btn-login, #entrar, form[action*="login"]'
            ) is not None
            return not em_login
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Extração de ativos
    # ------------------------------------------------------------------

    async def extrair_ativos(self) -> list[Ativo]:
        """
        Navega até o módulo de equipamentos/ativos e extrai os dados.
        Retorna lista de objetos Ativo.
        """
        page = self._page
        logger.info("Extraindo ativos …")

        # Navega para o módulo de equipamentos
        # Ajuste a URL ou clique conforme a navegação real do ELOCA
        await page.goto(f"{self.url}/equipamentos", wait_until="networkidle")
        # Alternativa: clicar no menu
        # await page.click('a:has-text("Equipamentos"), a:has-text("Ativos")')

        ativos: list[Ativo] = []

        # Verifica se há paginação e itera por todas as páginas
        pagina = 1
        while True:
            logger.info("  → Página %d", pagina)
            rows = await self._extrair_linhas_tabela_ativos()
            ativos.extend(rows)

            # Tenta avançar para próxima página
            proximo = page.locator(
                'a.next, button.next, [aria-label="Próxima página"], .pagination .next:not(.disabled)'
            )
            if await proximo.count() == 0 or not await proximo.is_enabled():
                break
            await proximo.click()
            await page.wait_for_load_state("networkidle")
            pagina += 1

        logger.info("Total de ativos extraídos: %d", len(ativos))
        return ativos

    async def _extrair_linhas_tabela_ativos(self) -> list[Ativo]:
        """Lê todas as linhas da tabela de ativos na página atual."""
        page = self._page

        # Aguarda a tabela carregar
        await page.wait_for_selector("table tbody tr, .list-equipamentos .item", timeout=15000)

        linhas = await page.query_selector_all("table tbody tr")
        ativos = []

        for linha in linhas:
            colunas = await linha.query_selector_all("td")
            if not colunas:
                continue

            textos = [await col.inner_text() for col in colunas]

            # Mapeamento de colunas — AJUSTE conforme a tabela real do ELOCA
            # Inspecione com page.pause() ou veja o HTML exportado
            ativo = Ativo(
                id=textos[0].strip() if len(textos) > 0 else "",
                codigo=textos[1].strip() if len(textos) > 1 else "",
                descricao=textos[2].strip() if len(textos) > 2 else "",
                numero_serie=textos[3].strip() if len(textos) > 3 else "",
                cliente=textos[4].strip() if len(textos) > 4 else "",
                contrato=textos[5].strip() if len(textos) > 5 else "",
                status=textos[6].strip() if len(textos) > 6 else "",
            )

            # Tenta capturar link de detalhe para extrair mais campos se necessário
            link = await linha.query_selector("a")
            if link:
                href = await link.get_attribute("href")
                ativo.extras["detalhe_url"] = href or ""

            ativos.append(ativo)

        return ativos

    # ------------------------------------------------------------------
    # Extração de Ordens de Serviço
    # ------------------------------------------------------------------

    async def extrair_ordens_servico(
        self,
        status_filtro: Optional[str] = None,  # ex: "Aberta", "Em andamento"
    ) -> list[OrdemServico]:
        """
        Navega até o módulo de OS e extrai os dados.
        Retorna lista de OrdemServico.
        """
        page = self._page
        logger.info("Extraindo ordens de serviço …")

        await page.goto(f"{self.url}/ordens-servico", wait_until="networkidle")
        # Alternativa via menu:
        # await page.click('a:has-text("Ordens de Serviço"), a:has-text("OS")')

        # Aplica filtro de status se solicitado
        if status_filtro:
            await self._filtrar_status_os(status_filtro)

        os_list: list[OrdemServico] = []
        pagina = 1

        while True:
            logger.info("  → Página %d", pagina)
            rows = await self._extrair_linhas_tabela_os()
            os_list.extend(rows)

            proximo = page.locator(
                'a.next, button.next, [aria-label="Próxima página"], .pagination .next:not(.disabled)'
            )
            if await proximo.count() == 0 or not await proximo.is_enabled():
                break
            await proximo.click()
            await page.wait_for_load_state("networkidle")
            pagina += 1

        logger.info("Total de OS extraídas: %d", len(os_list))
        return os_list

    async def _filtrar_status_os(self, status: str):
        """Aplica filtro de status na listagem de OS."""
        page = self._page
        try:
            select = page.locator('select[name="status"], #filtro-status')
            await select.select_option(label=status)
            await page.click('button[type="submit"], .btn-filtrar, #aplicar-filtro')
            await page.wait_for_load_state("networkidle")
        except Exception as e:
            logger.warning("Não foi possível aplicar filtro de status: %s", e)

    async def _extrair_linhas_tabela_os(self) -> list[OrdemServico]:
        page = self._page
        await page.wait_for_selector("table tbody tr, .list-os .item", timeout=15000)

        linhas = await page.query_selector_all("table tbody tr")
        os_list = []

        for linha in linhas:
            colunas = await linha.query_selector_all("td")
            if not colunas:
                continue

            textos = [await col.inner_text() for col in colunas]

            # Mapeamento de colunas — AJUSTE conforme a tabela real do ELOCA
            os_obj = OrdemServico(
                numero=textos[0].strip() if len(textos) > 0 else "",
                tipo=textos[1].strip() if len(textos) > 1 else "",
                status=textos[2].strip() if len(textos) > 2 else "",
                cliente=textos[3].strip() if len(textos) > 3 else "",
                descricao=textos[4].strip() if len(textos) > 4 else "",
                tecnico=textos[5].strip() if len(textos) > 5 else "",
                data_abertura=textos[6].strip() if len(textos) > 6 else "",
            )

            link = await linha.query_selector("a")
            if link:
                href = await link.get_attribute("href")
                os_obj.extras["detalhe_url"] = href or ""

            os_list.append(os_obj)

        return os_list

    # ------------------------------------------------------------------
    # Criação de Ordem de Serviço
    # ------------------------------------------------------------------

    async def criar_ordem_servico(self, nova_os: NovaOS) -> Optional[str]:
        """
        Preenche e submete o formulário de nova OS no ELOCA.
        Retorna o número da OS criada, ou None em caso de falha.
        """
        page = self._page
        logger.info("Criando nova OS para cliente '%s' …", nova_os.cliente)

        # Navega até formulário de nova OS
        await page.goto(f"{self.url}/ordens-servico/nova", wait_until="networkidle")
        # Alternativa via clique:
        # await page.click('a:has-text("Nova OS"), button:has-text("Nova Ordem")')

        try:
            # Preenche cliente — pode ser select ou autocomplete
            await self._preencher_campo_cliente(nova_os.cliente)

            # Preenche ativo/equipamento
            await self._preencher_campo_ativo(nova_os.ativo_id)

            # Tipo de serviço
            await page.select_option(
                'select[name="tipo_servico"], #tipo-servico',
                label=nova_os.tipo_servico,
            )

            # Descrição
            await page.fill(
                'textarea[name="descricao"], #descricao-os',
                nova_os.descricao,
            )

            # Técnico (opcional)
            if nova_os.tecnico:
                await page.select_option(
                    'select[name="tecnico"], #tecnico',
                    label=nova_os.tecnico,
                )

            # Data prevista (opcional)
            if nova_os.data_prevista:
                await page.fill(
                    'input[name="data_prevista"], #data-prevista',
                    nova_os.data_prevista,
                )

            # Prioridade
            await page.select_option(
                'select[name="prioridade"], #prioridade',
                label=nova_os.prioridade,
            )

            # Submete formulário
            await page.click('button[type="submit"], .btn-salvar-os, #salvar-os')
            await page.wait_for_load_state("networkidle")

            # Tenta extrair número da OS criada da confirmação
            numero_os = await self._extrair_numero_os_confirmacao()
            logger.info("OS criada com sucesso: %s", numero_os)
            return numero_os

        except Exception as e:
            logger.error("Erro ao criar OS: %s", e)
            await page.screenshot(path=f"/tmp/eloca_os_erro_{int(datetime.now().timestamp())}.png")
            return None

    async def _preencher_campo_cliente(self, cliente: str):
        """Preenche campo de cliente — trata tanto <select> quanto autocomplete."""
        page = self._page
        try:
            await page.select_option('select[name="cliente"], #cliente', label=cliente)
        except Exception:
            # Tenta autocomplete
            await page.fill('input[name="cliente"], #cliente-search', cliente)
            await page.wait_for_selector(
                '.autocomplete-item, .dropdown-item, li.suggestion',
                timeout=5000,
            )
            await page.click(f'.autocomplete-item:has-text("{cliente}")')

    async def _preencher_campo_ativo(self, ativo_id: str):
        """Preenche campo de ativo/equipamento."""
        page = self._page
        try:
            await page.select_option(
                'select[name="ativo"], select[name="equipamento"], #ativo',
                value=ativo_id,
            )
        except Exception:
            await page.fill(
                'input[name="ativo"], input[name="equipamento"], #ativo-search',
                ativo_id,
            )
            await page.wait_for_selector('.autocomplete-item, li.suggestion', timeout=5000)
            first = page.locator('.autocomplete-item, li.suggestion').first
            await first.click()

    async def _extrair_numero_os_confirmacao(self) -> str:
        """Tenta capturar o número da OS na tela de confirmação/detalhe."""
        page = self._page
        try:
            elemento = await page.query_selector(
                '.numero-os, #numero-os, [data-numero-os], h1, .alert-success strong'
            )
            if elemento:
                return (await elemento.inner_text()).strip()
        except Exception:
            pass
        return "N/A"

    # ------------------------------------------------------------------
    # Exportação auxiliar
    # ------------------------------------------------------------------

    @staticmethod
    def ativos_para_csv(ativos: list[Ativo]) -> str:
        """Converte lista de Ativo em string CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "codigo", "descricao", "numero_serie",
            "cliente", "contrato", "localizacao", "status",
            "data_instalacao",
        ])
        for a in ativos:
            writer.writerow([
                a.id, a.codigo, a.descricao, a.numero_serie,
                a.cliente, a.contrato, a.localizacao, a.status,
                a.data_instalacao,
            ])
        return output.getvalue()

    @staticmethod
    def os_para_csv(os_list: list[OrdemServico]) -> str:
        """Converte lista de OrdemServico em string CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "numero", "tipo", "status", "cliente",
            "ativo_id", "descricao", "tecnico",
            "data_abertura", "data_fechamento",
        ])
        for o in os_list:
            writer.writerow([
                o.id, o.numero, o.tipo, o.status, o.cliente,
                o.ativo_id, o.descricao, o.tecnico,
                o.data_abertura, o.data_fechamento,
            ])
        return output.getvalue()


# ---------------------------------------------------------------------------
# Execução standalone (debug)
# ---------------------------------------------------------------------------

async def _main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    async with ElocaRPA(headless=False) as rpa:  # headless=False para debug visual
        ok = await rpa.login()
        if not ok:
            return

        ativos = await rpa.extrair_ativos()
        print(f"\n=== ATIVOS ({len(ativos)}) ===")
        print(ElocaRPA.ativos_para_csv(ativos)[:500])

        os_list = await rpa.extrair_ordens_servico()
        print(f"\n=== ORDENS DE SERVIÇO ({len(os_list)}) ===")
        print(ElocaRPA.os_para_csv(os_list)[:500])


if __name__ == "__main__":
    asyncio.run(_main())
