"""
scheduler.py — Orquestrador principal da integração ELOCA ↔ CRM Lovable

Fluxo a cada ciclo:
  1. Obtém api_token (reutiliza sessão salva ou faz login)
  2. Busca ativos e OS via API HTTP direta (sem browser)
  3. Salva CSV no Supabase Storage + upsert nas tabelas
  4. Processa fila de criação de OS (CRM → ELOCA) via browser
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from eloca_auth import obter_token, carregar_cookies
from eloca_api  import ElocaApiClient, NovaOS
from eloca_bi   import (
    fetch_carteira_contratos, fetch_equipamentos_ativos,
    fetch_bi_movimentacoes, fetch_bi_ctprod, fetch_bi_faturamento,
    fetch_bi_ativos, fetch_bi_contas_pagar, fetch_bi_carteira_valor,
)
from supabase_sync import (
    get_client,
    # upload_csv,  # desativado — bucket bloqueado por RLS do Lovable
    upsert_ativos,
    upsert_ordens_servico,
    buscar_os_pendentes_criacao,
    marcar_os_criada,
    marcar_os_erro,
    marcar_os_processando,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scheduler")

SYNC_CRON    = os.getenv("SYNC_CRON",    "0,30 8-18 * * 1-5")
SYNC_TZ      = os.getenv("SYNC_TZ",      "America/Sao_Paulo")
RUN_ON_START = os.getenv("RUN_ON_START", "true").lower() == "true"

# ── bi-ingest Edge Function ───────────────────────────────────────────────────
BI_SYNC_TOKEN = os.getenv("BI_SYNC_TOKEN", "")
BI_INGEST_URL = "https://dxkbqxualiqdhvsudshr.supabase.co/functions/v1/bi-ingest"

# ── crm-sync Edge Function ────────────────────────────────────────────────────
CRM_SYNC_TOKEN = os.getenv("CRM_SYNC_TOKEN", "")
CRM_SYNC_URL   = "https://dxkbqxualiqdhvsudshr.supabase.co/functions/v1/crm-sync"


def _crm_sync_post(action: str, body: dict | None = None) -> dict:
    """Chama a Edge Function crm-sync com a action indicada.

    Substitui todas as chamadas supabase.rpc() que precisavam do
    SUPABASE_SERVICE_KEY no runner do GitHub Actions. A Edge Function
    executa as RPCs internamente com a service role do projeto.

    Retorna o JSON da resposta ou lança RuntimeError em caso de falha.
    """
    if not CRM_SYNC_TOKEN:
        raise RuntimeError(
            "CRM_SYNC_TOKEN não definido — adicione o secret no GitHub Actions."
        )
    import httpx as _httpx
    resp = _httpx.post(
        f"{CRM_SYNC_URL}?action={action}",
        headers={
            "x-sync-token": CRM_SYNC_TOKEN,
            "Content-Type": "application/json",
        },
        json=body or {},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _bi_ingest_post(table: str, rows: list[dict]) -> int:
    """Envia um lote de linhas para a Edge Function bi-ingest.

    Substitui as chamadas RPC sync_bi_* que retornavam 401 quando o
    SUPABASE_SERVICE_KEY não estava disponível no runner do GitHub Actions.
    O BI_SYNC_TOKEN é um secret dedicado, independente do service key.

    Retorna o número de linhas reportado pelo endpoint (ou len(rows) como fallback).
    """
    if not BI_SYNC_TOKEN:
        raise RuntimeError(
            "BI_SYNC_TOKEN não definido — adicione o secret no GitHub Actions."
        )
    import httpx as _httpx
    resp = _httpx.post(
        f"{BI_INGEST_URL}?table={table}",
        headers={
            "x-sync-token": BI_SYNC_TOKEN,
            "Content-Type": "application/json",
        },
        json={"rows": rows},
        timeout=60,
    )
    resp.raise_for_status()
    try:
        return resp.json().get("count", len(rows))
    except Exception:
        return len(rows)


def _get_sync_state(supabase, tabela: str) -> int:
    """Retorna o último recnum sincronizado para a tabela via crm-sync Edge Function."""
    try:
        data = _crm_sync_post("get_sync_state", {"tabela": tabela})
        return int(data.get("recnum") or 0)
    except Exception as e:
        logger.warning("Não foi possível ler sync_state para %s: %s", tabela, e)
        return 0


def _update_sync_state(supabase, tabela: str, recnum: int) -> None:
    """Grava o último recnum sincronizado para a tabela via crm-sync Edge Function."""
    try:
        _crm_sync_post("update_sync_state", {"tabela": tabela, "recnum": recnum})
        logger.info("sync_state atualizado: %s → recnum %d", tabela, recnum)
    except Exception as e:
        logger.warning("Não foi possível atualizar sync_state para %s: %s", tabela, e)


def _log_inicio(supabase, inicio: datetime) -> "int | None":
    """Insere linha de início na tabela sync_logs via crm-sync Edge Function."""
    try:
        data = _crm_sync_post("log_inicio")
        return data.get("log_id")
    except Exception as e:
        logger.warning("Não foi possível registrar início no sync_logs: %s", e)
        return None


def _log_fim(supabase, log_id, inicio: datetime,
             ativos_total: int, os_total: int, carteira_total: int,
             erros: list[str]):
    """Atualiza a linha de log com o resultado final do ciclo via crm-sync Edge Function."""
    if log_id is None:
        return
    try:
        concluido = datetime.utcnow()
        duracao   = round((concluido - inicio).total_seconds(), 1)
        status    = "erro" if len(erros) == 3 else ("parcial" if erros else "sucesso")
        _crm_sync_post("log_fim", {
            "log_id":         log_id,
            "ativos_total":   ativos_total,
            "os_total":       os_total,
            "carteira_total": carteira_total,
            "erros":          erros or None,
            "duracao":        duracao,
            "status":         status,
        })
    except Exception as e:
        logger.warning("Não foi possível atualizar sync_logs (id=%s): %s", log_id, e)


async def _buscar_os_com_retry(api) -> list:
    """
    Busca OS via CGI com retry automático quando a sessão expirar.
    - 1ª tentativa: usa cookies em cache.
    - Se falhar por sessão inválida: força novo login, atualiza cookies, tenta de novo.
    """
    for tentativa in range(2):
        try:
            return await api.listar_os(dias_atras=60)
        except RuntimeError as e:
            erro_str = str(e).lower()
            if tentativa == 0 and ("sessão" in erro_str or "cookies" in erro_str or "segurança" in erro_str):
                logger.warning("Sessão CGI expirada — renovando login e tentando novamente ...")
                novo = await obter_token(forcar_novo_login=True)
                api.api_token        = novo["api_token"]
                api.user_id          = novo["user_id"]
                api._session_cookies = carregar_cookies()
                logger.info("Credenciais renovadas (user_id=%s, %d cookies). Retentando OS ...",
                            api.user_id, len(api._session_cookies))
            else:
                raise
    return []


async def executar_sincronizacao():
    inicio = datetime.utcnow()
    logger.info("═" * 60)
    logger.info("Ciclo iniciado — %s", inicio.isoformat())

    erros = []
    ativos_total = os_total = carteira_total = 0

    try:
        supabase = get_client()
    except Exception as e:
        logger.error(
            "Falha ao criar cliente Supabase (%s) — operações que dependem do "
            "banco Supabase serão ignoradas; sync BI via bi-ingest continua.", e
        )
        supabase = None

    log_id = _log_inicio(supabase, inicio)

    # ── 1. BI SQL Server — carteira e contratos (independente do token ELOCA) ──
    try:
        carteira = fetch_carteira_contratos()
        carteira_total = len(carteira)
        upsert_carteira_supabase(supabase, carteira)
        sync_contracts_native(supabase, carteira)
    except Exception as e:
        msg = f"Erro ao buscar carteira de contratos (BI): {e}"
        logger.error(msg)
        erros.append(msg)

    try:
        equipamentos_ativos = fetch_equipamentos_ativos()
        update_ativos_contratos_bi(supabase, equipamentos_ativos)
        sync_assets_contract_native(supabase, equipamentos_ativos)
    except Exception as e:
        msg = f"Erro ao atualizar contratos em ativos (BI): {e}"
        logger.error(msg)
        erros.append(msg)

    # ── 1b. BI SQL Server — movimentações, produtos e faturamento (incremental) ─
    try:
        ultimo_movs = _get_sync_state(supabase, "bi_movimentacoes")
        movs = fetch_bi_movimentacoes(ultimo_recnum=ultimo_movs)
        if movs:
            sync_bi_movimentacoes(supabase, movs)
            novo_recnum = max(int(r["recnum"]) for r in movs)
            _update_sync_state(supabase, "bi_movimentacoes", novo_recnum)
        else:
            logger.info("bi_movimentacoes: nenhum registro novo desde recnum %d.", ultimo_movs)
    except Exception as e:
        msg = f"Erro ao sincronizar ctmequip (movimentações): {e}"
        logger.error(msg)
        erros.append(msg)

    try:
        ultimo_ctprod = _get_sync_state(supabase, "bi_ctprod")
        ctprod = fetch_bi_ctprod(ultimo_recnum=ultimo_ctprod)
        if ctprod:
            sync_bi_ctprod(supabase, ctprod)
            novo_recnum = max(int(r["recnum"]) for r in ctprod)
            _update_sync_state(supabase, "bi_ctprod", novo_recnum)
        else:
            logger.info("bi_ctprod: nenhum registro novo desde recnum %d.", ultimo_ctprod)
    except Exception as e:
        msg = f"Erro ao sincronizar ctprod: {e}"
        logger.error(msg)
        erros.append(msg)

    try:
        faturamento = fetch_bi_faturamento(janela_dias=90)
        sync_bi_faturamento(supabase, faturamento)
    except Exception as e:
        msg = f"Erro ao sincronizar docrec (faturamento): {e}"
        logger.error(msg)
        erros.append(msg)

    # Contas a pagar (docpag)
    try:
        contas_pagar = fetch_bi_contas_pagar(janela_dias=120)
        sync_bi_contas_pagar(supabase, contas_pagar)
    except Exception as e:
        msg = f"Erro ao sincronizar docpag: {e}"
        logger.error(msg)
        erros.append(msg)

    # Carteira com valor mensal real
    try:
        carteira_valor = fetch_bi_carteira_valor()
        sync_bi_carteira_valor(supabase, carteira_valor)
    except Exception as e:
        msg = f"Erro ao sincronizar carteira com valor: {e}"
        logger.error(msg)
        erros.append(msg)

    try:
        ativos = fetch_bi_ativos()
        sync_bi_ativos(supabase, ativos)
    except Exception as e:
        msg = f"Erro ao sincronizar catálogo de ativos (equip): {e}"
        logger.error(msg)
        erros.append(msg)

    # Propaga status do ELOCA (ativos) → assets.asset_status do CRM nativo
    try:
        info = _crm_sync_post("sync_assets_status")
        logger.info(
            "sync_assets_status_from_ativos: avaliados=%s atualizados=%s por_status=%s",
            info.get("avaliados"), info.get("atualizados"), info.get("por_status")
        )
    except Exception as e:
        logger.warning("Erro em sync_assets_status_from_ativos: %s", e)

    # ── 2. Obtém token ELOCA (para ativos e OS via REST/CGI) ─────────────────
    try:
        token_data = await obter_token()
        api_token = token_data["api_token"]
        user_id   = token_data["user_id"]
        empresa   = token_data["empresa"]
        logger.info("Token válido (user_id=%s, empresa=%s)", user_id, empresa)
    except Exception as e:
        msg = f"Falha ao obter token ELOCA: {e}"
        logger.error("%s — pulando ativos/OS da API.", msg)
        erros.append(msg)
        _log_fim(supabase, log_id, inicio, ativos_total, os_total, carteira_total, erros)
        return

    # ── 3. Extração via API HTTP (OS) ─────────────────────────────────────────
    # NOTA: listar_ativos() desativado — catálogo de equipamentos agora vem do
    # BI via bi_ativos (fetch_bi_ativos), que é mais completo e não exige login.
    # Reativar aqui se precisar de campos exclusivos da API: endereço, marca,
    # modelo, valor_compra, valor_mercado, fornecedor.
    async with ElocaApiClient(api_token, user_id, empresa) as api:

        # OS (com retry automático se sessão CGI expirar)
        try:
            os_list = await _buscar_os_com_retry(api)
            os_total = len(os_list)
            upsert_os_supabase(supabase, os_list)
        except Exception as e:
            msg = f"Erro ao buscar OS: {e}"
            logger.error(msg)
            erros.append(msg)

        # ── 4. Criação de OS (fila do CRM → ELOCA) ────────────────────────────
        try:
            pendentes = buscar_os_pendentes_criacao(supabase)
            logger.info("%d OS pendente(s) de criação.", len(pendentes))

            if pendentes:
                await processar_fila_criacao_os(pendentes, supabase, api_token)

        except Exception as e:
            msg = f"Erro ao processar fila de OS: {e}"
            logger.error(msg)
            erros.append(msg)

    # ── Resumo ────────────────────────────────────────────────────────────────
    duracao = (datetime.utcnow() - inicio).total_seconds()
    if erros:
        logger.warning("Ciclo concluído com %d erro(s) em %.1fs.", len(erros), duracao)
    else:
        logger.info("Ciclo concluído com sucesso em %.1fs.", duracao)
    logger.info("═" * 60)

    _log_fim(supabase, log_id, inicio, ativos_total, os_total, carteira_total, erros)


def upsert_ativos_supabase(supabase, ativos):
    """Upsert de ativos via RPC sync_ativos (SECURITY DEFINER)."""
    def s(v):
        return str(v).strip() if v is not None else ""

    registros = []
    for a in ativos:
        item = a.extras
        registros.append({
            "id":               s(item.get("recnum")) or s(item.get("equipamento")),
            "codigo":           s(item.get("equipamento")),
            "numero_serie":     s(item.get("serieFabricante")),
            "descricao":        s(item.get("produto")),
            "cod_produto":      s(item.get("codigo_produto")),
            "produto":          s(item.get("produto")),
            "status":           s(item.get("status")),
            "situacao_os":      s(item.get("situacaoOS")),
            "tipo_os":          s(item.get("tipoOS")),
            "os_aberta":        s(item.get("osAberta")),
            "os_instalacao":    s(item.get("osInstalacao")),
            "ult_os":           s(item.get("os")),
            "cliente":          s(item.get("nomeFantasia") or item.get("local")),
            "nome_fantasia":    s(item.get("nomeFantasia")),
            "localizacao":      s(item.get("local")),
            "local_contrato":   s(item.get("localContrato")),
            "setor":            s(item.get("setor")),
            "endereco":         s(item.get("endereco")),
            "numero_endereco":  s(item.get("numero")),
            "bairro":           s(item.get("bairro")),
            "complemento":      s(item.get("complemento")),
            "municipio":        s(item.get("municipio")),
            "uf":               s(item.get("uf")),
            "cep":              s(item.get("cep")),
            "contrato":         s(item.get("contract")),
            "grupo":            s(item.get("descricao_grupo_produto")),
            "grupo2":           s(item.get("descricao_grupo_produto2")),
            "marca":            s(item.get("marca")),
            "modelo":           s(item.get("modelo")),
            "data_instalacao":  s(item.get("aquisicao")),
            "ano_fabricacao":   s(item.get("anoDeFabricacao")),
            "termino_garantia": s(item.get("termoGarantia")),
            "nota_fiscal":      s(item.get("notaFiscalCompraEquip")),
            "valor_compra":     s(item.get("valcompra")),
            "valor_mercado":    s(item.get("valorMercado")),
            "fornecedor":       s(item.get("fornecedor")),
            "proprietario":     s(item.get("proprietario")),
            "usado":            s(item.get("usado")),
            "envio":            s(item.get("envio")),
            "ult_retorno":      s(item.get("data_ultimo_retorno")),
            "ip":               s(item.get("IpEquip")),
            "inf1":             s(item.get("INF. 1")),
            "inf2":             s(item.get("INF. 2")),
            "inf3":             s(item.get("INF. 3")),
            "inf4":             s(item.get("INF. 4")),
            "inf5":             s(item.get("INF. 5")),
            "inf6":             s(item.get("INF. 6")),
            "inf7":             s(item.get("INF. 7")),
            "empresa":          s(item.get("empresa")),
            "filial":           s(item.get("filial")),
        })
    if not registros:
        return
    from supabase_sync import _chunks
    total = 0
    for lote in _chunks(registros, 250):
        try:
            supabase.rpc("sync_ativos", {"p_data": lote}).execute()
            total += len(lote)
        except Exception as e:
            logger.warning("Erro ao sincronizar lote de ativos (%d): %s", len(lote), e)
    logger.info("Upsert de %d/%d ativos concluído via RPC.", total, len(registros))


def upsert_os_supabase(supabase, os_list):
    """Upsert de OS via RPC sync_ordens_servico (SECURITY DEFINER)."""
    registros = []
    for o in os_list:
        if not o.numero:
            continue
        registros.append({
            "numero":          o.numero,
            "tipo":            o.tipo,
            "status":          o.status,
            "cliente":         o.cliente,
            "ativo_id":        o.equipamento,
            "descricao":       o.descricao,
            "tecnico":         o.tecnico,
            "data_abertura":   o.data_abertura,
            "data_fechamento": o.data_fechamento,
        })
    if not registros:
        return
    from supabase_sync import _chunks
    total = 0
    for lote in _chunks(registros, 500):
        try:
            r = _crm_sync_post("sync_ordens_servico", {"rows": lote})
            total += r.get("count", len(lote))
        except Exception as e:
            logger.warning("Erro em sync_ordens_servico (lote %d): %s", len(lote), e)
    logger.info("Upsert de %d/%d OS via crm-sync.", total, len(registros))


def upsert_carteira_supabase(supabase, carteira: list[dict]):
    """Upsert da carteira de contratos via RPC sync_carteira_contratos (SECURITY DEFINER)."""
    def s(v):
        return str(v).strip() if v is not None else ""

    registros = []
    for item in carteira:
        codigo = s(item.get("codigo"))
        if not codigo:
            continue
        registros.append({
            "id":              codigo,
            "numero_contrato": codigo,
            "cliente_codigo":  s(item.get("cliente")),
            "cliente_nome":    s(item.get("cliente_nome")),
            "situacao":        s(item.get("situacao")),
            "data_inicio":     s(item.get("datavigini")) or None,
            "data_fim":        s(item.get("datavigfim")) or None,
        })

    if not registros:
        logger.info("Carteira de contratos: nenhum registro para upsert.")
        return

    from supabase_sync import _chunks
    total = 0
    for lote in _chunks(registros, 500):
        try:
            r = _crm_sync_post("sync_carteira", {"rows": lote})
            total += r.get("count", len(lote))
        except Exception as e:
            logger.warning("Erro em sync_carteira (lote %d): %s", len(lote), e)
    logger.info("Upsert de %d/%d contratos na carteira_contratos via crm-sync.", total, len(registros))


def sync_contracts_native(supabase, carteira: list[dict]):
    """Atualiza start_date/end_date na tabela nativa contracts do CRM (lotes de 20)."""
    def s(v):
        return str(v).strip() if v is not None else ""

    from supabase_sync import _chunks

    registros = []
    for item in carteira:
        codigo = s(item.get("codigo"))
        if not codigo:
            continue
        registros.append({
            "numero_contrato": codigo,
            "data_inicio":     s(item.get("datavigini")) or None,
            "data_fim":        s(item.get("datavigfim")) or None,
        })
    if not registros:
        return
    total = 0
    for lote in _chunks(registros, 20):
        try:
            r = _crm_sync_post("sync_contracts_native", {"rows": lote})
            total += r.get("count", len(lote))
        except Exception as e:
            logger.warning("Erro em sync_contracts_native (lote %d): %s", len(lote), e)
    logger.info("sync_contracts_native: %d contrato(s) atualizados no CRM nativo.", total)


def sync_assets_contract_native(supabase, equipamentos: list[dict]):
    """Atualiza contract_id na tabela nativa assets do CRM."""
    def s(v):
        return str(v).strip() if v is not None else ""

    from supabase_sync import _chunks

    registros = []
    for item in equipamentos:
        equip = s(item.get("equipamento"))
        contrato = s(item.get("contrato"))
        if not equip or not contrato:
            continue
        registros.append({"equipamento": equip, "contrato": contrato})

    if not registros:
        return

    total = 0
    for lote in _chunks(registros, 500):
        try:
            r = _crm_sync_post("sync_assets_contract_native", {"rows": lote})
            total += r.get("count", len(lote))
        except Exception as e:
            logger.warning("Erro em sync_assets_contract_native (lote %d): %s", len(lote), e)
    logger.info("sync_assets_contract_native: %d ativo(s) vinculados ao contrato no CRM nativo.", total)


def update_ativos_contratos_bi(supabase, equipamentos: list[dict]):
    """
    Atualiza contrato e nome_fantasia em ativos via RPC sync_ativos_contratos.
    Passa todos os registros de uma vez — o PostgreSQL faz o UPDATE em lote.
    """
    from supabase_sync import _chunks

    def s(v):
        return str(v).strip() if v is not None else ""

    registros = []
    for item in equipamentos:
        equip = s(item.get("equipamento"))
        if not equip:
            continue
        registros.append({
            "equipamento":  equip,
            "contrato":     s(item.get("contrato")),
            "cliente_nome": s(item.get("cliente_nome")),
        })

    if not registros:
        return

    total = 0
    for lote in _chunks(registros, 500):
        try:
            r = _crm_sync_post("sync_ativos_contratos", {"rows": lote})
            total += r.get("count", len(lote))
        except Exception as e:
            logger.warning("Erro ao atualizar ativos via RPC (lote %d): %s", len(lote), e)

    logger.info("Ativos atualizados com contrato/cliente via crm-sync: %d", total)


def sync_bi_movimentacoes(supabase, movs: list[dict]):
    """Upsert de ctmequip na tabela bi_movimentacoes via bi-ingest Edge Function."""
    if not movs:
        return
    from supabase_sync import _chunks
    total = 0
    for lote in _chunks(movs, 500):
        try:
            total += _bi_ingest_post("bi_movimentacoes", lote)
        except Exception as e:
            logger.warning("Erro em sync_bi_movimentacoes (lote %d): %s", len(lote), e)
    logger.info("sync_bi_movimentacoes: %d/%d registros inseridos/atualizados.", total, len(movs))


def sync_bi_ctprod(supabase, ctprod: list[dict]):
    """Upsert de ctprod na tabela bi_ctprod via bi-ingest Edge Function."""
    if not ctprod:
        return
    from supabase_sync import _chunks
    total = 0
    for lote in _chunks(ctprod, 500):
        try:
            total += _bi_ingest_post("bi_ctprod", lote)
        except Exception as e:
            logger.warning("Erro em sync_bi_ctprod (lote %d): %s", len(lote), e)
    logger.info("sync_bi_ctprod: %d/%d registros inseridos/atualizados.", total, len(ctprod))


def sync_bi_faturamento(supabase, faturamento: list[dict]):
    """Upsert de docrec na tabela bi_faturamento via bi-ingest Edge Function."""
    if not faturamento:
        return
    from supabase_sync import _chunks
    total = 0
    for lote in _chunks(faturamento, 500):
        try:
            total += _bi_ingest_post("bi_faturamento", lote)
        except Exception as e:
            logger.warning("Erro em sync_bi_faturamento (lote %d): %s", len(lote), e)
    logger.info("sync_bi_faturamento: %d/%d registros inseridos/atualizados.", total, len(faturamento))


def sync_bi_ativos(supabase, ativos: list[dict]):
    """Upsert do catálogo de equipamentos na tabela bi_ativos via bi-ingest Edge Function.

    Cada registro traz:
      - Dados do equipamento (equip): codigo, produto, serial, situacao
      - Tipo/subtipo (produtos): grupo_descricao, grupo2_descricao
      - Posição atual (ctmequip): contrato_atual, ultimo_envret, data_ultimo_mov
      - Flag de inconsistência: situacao × envret divergem
    """
    if not ativos:
        return
    from supabase_sync import _chunks
    total = 0
    # Normalizar boolean → bool nativo (bi-ingest aceita JSON padrão)
    payload = [
        {**a, 'inconsistente': bool(a.get('inconsistente', False))}
        for a in ativos
    ]
    for lote in _chunks(payload, 500):
        try:
            total += _bi_ingest_post("bi_ativos", lote)
        except Exception as e:
            logger.warning("Erro em sync_bi_ativos (lote %d): %s", len(lote), e)
    inconsistentes = sum(1 for a in ativos if a.get('inconsistente'))
    logger.info(
        "sync_bi_ativos: %d/%d equipamentos sincronizados. Inconsistentes: %d",
        total, len(ativos), inconsistentes,
    )


async def processar_fila_criacao_os(pendentes: list[dict], supabase, api_token: str):
    """
    Cria OS no ELOCA via CGI para cada item da fila.
    Usa httpx direto (sem browser) — o CGI aceita POST autenticado.
    """
    import httpx
    from eloca_api import CGI_BASE

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
        for item in pendentes:
            fila_id = item["id"]
            marcar_os_processando(supabase, fila_id)

            try:
                # Monta o POST para criar a OS via CGI
                # ACAO=1 = incluir nova OS (verifique o valor real inspecionando
                # a requisição ao clicar em "Salvar" no formulário do ELOCA)
                form_data = {
                    "PRG":       "scp102a1",
                    "ACAO":      "1",
                    "ISAJAX":    "S",
                    "EMPRESA":   "",           # preenchido pelo server via sessão
                    "CLIENTE":   item.get("cliente", ""),
                    "EQUIPAMENTO": item.get("ativo_id", ""),
                    "TIPO":      item.get("tipo_servico", ""),
                    "DESCRICAO": item.get("descricao", ""),
                    "TECNICO":   item.get("tecnico", ""),
                    "DTPREV":    item.get("data_prevista", ""),
                    "api_token": api_token,
                }

                r = await http.post(CGI_BASE, data=form_data)
                r.raise_for_status()

                # Tenta extrair número da OS da resposta
                import re
                numero_os = "N/A"
                m = re.search(r'OS[:\s#]*(\d+)', r.text, re.IGNORECASE)
                if m:
                    numero_os = m.group(1)

                marcar_os_criada(supabase, fila_id, numero_os)
                logger.info("OS criada: %s (fila_id=%s)", numero_os, fila_id)

            except Exception as e:
                marcar_os_erro(supabase, fila_id, str(e))
                logger.error("Erro ao criar OS (fila_id=%s): %s", fila_id, e)


async def main():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(SYNC_TZ)

    logger.info("Integração ELOCA ↔ CRM Lovable iniciando …")
    logger.info("Cron: %s  Timezone: %s", SYNC_CRON, SYNC_TZ)

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        executar_sincronizacao,
        CronTrigger.from_crontab(SYNC_CRON, timezone=tz),
        id="sync_eloca",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

    if RUN_ON_START:
        await executar_sincronizacao()

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())


def sync_bi_contas_pagar(supabase, contas_pagar: list[dict]):
    """Upsert de docpag na tabela bi_contas_pagar via bi-ingest Edge Function."""
    if not contas_pagar:
        return
    from supabase_sync import _chunks
    total = 0
    for lote in _chunks(contas_pagar, 500):
        try:
            total += _bi_ingest_post("bi_contas_pagar", lote)
        except Exception as e:
            logger.warning("Erro em sync_bi_contas_pagar (lote %d): %s", len(lote), e)
    logger.info("sync_bi_contas_pagar: %d/%d registros.", total, len(contas_pagar))


def sync_bi_carteira_valor(supabase, carteira: list[dict]):
    """Upsert da carteira com valor mensal real via bi-ingest Edge Function."""
    if not carteira:
        return
    from supabase_sync import _chunks
    total = 0
    for lote in _chunks(carteira, 500):
        try:
            total += _bi_ingest_post("bi_carteira_valor", lote)
        except Exception as e:
            logger.warning("Erro em sync_bi_carteira_valor (lote %d): %s", len(lote), e)
    logger.info("sync_bi_carteira_valor: %d/%d contratos.", total, len(carteira))
