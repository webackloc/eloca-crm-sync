-- =============================================================================
-- BLOCO 3 — Tabela e função para catálogo de ativos (equip + produtos + posição)
-- Execute no SQL Editor do Supabase (dashboard.supabase.com → SQL Editor)
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.bi_ativos (
    codigo              TEXT PRIMARY KEY,   -- equip.codigo (ID do equipamento)
    codigoproduto       TEXT,               -- equip.codigoproduto
    produto_descricao   TEXT,               -- equip.produto
    serial_fabricante   TEXT,               -- equip.seriefabricante
    situacao            TEXT,               -- INDISPONÍVEL / DISPONÍVEL
    tipo_equipamento    TEXT,               -- produtos.grupo_descricao
    subtipo_equipamento TEXT,               -- produtos.grupo2_descricao
    contrato_atual      TEXT,               -- último movimento (contrato)
    ultimo_envret       CHAR(1),            -- 'E' = em contrato, 'R' = devolvido
    data_ultimo_mov     DATE,
    inconsistente       BOOLEAN DEFAULT FALSE,
    sincronizado_em     TIMESTAMPTZ DEFAULT NOW(),
    bi_updated_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bi_ativos_situacao      ON public.bi_ativos (situacao);
CREATE INDEX IF NOT EXISTS idx_bi_ativos_contrato      ON public.bi_ativos (contrato_atual);
CREATE INDEX IF NOT EXISTS idx_bi_ativos_codigoproduto ON public.bi_ativos (codigoproduto);
CREATE INDEX IF NOT EXISTS idx_bi_ativos_tipo          ON public.bi_ativos (tipo_equipamento);


-- ---------------------------------------------------------------------------
-- sync_bi_ativos — upsert do catálogo completo de equipamentos
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_bi_ativos(p_data JSONB)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  INSERT INTO bi_ativos (
    codigo, codigoproduto, produto_descricao,
    serial_fabricante, situacao,
    tipo_equipamento, subtipo_equipamento,
    contrato_atual, ultimo_envret, data_ultimo_mov,
    inconsistente, sincronizado_em, bi_updated_at
  )
  SELECT
    item->>'codigo',
    NULLIF(item->>'codigoproduto', ''),
    NULLIF(item->>'produto_descricao', ''),
    NULLIF(item->>'serial_fabricante', ''),
    item->>'situacao',
    NULLIF(item->>'tipo_equipamento', ''),
    NULLIF(item->>'subtipo_equipamento', ''),
    NULLIF(item->>'contrato_atual', ''),
    NULLIF(item->>'ultimo_envret', ''),
    NULLIF(item->>'data_ultimo_mov', '')::DATE,
    (item->>'inconsistente')::BOOLEAN,
    NOW(),
    NULLIF(item->>'bi_updated_at', '')::TIMESTAMPTZ
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (codigo) DO UPDATE SET
    codigoproduto       = EXCLUDED.codigoproduto,
    produto_descricao   = EXCLUDED.produto_descricao,
    serial_fabricante   = EXCLUDED.serial_fabricante,
    situacao            = EXCLUDED.situacao,
    tipo_equipamento    = EXCLUDED.tipo_equipamento,
    subtipo_equipamento = EXCLUDED.subtipo_equipamento,
    contrato_atual      = EXCLUDED.contrato_atual,
    ultimo_envret       = EXCLUDED.ultimo_envret,
    data_ultimo_mov     = EXCLUDED.data_ultimo_mov,
    inconsistente       = EXCLUDED.inconsistente,
    sincronizado_em     = EXCLUDED.sincronizado_em,
    bi_updated_at       = EXCLUDED.bi_updated_at;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.sync_bi_ativos(JSONB) TO anon;

-- Verificação: deve retornar as 4 tabelas bi_ e a nova bi_ativos
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name LIKE 'bi_%'
ORDER BY table_name;
