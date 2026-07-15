"""
Supabase Sync
Salva os dados extraídos do ELOCA no Supabase:
  - Faz upload dos CSVs no Supabase Storage (bucket "eloca-sync")
  - Upsert dos registros nas tabelas "ativos" e "ordens_servico"

Tabelas esperadas no Supabase (crie via SQL Editor ou migration no Lovable):

    CREATE TABLE IF NOT EXISTS ativos (
        id TEXT PRIMARY KEY,
        codigo TEXT,
        descricao TEXT,
        numero_serie TEXT,
        cliente TEXT,
        contrato TEXT,
        localizacao TEXT,
        status TEXT,
        data_instalacao TEXT,
        sincronizado_em TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS ordens_servico (
        numero TEXT PRIMARY KEY,
        tipo TEXT,
        status TEXT,
        cliente TEXT,
        ativo_id TEXT REFERENCES ativos(id),
        descricao TEXT,
        tecnico TEXT,
        data_abertura TEXT,
        data_fechamento TEXT,
        sincronizado_em TIMESTAMPTZ DEFAULT NOW()
    );

    -- Bucket de storage (execute no dashboard do Supabase)
    -- Storage > New Bucket > nome: "eloca-sync" > público: false
"""

import logging
import os
from datetime import datetime
from dataclasses import asdict

from supabase import create_client, Client

from eloca_api import Ativo, OrdemServico

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")  # service_role key (não anon)
STORAGE_BUCKET = os.getenv("SUPABASE_BUCKET", "eloca-sync")


# ---------------------------------------------------------------------------
# Cliente Supabase
# ---------------------------------------------------------------------------

def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError(
            "SUPABASE_URL e SUPABASE_SERVICE_KEY devem estar definidos nas variáveis de ambiente."
        )
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------------------------------------------------------------------------
# Upload de CSV para Storage
# ---------------------------------------------------------------------------

def upload_csv(client: Client, nome_arquivo: str, conteudo_csv: str) -> str:
    """
    Faz upload do CSV para o bucket Storage.
    Retorna a URL pública (ou path) do arquivo.
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = f"{timestamp}/{nome_arquivo}"

    logger.info("Fazendo upload: %s → bucket '%s'", path, STORAGE_BUCKET)

    conteudo_bytes = conteudo_csv.encode("utf-8")

    # Remove arquivo anterior com mesmo nome base (opcional — mantém histórico)
    # client.storage.from_(STORAGE_BUCKET).remove([path])

    res = client.storage.from_(STORAGE_BUCKET).upload(
        path=path,
        file=conteudo_bytes,
        file_options={"content-type": "text/csv; charset=utf-8"},
    )

    logger.info("Upload concluído: %s", path)
    return path


# ---------------------------------------------------------------------------
# Upsert de Ativos
# ---------------------------------------------------------------------------

def upsert_ativos(client: Client, ativos: list[Ativo]) -> int:
    """
    Insere ou atualiza registros na tabela 'ativos'.
    Retorna quantidade de registros processados.
    """
    if not ativos:
        logger.info("Nenhum ativo para sincronizar.")
        return 0

    registros = []
    for a in ativos:
        d = asdict(a)
        d.pop("extras", None)  # Remove campo extras (dict arbitrário)
        d["sincronizado_em"] = datetime.utcnow().isoformat()
        registros.append(d)

    logger.info("Upserting %d ativos …", len(registros))

    # Divide em lotes de 500 para evitar payload muito grande
    for lote in _chunks(registros, 500):
        client.table("ativos").upsert(lote, on_conflict="id").execute()

    logger.info("Ativos sincronizados com sucesso.")
    return len(registros)


# ---------------------------------------------------------------------------
# Upsert de Ordens de Serviço
# ---------------------------------------------------------------------------

def upsert_ordens_servico(client: Client, os_list: list[OrdemServico]) -> int:
    """
    Insere ou atualiza registros na tabela 'ordens_servico'.
    """
    if not os_list:
        logger.info("Nenhuma OS para sincronizar.")
        return 0

    registros = []
    for o in os_list:
        d = asdict(o)
        d.pop("extras", None)
        d["sincronizado_em"] = datetime.utcnow().isoformat()
        registros.append(d)

    logger.info("Upserting %d ordens de serviço …", len(registros))

    for lote in _chunks(registros, 500):
        client.table("ordens_servico").upsert(lote, on_conflict="numero").execute()

    logger.info("Ordens de serviço sincronizadas com sucesso.")
    return len(registros)


# ---------------------------------------------------------------------------
# Fila de criação de OS (CRM → ELOCA)
# ---------------------------------------------------------------------------

def buscar_os_pendentes_criacao(client: Client) -> list[dict]:
    """
    Busca no Supabase as OS que o CRM Lovable marcou para criar no ELOCA.
    O CRM deve ter uma tabela 'fila_criacao_os' com status 'pendente'.

    Estrutura esperada da tabela no Supabase:

        CREATE TABLE IF NOT EXISTS fila_criacao_os (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            cliente TEXT NOT NULL,
            ativo_id TEXT NOT NULL,
            tipo_servico TEXT NOT NULL,
            descricao TEXT,
            tecnico TEXT,
            data_prevista TEXT,
            prioridade TEXT DEFAULT 'Normal',
            status TEXT DEFAULT 'pendente',  -- 'pendente' | 'processando' | 'criada' | 'erro'
            numero_os_criada TEXT,
            erro TEXT,
            criado_em TIMESTAMPTZ DEFAULT NOW(),
            processado_em TIMESTAMPTZ
        );
    """
    res = (
        client.table("fila_criacao_os")
        .select("*")
        .eq("status", "pendente")
        .order("criado_em")
        .limit(50)
        .execute()
    )
    return res.data or []


def marcar_os_criada(client: Client, fila_id: str, numero_os: str):
    """Atualiza o registro na fila após criação bem-sucedida no ELOCA."""
    client.table("fila_criacao_os").update({
        "status": "criada",
        "numero_os_criada": numero_os,
        "processado_em": datetime.utcnow().isoformat(),
    }).eq("id", fila_id).execute()


def marcar_os_erro(client: Client, fila_id: str, mensagem_erro: str):
    """Atualiza o registro na fila com erro."""
    client.table("fila_criacao_os").update({
        "status": "erro",
        "erro": mensagem_erro,
        "processado_em": datetime.utcnow().isoformat(),
    }).eq("id", fila_id).execute()


def marcar_os_processando(client: Client, fila_id: str):
    """Marca como processando para evitar processamento duplo."""
    client.table("fila_criacao_os").update({
        "status": "processando",
    }).eq("id", fila_id).execute()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
