-- =============================================================================
-- sync_state_migration.sql
-- Tabela de controle para sync incremental (evita full-dump a cada ciclo)
--
-- Rodar no SQL Editor do Supabase (uma única vez)
-- =============================================================================

-- ── Tabela de estado ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sync_state (
    tabela        TEXT        PRIMARY KEY,
    ultimo_recnum BIGINT      NOT NULL DEFAULT 0,
    ultima_sync   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Linha inicial para cada tabela gerenciada
INSERT INTO sync_state (tabela, ultimo_recnum) VALUES
    ('bi_movimentacoes', 0),
    ('bi_ctprod',        0),
    ('bi_faturamento',   0)
ON CONFLICT (tabela) DO NOTHING;

-- ── RPC: lê o último recnum de uma tabela ─────────────────────────────────────
CREATE OR REPLACE FUNCTION get_sync_state(p_tabela TEXT)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_recnum BIGINT;
BEGIN
    SELECT ultimo_recnum INTO v_recnum
    FROM sync_state
    WHERE tabela = p_tabela;
    RETURN COALESCE(v_recnum, 0);
END;
$$;

-- ── RPC: salva o último recnum após sync bem-sucedido ─────────────────────────
CREATE OR REPLACE FUNCTION update_sync_state(p_tabela TEXT, p_recnum BIGINT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO sync_state (tabela, ultimo_recnum, ultima_sync)
    VALUES (p_tabela, p_recnum, NOW())
    ON CONFLICT (tabela) DO UPDATE
        SET ultimo_recnum = EXCLUDED.ultimo_recnum,
            ultima_sync   = NOW();
END;
$$;

GRANT EXECUTE ON FUNCTION get_sync_state(TEXT)         TO anon;
GRANT EXECUTE ON FUNCTION update_sync_state(TEXT, BIGINT) TO anon;
