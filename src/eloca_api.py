"""
eloca_api.py
Cliente HTTP direto para a API do ELOCA (sem browser).
Usa o api_token obtido pelo eloca_auth.py.

Endpoints descobertos pela inspeção:
  Equipamentos : GET sistema.otimogestor.com.br/api/api/reports/Servicos/Equipamentos
  OS (CGI)     : GET weback.app.otimogestor.com.br/cgi-bin/exec.cgi?PRG=scp102a1&ISAJAX=S&...
  Clientes     : GET api.otimogestor.com.br/api/Estoque/Search/ClientesLocalContrato
  Tipos OS     : GET api.otimogestor.com.br/api/tipos-os
  Situações OS : GET api.otimogestor.com.br/api/situacoes-os
  Usuário      : GET api.otimogestor.com.br/api/user
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Bases ──────────────────────────────────────────────────────────────────────
API_BASE     = os.getenv("API_BASE",     "https://api.otimogestor.com.br")
SISTEMA_BASE = os.getenv("SISTEMA_BASE", "https://sistema.otimogestor.com.br")
CGI_BASE     = os.getenv("CGI_BASE",     "https://weback.app.otimogestor.com.br/cgi-bin/exec.cgi")

HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "60"))


# ── Modelos ────────────────────────────────────────────────────────────────────

@dataclass
class Ativo:
    recnum: str = ""
    equipamento: str = ""          # código do equipamento
    serie_fabricante: str = ""
    status: str = ""
    cliente: str = ""
    local: str = ""
    empresa: str = ""
    produto: str = ""
    descricao: str = ""
    aquisicao: str = ""
    contrato: str = ""
    extras: dict = field(default_factory=dict)


@dataclass
class OrdemServico:
    numero: str = ""
    tipo: str = ""
    status: str = ""
    cliente: str = ""
    equipamento: str = ""
    descricao: str = ""
    tecnico: str = ""
    data_abertura: str = ""
    data_fechamento: str = ""
    extras: dict = field(default_factory=dict)


@dataclass
class NovaOS:
    cliente_codigo: str
    equipamento_codigo: str
    tipo_os_codigo: str
    descricao: str
    tecnico_codigo: str = ""
    data_prevista: str = ""
    prioridade: str = "Normal"


# ── Cliente principal ──────────────────────────────────────────────────────────

SESSION_FILE = os.getenv("SESSION_FILE", "/tmp/eloca_session.json")


def _carregar_cookies_sessao() -> dict:
    """Lê os cookies do arquivo de sessão do Playwright para usar no CGI."""
    if not os.path.exists(SESSION_FILE):
        return {}
    try:
        import json
        with open(SESSION_FILE) as f:
            state = json.load(f)
        # Filtra cookies do domínio weback.app.otimogestor.com.br
        cookies = {}
        for c in state.get("cookies", []):
            domain = c.get("domain", "")
            if "otimogestor" in domain:
                cookies[c["name"]] = c["value"]
        return cookies
    except Exception as e:
        logger.warning("Não foi possível carregar cookies de sessão: %s", e)
        return {}


class ElocaApiClient:
    """
    Faz todas as chamadas de dados ao ELOCA via HTTP direto.
    - API moderna (api.otimogestor.com.br): usa api_token como query param
    - CGI legado (weback.app.otimogestor.com.br/cgi-bin): usa cookies de sessão
    """

    def __init__(self, api_token: str, user_id: str, empresa: str):
        self.api_token    = api_token
        self.user_id      = user_id
        self.empresa      = empresa
        self._session_cookies = _carregar_cookies_sessao()
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        proxy_url = os.getenv("PROXY_URL")
        proxy_kwargs = {"proxy": proxy_url} if proxy_url else {}
        self._client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
            },
            follow_redirects=True,
            **proxy_kwargs,
        )
        return self

    async def __aexit__(self, *_):
        if self._client:
            await self._client.aclose()

    # ── Parâmetro padrão ──────────────────────────────────────────────────────

    def _p(self, extra: dict = None) -> dict:
        """Retorna params base com api_token."""
        params = {"api_token": self.api_token}
        if extra:
            params.update(extra)
        return params

    # ── Usuário / validação ───────────────────────────────────────────────────

    async def info_usuario(self) -> dict:
        """Valida token e retorna dados do usuário logado."""
        r = await self._client.get(f"{API_BASE}/api/user", params=self._p())
        r.raise_for_status()
        return r.json()

    # ── Equipamentos / Ativos ─────────────────────────────────────────────────

    async def listar_ativos(
        self,
        local: str = "0",
        produto: str = "",
        fornecedor: str = "",
        data_de: str = "",
        data_ate: str = "",
    ) -> list[Ativo]:
        """
        Retorna lista completa de equipamentos/ativos.
        Endpoint: sistema.otimogestor.com.br/api/api/reports/Servicos/Equipamentos
        """
        logger.info("Buscando ativos via API …")

        params = self._p({
            "local":       local,
            "endereco":    "0",
            "produto":     produto,
            "fornecedor":  fornecedor,
            "data":        data_de,
            "adata":       data_ate,
        })

        r = await self._client.get(
            f"{SISTEMA_BASE}/api/api/reports/Servicos/Equipamentos",
            params=params,
        )
        r.raise_for_status()
        dados = r.json()

        ativos = []
        for item in dados:
            ativo = Ativo(
                recnum           = str(item.get("recnum", "")),
                equipamento      = str(item.get("equipamento", "")),
                serie_fabricante = str(item.get("serieFabricante", "")),
                status           = str(item.get("status", "")),
                cliente          = str(item.get("cliente", item.get("local", ""))),
                local            = str(item.get("local", "")),
                empresa          = str(item.get("empresa", "")),
                produto          = str(item.get("produto", "")),
                descricao        = str(item.get("descricao", item.get("produto", ""))),
                aquisicao        = str(item.get("aquisicao", "")),
                contrato         = str(item.get("contrato", "")),
                extras           = item,
            )
            ativos.append(ativo)

        logger.info("Ativos retornados: %d", len(ativos))
        return ativos

    # ── Ordens de Serviço ─────────────────────────────────────────────────────

    async def listar_os(
        self,
        dias_atras: int = 30,
        status_codes: list[str] = None,
        cliente_codigo: str = "0",
        tecnico_codigo: str = "0",
    ) -> list[OrdemServico]:
        """
        Retorna lista de Ordens de Serviço via endpoint CGI do ELOCA.
        Endpoint: /cgi-bin/exec.cgi?PRG=scp102a1&ISAJAX=S&...
        """
        logger.info("Buscando OS via CGI (últimos %d dias) …", dias_atras)

        hoje    = datetime.today()
        data_de = (hoje - timedelta(days=dias_atras)).strftime("%d/%m/%Y")
        data_ate = hoje.strftime("%d/%m/%Y")

        # Códigos de status padrão (todos os ativos)
        if not status_codes:
            status_codes = ["A"]  # A = Em aberto; use ["F"] para fechadas, [] para todas

        tipos = ["*1*", "*2*", "*3*", "*4*", "*5*", "*9*", "*11*"]
        filtros = [f"*{i}*" for i in range(37)]

        params = [
            ("ISAJAX",    "S"),
            ("LOCAL",     "0"),
            ("CODSTATUS", status_codes[0] if status_codes else "A"),
            ("TIPO_DATA", "0"),
            ("DADATA",    data_de),
            ("ADATA",     data_ate),
            ("DOCLIENTE", cliente_codigo),
            ("DOTECNICO", tecnico_codigo),
            ("CODCONTRATO", ""),
            ("NEXTFIELD", ""),
            ("ID",        self.user_id),
            ("ACAO",      "25"),
            ("EXTRECNO",  "0"),
            ("PRG",       "scp102a1"),
            ("AOCLIENTE", "99999999999999"),
            ("AOTECNICO", "99999999"),
            ("EMPRESA",   self.empresa),
            ("tableScp102a1New1_length", "999"),  # máximo de resultados por página
        ]
        for t in tipos:
            params.append(("TIPO", t))
        for f in filtros:
            params.append(("FILTROS", f))

        # CGI usa cookies de sessão, não api_token
        r = await self._client.get(
            CGI_BASE, params=params, cookies=self._session_cookies
        )
        r.raise_for_status()

        if "Erro de segurança" in r.text or "relogar" in r.text.lower():
            raise RuntimeError(
                "CGI retornou erro de sessão — cookies inválidos ou expirados."
            )

        logger.info("CGI retornou %d chars", len(r.text))
        # O CGI retorna fragmento HTML com linhas <tr> — parsear
        os_list = self._parsear_html_os(r.text)
        logger.info("OS retornadas: %d", len(os_list))
        if os_list:
            logger.info("Primeira OS: nº=%s | tipo=%s | status=%s | cliente=%s",
                        os_list[0].numero, os_list[0].tipo,
                        os_list[0].status, os_list[0].cliente)
        return os_list

    def _parsear_html_os(self, html: str) -> list[OrdemServico]:
        """
        Extrai OS do HTML retornado pelo CGI.

        Estrutura observada (colunas por índice de <td>):
          0  ícone (details-control)
          1  empresa
          2  link "Imprime" → recnum da OS em imprimeModal(RECNUM)
          3  código cliente
          4  nome cliente
          5  telefone
          6  CEP
          7  número OS  → texto do link ordemservico(recnum, NUMERO_OS)
          8  vazio
          9  tipo OS
          10 substatus / observação
          11 vazio
          12 status principal (Aberto / Fechado …)
          13 data abertura (se presente)
          14 equipamento (se presente)
          15 técnico (se presente)
        """
        try:
            from html.parser import HTMLParser
            import re as _re

            class TableParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.in_tr       = False
                    self.in_td       = False
                    self.rows        = []
                    self.current_row = []
                    self.current_cell = ""

                def handle_starttag(self, tag, attrs):
                    if tag == "tr":
                        self.in_tr = True
                        self.current_row = []
                    elif tag == "td" and self.in_tr:
                        self.in_td = True
                        self.current_cell = ""

                def handle_endtag(self, tag):
                    if tag == "tr":
                        self.in_tr = False
                        if len(self.current_row) >= 10:
                            self.rows.append(self.current_row[:])
                        self.current_row = []
                    elif tag == "td" and self.in_td:
                        self.in_td = False
                        self.current_row.append(self.current_cell.strip())

                def handle_data(self, data):
                    if self.in_td:
                        self.current_cell += data

            parser = TableParser()
            parser.feed(html)

            def _cel(row, idx):
                v = row[idx].strip() if idx < len(row) else ""
                return " ".join(v.split())  # colapsa whitespace

            os_list = []
            for row in parser.rows:
                numero = _cel(row, 7)
                # Ignora linhas de cabeçalho ou sem número de OS numérico
                if not numero or not numero.isdigit():
                    continue
                os_obj = OrdemServico(
                    numero          = numero,
                    tipo            = _cel(row, 9),
                    status          = _cel(row, 12),
                    cliente         = _cel(row, 4),   # nome do cliente
                    equipamento     = _cel(row, 14) if len(row) > 14 else "",
                    descricao       = _cel(row, 10),  # substatus / obs
                    tecnico         = _cel(row, 15) if len(row) > 15 else "",
                    data_abertura   = _cel(row, 13) if len(row) > 13 else "",
                    data_fechamento = _cel(row, 16) if len(row) > 16 else "",
                    extras          = {"cliente_codigo": _cel(row, 3)},
                )
                os_list.append(os_obj)
            return os_list

        except Exception as e:
            logger.warning("Erro ao parsear HTML de OS: %s", e)
            logger.debug("HTML recebido (500 chars): %s", html[:500])
            return []

    # ── Carteira de Contratos ─────────────────────────────────────────────────

    async def listar_carteira_contratos(self) -> list[dict]:
        """
        Retorna carteira de contratos via REST (sistema.otimogestor.com.br).

        Estratégia:
          1. Visitar sistema.otimogestor.com.br/ com api_token para estabelecer
             sessão Sanctum nesse domínio (nosso login passa só por weback.app).
          2. Capturar cookies de sessão do response.
          3. Tentar o endpoint de contratos com múltiplos métodos de auth.
        """
        import urllib.parse

        BASE_CONTRATO = f"{SISTEMA_BASE}/api/api/reports/Contrato/listar-contratos-produtos"
        PARAMS_CONTRATO = {"local": "0", "quebra": "CARTEIRA DE CLIENTES"}

        # ── Passo 1: visitar sistema.otimogestor.com.br para criar sessão ────────
        logger.info("[CARTEIRA] Estabelecendo sessão em sistema.otimogestor.com.br …")
        combined_cookies = dict(self._session_cookies)
        try:
            r_home = await self._client.get(
                f"{SISTEMA_BASE}/",
                params={"api_token": self.api_token},
                cookies=self._session_cookies,
                headers={"Accept": "text/html,application/xhtml+xml,*/*"},
            )
            new_ck = dict(r_home.cookies)
            logger.info("[CARTEIRA] GET sistema/ → %d | novos cookies: %s",
                        r_home.status_code, list(new_ck.keys()))
            combined_cookies.update(new_ck)
        except Exception as e:
            logger.warning("[CARTEIRA] Falha ao visitar sistema/: %s", e)

        # XSRF para Sanctum stateful
        xsrf_raw = combined_cookies.get("XSRF-TOKEN", "")
        xsrf = urllib.parse.unquote(xsrf_raw)

        # ── Passo 2: obter stack trace do Laravel (Accept: text/html) ───────────
        try:
            r_html = await self._client.get(
                BASE_CONTRATO,
                params={"api_token": self.api_token},
                cookies=combined_cookies,
                headers={"Accept": "text/html,application/xhtml+xml,*/*"},
            )
            # Extrair trecho relevante do HTML de erro (Ignition/Whoops)
            body = r_html.text
            # Procurar pela mensagem de exceção no HTML
            import re as _re
            exc_match = _re.search(r'(Exception|Error|Illuminate[\\][^<]{0,200})', body)
            trace_snippet = exc_match.group(0)[:300] if exc_match else body[2000:2600]
            logger.info("[CARTEIRA] stack-trace (HTML 500): status=%d snippet=%s",
                        r_html.status_code, trace_snippet.replace("\n", " ")[:400])
        except Exception as e:
            logger.warning("[CARTEIRA] Falha ao obter stack trace: %s", e)

        # ── Passo 3: tentar api.otimogestor.com.br para contratos ────────────────
        api_candidates = [
            f"{API_BASE}/api/contratos",
            f"{API_BASE}/api/Contrato/listar",
            f"{API_BASE}/api/carteira",
            f"{API_BASE}/api/relatorios/contratos",
            f"{API_BASE}/api/Contrato/carteira",
            f"{API_BASE}/api/reports/Contrato/listar-contratos-produtos",
        ]
        for url in api_candidates:
            try:
                r = await self._client.get(
                    url, params={"api_token": self.api_token},
                    headers={"Accept": "application/json"}
                )
                logger.info("[CARTEIRA] api.otimo %s → %d: %s",
                            url.split("/api/")[-1], r.status_code, r.text[:200])
                if r.status_code == 200:
                    dados = r.json()
                    if isinstance(dados, list) and dados:
                        logger.info("[CARTEIRA] SUCESSO em api.otimogestor! %d registros", len(dados))
                        return dados
            except Exception as e:
                logger.warning("[CARTEIRA] %s → ERRO: %s", url, e)

        # ── Passo 4: tentar sistema com Accept html para ver dados brutos ─────────
        tentativas = [
            ("sistema-queryparam", {
                "params": {"api_token": self.api_token, "local": "0", "quebra": "CARTEIRA DE CLIENTES"},
                "cookies": combined_cookies,
            }),
        ]

        for label, kwargs in tentativas:
            try:
                r = await self._client.get(BASE_CONTRATO, **kwargs)
                body = r.text[:600]
                logger.info("[CARTEIRA] %s → %d: %s", label, r.status_code, body)
                if r.status_code == 200:
                    try:
                        dados = r.json()
                    except Exception:
                        logger.warning("[CARTEIRA] %s → 200 mas JSON inválido", label)
                        continue
                    total = len(dados) if isinstance(dados, list) else -1
                    logger.info("[CARTEIRA] SUCESSO via %s! %d registros", label, total)
                    return dados if isinstance(dados, list) else []
            except Exception as e:
                logger.warning("[CARTEIRA] %s → ERRO: %s", label, e)

        # ── Passo 3: tentar login direto em sistema.otimogestor.com.br ───────────
        username = os.getenv("ELOCA_USERNAME", "")
        password = os.getenv("ELOCA_PASSWORD", "")
        if username and password:
            for login_url in [
                f"{SISTEMA_BASE}/api/login",
                f"{SISTEMA_BASE}/api/auth/login",
            ]:
                try:
                    r_login = await self._client.post(
                        login_url,
                        json={"login": username, "password": password},
                        headers={"Accept": "application/json",
                                 "Content-Type": "application/json"},
                    )
                    logger.info("[CARTEIRA] POST %s → %d: %s",
                                login_url, r_login.status_code, r_login.text[:300])
                    if r_login.status_code == 200:
                        tk = r_login.json().get("token") or r_login.json().get("access_token")
                        if tk:
                            r2 = await self._client.get(
                                BASE_CONTRATO,
                                params=PARAMS_CONTRATO,
                                headers={"Authorization": f"Bearer {tk}",
                                         "Accept": "application/json"},
                            )
                            logger.info("[CARTEIRA] bearer-direto → %d: %s",
                                        r2.status_code, r2.text[:300])
                            if r2.status_code == 200:
                                dados = r2.json()
                                return dados if isinstance(dados, list) else []
                except Exception as e:
                    logger.warning("[CARTEIRA] %s → ERRO: %s", login_url, e)

        logger.info("[CARTEIRA] Todas as tentativas falharam — retornando vazio.")
        return []

    # ── Dados auxiliares ──────────────────────────────────────────────────────

    async def listar_clientes(self) -> list[dict]:
        """Retorna lista de clientes."""
        r = await self._client.get(
            f"{API_BASE}/api/Estoque/Search/ClientesLocalContrato",
            params=self._p(),
        )
        r.raise_for_status()
        dados = r.json()
        logger.info("Clientes: %d", len(dados))
        return dados

    async def listar_tipos_os(self) -> list[dict]:
        """Retorna tipos de OS disponíveis."""
        r = await self._client.get(f"{API_BASE}/api/tipos-os", params=self._p())
        r.raise_for_status()
        return r.json().get("dados", [])

    async def listar_situacoes_os(self) -> list[dict]:
        """Retorna situações/status de OS."""
        r = await self._client.get(f"{API_BASE}/api/situacoes-os", params=self._p())
        r.raise_for_status()
        return r.json().get("Situacao", [])

    # ── Exportação CSV ────────────────────────────────────────────────────────

    @staticmethod
    def ativos_para_csv(ativos: list[Ativo]) -> str:
        import csv, io
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["recnum","equipamento","serie_fabricante","status",
                    "cliente","local","empresa","produto","descricao",
                    "aquisicao","contrato"])
        for a in ativos:
            w.writerow([a.recnum, a.equipamento, a.serie_fabricante, a.status,
                        a.cliente, a.local, a.empresa, a.produto, a.descricao,
                        a.aquisicao, a.contrato])
        return out.getvalue()

    @staticmethod
    def os_para_csv(os_list: list[OrdemServico]) -> str:
        import csv, io
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["numero","tipo","status","cliente","equipamento",
                    "descricao","tecnico","data_abertura","data_fechamento"])
        for o in os_list:
            w.writerow([o.numero, o.tipo, o.status, o.cliente, o.equipamento,
                        o.descricao, o.tecnico, o.data_abertura, o.data_fechamento])
        return out.getvalue()
