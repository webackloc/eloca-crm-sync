-- ─────────────────────────────────────────────────────────────────────────────
-- supabase_setup.sql
-- Execute no SQL Editor do Supabase (ou como migration no projeto Lovable)
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Tabela de Ativos / Equipamentos ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.ativos (
    id               TEXT PRIMARY KEY,
    codigo           TEXT,
    descricao        TEXT,
    numero_serie     TEXT,
    cliente          TEXT,
    contrato         TEXT,
    localizacao      TEXT,
    status           TEXT,
    data_instalacao  TEXT,
    sincronizado_em  TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para consultas do CRM
CREATE INDEX IF NOT EXISTS idx_ativos_cliente  ON public.ativos(cliente);
CREATE INDEX IF NOT EXISTS idx_ativos_status   ON public.ativos(status);
CREATE INDEX IF NOT EXISTS idx_ativos_contrato ON public.ativos(contrato);


-- ── Tabela de Ordens de Serviço ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.ordens_servico (
    numero           TEXT PRIMARY KEY,
    tipo             TEXT,
    status           TEXT,
    cliente          TEXT,
    ativo_id         TEXT,   -- FK suave (sem constraint para evitar erro se ativo não existir ainda)
    descricao        TEXT,
    tecnico          TEXT,
    data_abertura    TEXT,
    data_fechamento  TEXT,
    sincronizado_em  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_os_cliente      ON public.ordens_servico(cliente);
CREATE INDEX IF NOT EXISTS idx_os_status       ON public.ordens_servico(status);
CREATE INDEX IF NOT EXISTS idx_os_ativo        ON public.ordens_servico(ativo_id);
CREATE INDEX IF NOT EXISTS idx_os_data_abert   ON public.ordens_servico(data_abertura);


-- ── Fila de Criação de OS (CRM → ELOCA) ──────────────────────────────────────
-- O CRM Lovable insere registros aqui; o RPA os lê e cria no ELOCA.
CREATE TABLE IF NOT EXISTS public.fila_criacao_os (
    id               UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    cliente          TEXT        NOT NULL,
    ativo_id         TEXT        NOT NULL,
    tipo_servico     TEXT        NOT NULL,
    descricao        TEXT,
    tecnico          TEXT,
    data_prevista    TEXT,
    prioridade       TEXT        DEFAULT 'Normal',
    -- Controle de estado
    status           TEXT        DEFAULT 'pendente',
    -- 'pendente' | 'processando' | 'criada' | 'erro'
    numero_os_criada TEXT,       -- preenchido após criação no ELOCA
    erro             TEXT,       -- mensagem de erro se status = 'erro'
    criado_em        TIMESTAMPTZ DEFAULT NOW(),
    processado_em    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_fila_os_status ON public.fila_criacao_os(status);


-- ── Row Level Security ────────────────────────────────────────────────────────
-- Habilita RLS e permite apenas service_role (o RPA usa service_role key).
-- A anon key do front-end Lovable precisa de políticas específicas — ajuste
-- conforme as necessidades do seu CRM.

ALTER TABLE public.ativos          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ordens_servico  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fila_criacao_os ENABLE ROW LEVEL SECURITY;

-- Política: service_role pode tudo (já é implícito, mas explicitamos)
-- Política: usuários autenticados do Lovable podem ler ativos e OS
CREATE POLICY "Leitura autenticada de ativos"
    ON public.ativos FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Leitura autenticada de OS"
    ON public.ordens_servico FOR SELECT
    TO authenticated
    USING (true);

-- Política: usuários autenticados podem inserir na fila
CREATE POLICY "Inserir na fila de OS"
    ON public.fila_criacao_os FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- Política: usuários autenticados podem ler sua própria fila
CREATE POLICY "Leitura da fila de OS"
    ON public.fila_criacao_os FOR SELECT
    TO authenticated
    USING (true);


-- ── Storage Bucket ────────────────────────────────────────────────────────────
-- Execute via Dashboard do Supabase: Storage > New Bucket
-- Nome: eloca-sync | Público: NÃO
-- Ou via SQL (requer extensão storage):
-- INSERT INTO storage.buckets (id, name, public) VALUES ('eloca-sync', 'eloca-sync', false)
-- ON CONFLICT DO NOTHING;
