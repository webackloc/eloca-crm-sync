-- =============================================================================
-- BLOCO 2 — Tabelas e funções para ctmequip, ctprod e docrec
-- Execute no SQL Editor do Supabase ANTES do Bloco 3
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Tabelas
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.bi_movimentacoes (
    recnum          BIGINT PRIMARY KEY,
    equipamento     TEXT,
    contrato        TEXT,
    envret          CHAR(1),
    data            DATE,
    setor           TEXT,
    numos           BIGINT,
    seq             INT,
    sincronizado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.bi_ctprod (
    recnum            BIGINT PRIMARY KEY,
    contrato          TEXT,
    produto           TEXT,
    produto_descricao TEXT,
    setor             TEXT,
    valor             NUMERIC,
    valorunitario     NUMERIC,
    sincronizado_em   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.bi_faturamento (
    numfatura         TEXT PRIMARY KEY,
    numsequencia      INT,
    contrato          TEXT,
    codigocliente     BIGINT,
    cliente           TEXT,
    valoremissao      NUMERIC,
    dataemissao       DATE,
    datavencto        DATE,
    liquidado         CHAR(1),
    tipodocumento     TEXT,
    representante     TEXT,
    representante_nome TEXT,
    sincronizado_em   TIMESTAMPTZ DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_bi_mov_equipamento ON public.bi_movimentacoes (equipamento);
CREATE INDEX IF NOT EXISTS idx_bi_mov_contrato    ON public.bi_movimentacoes (contrato);
CREATE INDEX IF NOT EXISTS idx_bi_mov_data        ON public.bi_movimentacoes (data);
CREATE INDEX IF NOT EXISTS idx_bi_ctprod_contrato ON public.bi_ctprod (contrato);
CREATE INDEX IF NOT EXISTS idx_bi_fat_contrato    ON public.bi_faturamento (contrato);
CREATE INDEX IF NOT EXISTS idx_bi_fat_dataemissao ON public.bi_faturamento (dataemissao);
CREATE INDEX IF NOT EXISTS idx_bi_fat_liquidado   ON public.bi_faturamento (liquidado);


-- ---------------------------------------------------------------------------
-- Funções SECURITY DEFINER
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.sync_bi_movimentacoes(p_data JSONB)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  INSERT INTO bi_movimentacoes (recnum, equipamento, contrato, envret, data, setor, numos, seq, sincronizado_em)
  SELECT
    (item->>'recnum')::BIGINT, item->>'equipamento', item->>'contrato', item->>'envret',
    NULLIF(item->>'data', '')::DATE, item->>'setor',
    NULLIF(item->>'numos', '')::BIGINT, NULLIF(item->>'seq', '')::INT, NOW()
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (recnum) DO UPDATE SET
    equipamento=EXCLUDED.equipamento, contrato=EXCLUDED.contrato, envret=EXCLUDED.envret,
    data=EXCLUDED.data, setor=EXCLUDED.setor, numos=EXCLUDED.numos,
    seq=EXCLUDED.seq, sincronizado_em=EXCLUDED.sincronizado_em;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.sync_bi_ctprod(p_data JSONB)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  INSERT INTO bi_ctprod (recnum, contrato, produto, produto_descricao, setor, valor, valorunitario, sincronizado_em)
  SELECT
    (item->>'recnum')::BIGINT, item->>'contrato', item->>'produto', item->>'produto_descricao',
    item->>'setor', NULLIF(item->>'valor', '')::NUMERIC, NULLIF(item->>'valorunitario', '')::NUMERIC, NOW()
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (recnum) DO UPDATE SET
    contrato=EXCLUDED.contrato, produto=EXCLUDED.produto, produto_descricao=EXCLUDED.produto_descricao,
    setor=EXCLUDED.setor, valor=EXCLUDED.valor, valorunitario=EXCLUDED.valorunitario,
    sincronizado_em=EXCLUDED.sincronizado_em;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.sync_bi_faturamento(p_data JSONB)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  INSERT INTO bi_faturamento (numfatura, numsequencia, contrato, codigocliente, cliente,
    valoremissao, dataemissao, datavencto, liquidado, tipodocumento,
    representante, representante_nome, sincronizado_em)
  SELECT
    item->>'numfatura', NULLIF(item->>'numsequencia', '')::INT,
    NULLIF(TRIM(item->>'contrato'), ''), NULLIF(item->>'codigocliente', '')::BIGINT,
    item->>'cliente', NULLIF(item->>'valoremissao', '')::NUMERIC,
    NULLIF(item->>'dataemissao', '')::DATE, NULLIF(item->>'datavencto', '')::DATE,
    item->>'liquidado', item->>'tipodocumento', item->>'representante',
    item->>'representante_nome', NOW()
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (numfatura) DO UPDATE SET
    numsequencia=EXCLUDED.numsequencia, contrato=EXCLUDED.contrato,
    codigocliente=EXCLUDED.codigocliente, cliente=EXCLUDED.cliente,
    valoremissao=EXCLUDED.valoremissao, dataemissao=EXCLUDED.dataemissao,
    datavencto=EXCLUDED.datavencto, liquidado=EXCLUDED.liquidado,
    tipodocumento=EXCLUDED.tipodocumento, representante=EXCLUDED.representante,
    representante_nome=EXCLUDED.representante_nome, sincronizado_em=EXCLUDED.sincronizado_em;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.sync_bi_movimentacoes(JSONB) TO anon;
GRANT EXECUTE ON FUNCTION public.sync_bi_ctprod(JSONB)        TO anon;
GRANT EXECUTE ON FUNCTION public.sync_bi_faturamento(JSONB)   TO anon;

-- Verificação final — deve retornar as 4 tabelas bi_
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name LIKE 'bi_%'
ORDER BY table_name;
