-- =============================================================================
-- Funções SECURITY DEFINER para integração ELOCA BI → Supabase
-- Execute este script no SQL Editor do Lovable (ou Supabase direto)
-- Permite que a anon key escreva nas tabelas de sync SEM desabilitar RLS
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 1. log_sync_inicio — registra início do ciclo em sync_logs
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.log_sync_inicio()
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE v_id BIGINT;
BEGIN
  INSERT INTO sync_logs (iniciado_em, status)
  VALUES (NOW(), 'rodando')
  RETURNING id INTO v_id;
  RETURN v_id;
END;
$$;


-- ---------------------------------------------------------------------------
-- 2. log_sync_fim — atualiza o registro de log com resultado do ciclo
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.log_sync_fim(
  p_log_id        BIGINT,
  p_ativos_total  INT,
  p_os_total      INT,
  p_carteira_total INT,
  p_erros         TEXT[],
  p_duracao       FLOAT,
  p_status        TEXT
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE sync_logs SET
    concluido_em     = NOW(),
    duracao_segundos = p_duracao,
    ativos_total     = p_ativos_total,
    os_total         = p_os_total,
    carteira_total   = p_carteira_total,
    erros            = p_erros,
    status           = p_status
  WHERE id = p_log_id;
END;
$$;


-- ---------------------------------------------------------------------------
-- 3. sync_carteira_contratos — upsert da carteira vinda do BI SQL Server
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_carteira_contratos(p_data JSONB)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO carteira_contratos (
    id, numero_contrato, cliente_codigo, cliente_nome,
    situacao, data_inicio, data_fim, sincronizado_em
  )
  SELECT
    item->>'id',
    item->>'numero_contrato',
    item->>'cliente_codigo',
    item->>'cliente_nome',
    item->>'situacao',
    item->>'data_inicio',
    item->>'data_fim',
    NOW()
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (id) DO UPDATE SET
    numero_contrato = EXCLUDED.numero_contrato,
    cliente_codigo  = EXCLUDED.cliente_codigo,
    cliente_nome    = EXCLUDED.cliente_nome,
    situacao        = EXCLUDED.situacao,
    data_inicio     = EXCLUDED.data_inicio,
    data_fim        = EXCLUDED.data_fim,
    sincronizado_em = EXCLUDED.sincronizado_em;
END;
$$;


-- ---------------------------------------------------------------------------
-- 4. sync_ativos_contratos — atualiza contrato/cliente em ativos via BI
--    Recebe array de {equipamento, contrato, cliente_nome}
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_ativos_contratos(p_data JSONB)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE ativos a
  SET
    contrato      = item->>'contrato',
    nome_fantasia = item->>'cliente_nome',
    sincronizado_em = NOW()
  FROM jsonb_array_elements(p_data) AS item
  WHERE a.codigo = item->>'equipamento';
END;
$$;


-- ---------------------------------------------------------------------------
-- 5. sync_ativos — upsert completo de ativos vindos da API ELOCA
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_ativos(p_data JSONB)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO ativos (
    id, codigo, numero_serie, descricao, cod_produto, produto,
    status, situacao_os, tipo_os, os_aberta, os_instalacao, ult_os,
    cliente, nome_fantasia, localizacao, local_contrato, setor,
    endereco, numero_endereco, bairro, complemento, municipio, uf, cep,
    contrato, grupo, grupo2, marca, modelo, data_instalacao,
    ano_fabricacao, termino_garantia, nota_fiscal, valor_compra,
    valor_mercado, fornecedor, proprietario, usado, envio, ult_retorno,
    ip, inf1, inf2, inf3, inf4, inf5, inf6, inf7, empresa, filial,
    sincronizado_em
  )
  SELECT
    item->>'id', item->>'codigo', item->>'numero_serie', item->>'descricao',
    item->>'cod_produto', item->>'produto', item->>'status',
    item->>'situacao_os', item->>'tipo_os', item->>'os_aberta',
    item->>'os_instalacao', item->>'ult_os', item->>'cliente',
    item->>'nome_fantasia', item->>'localizacao', item->>'local_contrato',
    item->>'setor', item->>'endereco', item->>'numero_endereco',
    item->>'bairro', item->>'complemento', item->>'municipio',
    item->>'uf', item->>'cep', item->>'contrato', item->>'grupo',
    item->>'grupo2', item->>'marca', item->>'modelo',
    item->>'data_instalacao', item->>'ano_fabricacao',
    item->>'termino_garantia', item->>'nota_fiscal', item->>'valor_compra',
    item->>'valor_mercado', item->>'fornecedor', item->>'proprietario',
    item->>'usado', item->>'envio', item->>'ult_retorno', item->>'ip',
    item->>'inf1', item->>'inf2', item->>'inf3', item->>'inf4',
    item->>'inf5', item->>'inf6', item->>'inf7', item->>'empresa',
    item->>'filial', NOW()
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (id) DO UPDATE SET
    codigo          = EXCLUDED.codigo,
    numero_serie    = EXCLUDED.numero_serie,
    descricao       = EXCLUDED.descricao,
    cod_produto     = EXCLUDED.cod_produto,
    produto         = EXCLUDED.produto,
    status          = EXCLUDED.status,
    situacao_os     = EXCLUDED.situacao_os,
    tipo_os         = EXCLUDED.tipo_os,
    os_aberta       = EXCLUDED.os_aberta,
    os_instalacao   = EXCLUDED.os_instalacao,
    ult_os          = EXCLUDED.ult_os,
    cliente         = EXCLUDED.cliente,
    nome_fantasia   = EXCLUDED.nome_fantasia,
    localizacao     = EXCLUDED.localizacao,
    local_contrato  = EXCLUDED.local_contrato,
    setor           = EXCLUDED.setor,
    endereco        = EXCLUDED.endereco,
    numero_endereco = EXCLUDED.numero_endereco,
    bairro          = EXCLUDED.bairro,
    complemento     = EXCLUDED.complemento,
    municipio       = EXCLUDED.municipio,
    uf              = EXCLUDED.uf,
    cep             = EXCLUDED.cep,
    contrato        = EXCLUDED.contrato,
    grupo           = EXCLUDED.grupo,
    grupo2          = EXCLUDED.grupo2,
    marca           = EXCLUDED.marca,
    modelo          = EXCLUDED.modelo,
    data_instalacao = EXCLUDED.data_instalacao,
    ano_fabricacao  = EXCLUDED.ano_fabricacao,
    termino_garantia = EXCLUDED.termino_garantia,
    nota_fiscal     = EXCLUDED.nota_fiscal,
    valor_compra    = EXCLUDED.valor_compra,
    valor_mercado   = EXCLUDED.valor_mercado,
    fornecedor      = EXCLUDED.fornecedor,
    proprietario    = EXCLUDED.proprietario,
    usado           = EXCLUDED.usado,
    envio           = EXCLUDED.envio,
    ult_retorno     = EXCLUDED.ult_retorno,
    ip              = EXCLUDED.ip,
    inf1            = EXCLUDED.inf1,
    inf2            = EXCLUDED.inf2,
    inf3            = EXCLUDED.inf3,
    inf4            = EXCLUDED.inf4,
    inf5            = EXCLUDED.inf5,
    inf6            = EXCLUDED.inf6,
    inf7            = EXCLUDED.inf7,
    empresa         = EXCLUDED.empresa,
    filial          = EXCLUDED.filial,
    sincronizado_em = EXCLUDED.sincronizado_em;
END;
$$;


-- ---------------------------------------------------------------------------
-- 6. sync_ordens_servico — upsert de OS vindas do CGI ELOCA
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_ordens_servico(p_data JSONB)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO ordens_servico (
    numero, tipo, status, cliente, ativo_id,
    descricao, tecnico, data_abertura, data_fechamento, sincronizado_em
  )
  SELECT
    item->>'numero', item->>'tipo', item->>'status',
    item->>'cliente', item->>'ativo_id', item->>'descricao',
    item->>'tecnico', item->>'data_abertura', item->>'data_fechamento',
    NOW()
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (numero) DO UPDATE SET
    tipo            = EXCLUDED.tipo,
    status          = EXCLUDED.status,
    cliente         = EXCLUDED.cliente,
    ativo_id        = EXCLUDED.ativo_id,
    descricao       = EXCLUDED.descricao,
    tecnico         = EXCLUDED.tecnico,
    data_abertura   = EXCLUDED.data_abertura,
    data_fechamento = EXCLUDED.data_fechamento,
    sincronizado_em = EXCLUDED.sincronizado_em;
END;
$$;


-- ---------------------------------------------------------------------------
-- 7. cleanup_carteira_contratos — remove contratos que não estão mais ativos no BI
--    Recebe array de IDs ativos; deleta tudo que não estiver na lista
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.cleanup_carteira_contratos(p_ids JSONB)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  DELETE FROM carteira_contratos
  WHERE id NOT IN (
    SELECT value::text FROM jsonb_array_elements_text(p_ids)
  );
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;


-- ---------------------------------------------------------------------------
-- 8. sync_contracts_native — atualiza datas de vigência nas tabelas nativas do CRM
--    Recebe array de {numero_contrato, data_inicio, data_fim}
--    Faz match por contracts.contract_number
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_contracts_native(p_data JSONB)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  UPDATE contracts c
  SET
    start_date = TO_DATE(NULLIF(item->>'data_inicio', ''), 'YYYY-MM-DD'),
    end_date   = TO_DATE(NULLIF(item->>'data_fim',    ''), 'YYYY-MM-DD'),
    updated_at = NOW()
  FROM jsonb_array_elements(p_data) AS item
  WHERE c.contract_number = item->>'numero_contrato';
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;


-- ---------------------------------------------------------------------------
-- 9. sync_assets_contract_native — vincula assets ao contrato correto (contract_id UUID)
--    Recebe array de {equipamento, contrato}
--    Faz match por assets.name = equipamento; busca contract_id via contract_number
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_assets_contract_native(p_data JSONB)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  UPDATE assets a
  SET
    contract_id = (
      SELECT c.id FROM contracts c
      WHERE c.contract_number = item->>'contrato'
      LIMIT 1
    ),
    updated_at = NOW()
  FROM jsonb_array_elements(p_data) AS item
  WHERE a.name = item->>'equipamento'
    AND (item->>'contrato') IS NOT NULL
    AND (item->>'contrato') != '';
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;


-- ---------------------------------------------------------------------------
-- Permissões: permite que a anon key chame as funções
-- ---------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION public.log_sync_inicio()            TO anon;
GRANT EXECUTE ON FUNCTION public.log_sync_fim(BIGINT, INT, INT, INT, TEXT[], FLOAT, TEXT) TO anon;
GRANT EXECUTE ON FUNCTION public.sync_carteira_contratos(JSONB) TO anon;
GRANT EXECUTE ON FUNCTION public.sync_ativos_contratos(JSONB)   TO anon;
GRANT EXECUTE ON FUNCTION public.sync_ativos(JSONB)             TO anon;
GRANT EXECUTE ON FUNCTION public.sync_ordens_servico(JSONB)     TO anon;
GRANT EXECUTE ON FUNCTION public.cleanup_carteira_contratos(JSONB) TO anon;
GRANT EXECUTE ON FUNCTION public.sync_contracts_native(JSONB)       TO anon;
GRANT EXECUTE ON FUNCTION public.sync_assets_contract_native(JSONB) TO anon;


-- =============================================================================
-- BLOCO 2 — Tabelas e funções para ctmequip, ctprod e docrec
-- Execute após o Bloco 1 já estar aplicado
-- =============================================================================


-- ---------------------------------------------------------------------------
-- Tabelas BI
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.bi_movimentacoes (
    recnum          BIGINT PRIMARY KEY,
    equipamento     TEXT,
    contrato        TEXT,
    envret          CHAR(1),          -- 'E' = entrega, 'R' = retirada
    data            DATE,
    setor           TEXT,             -- plano/configuração no momento da mov.
    numos           BIGINT,           -- número da OS associada
    seq             INT,
    sincronizado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.bi_ctprod (
    recnum            BIGINT PRIMARY KEY,
    contrato          TEXT,
    produto           TEXT,
    produto_descricao TEXT,
    setor             TEXT,        -- nome do cliente/segmento no momento do contrato
    valor             NUMERIC,     -- valor total do item no contrato
    valorunitario     NUMERIC,     -- preço unitário mensal de locação
    sincronizado_em   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.bi_faturamento (
    numfatura        TEXT PRIMARY KEY,  -- formato variado ex: '10092024', '4291'
    numsequencia     INT,
    contrato         TEXT,              -- NULL quando faturamento avulso (sem contrato)
    codigocliente    BIGINT,
    cliente          TEXT,
    valoremissao     NUMERIC,
    dataemissao      DATE,
    datavencto       DATE,
    liquidado        CHAR(1),          -- 'S' = liquidado, ' ' = em aberto
    tipodocumento    TEXT,
    representante    TEXT,
    representante_nome TEXT,
    sincronizado_em  TIMESTAMPTZ DEFAULT NOW()
);

-- Índices de consulta frequente
CREATE INDEX IF NOT EXISTS idx_bi_mov_equipamento ON public.bi_movimentacoes (equipamento);
CREATE INDEX IF NOT EXISTS idx_bi_mov_contrato    ON public.bi_movimentacoes (contrato);
CREATE INDEX IF NOT EXISTS idx_bi_mov_data        ON public.bi_movimentacoes (data);
CREATE INDEX IF NOT EXISTS idx_bi_ctprod_contrato ON public.bi_ctprod (contrato);
CREATE INDEX IF NOT EXISTS idx_bi_fat_contrato    ON public.bi_faturamento (contrato);
CREATE INDEX IF NOT EXISTS idx_bi_fat_dataemissao ON public.bi_faturamento (dataemissao);
CREATE INDEX IF NOT EXISTS idx_bi_fat_liquidado   ON public.bi_faturamento (liquidado);


-- ---------------------------------------------------------------------------
-- 10. sync_bi_movimentacoes — upsert de ctmequip
--     Recebe array de {recnum, equipamento, contrato, envret, data,
--                      setor, numos, local, seq, quantidade, valor,
--                      horimetro, observacao}
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_bi_movimentacoes(p_data JSONB)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  INSERT INTO bi_movimentacoes (
    recnum, equipamento, contrato, envret, data,
    setor, numos, seq, sincronizado_em
  )
  SELECT
    (item->>'recnum')::BIGINT,
    item->>'equipamento',
    item->>'contrato',
    item->>'envret',
    NULLIF(item->>'data', '')::DATE,
    item->>'setor',
    NULLIF(item->>'numos', '')::BIGINT,
    NULLIF(item->>'seq', '')::INT,
    NOW()
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (recnum) DO UPDATE SET
    equipamento     = EXCLUDED.equipamento,
    contrato        = EXCLUDED.contrato,
    envret          = EXCLUDED.envret,
    data            = EXCLUDED.data,
    setor           = EXCLUDED.setor,
    numos           = EXCLUDED.numos,
    seq             = EXCLUDED.seq,
    sincronizado_em = EXCLUDED.sincronizado_em;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;


-- ---------------------------------------------------------------------------
-- 11. sync_bi_ctprod — upsert de ctprod
--     Recebe array de {recnum, contrato, produto, produto_descricao,
--                      setor, valor, valorunitario, seqequip}
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_bi_ctprod(p_data JSONB)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  INSERT INTO bi_ctprod (
    recnum, contrato, produto, produto_descricao,
    setor, valor, valorunitario, sincronizado_em
  )
  SELECT
    (item->>'recnum')::BIGINT,
    item->>'contrato',
    item->>'produto',
    item->>'produto_descricao',
    item->>'setor',
    NULLIF(item->>'valor', '')::NUMERIC,
    NULLIF(item->>'valorunitario', '')::NUMERIC,
    NOW()
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (recnum) DO UPDATE SET
    contrato          = EXCLUDED.contrato,
    produto           = EXCLUDED.produto,
    produto_descricao = EXCLUDED.produto_descricao,
    setor             = EXCLUDED.setor,
    valor             = EXCLUDED.valor,
    valorunitario     = EXCLUDED.valorunitario,
    sincronizado_em   = EXCLUDED.sincronizado_em;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;


-- ---------------------------------------------------------------------------
-- 12. sync_bi_faturamento — upsert de docrec
--     Recebe array de {numfatura, numsequencia, contrato, codigocliente,
--                      cliente, valoremissao, dataemissao, datavencto,
--                      liquidado, tipodocumento, representante, representante_nome}
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_bi_faturamento(p_data JSONB)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE v_count INT;
BEGIN
  INSERT INTO bi_faturamento (
    numfatura, numsequencia, contrato, codigocliente,
    cliente, valoremissao, dataemissao, datavencto,
    liquidado, tipodocumento, representante, representante_nome,
    sincronizado_em
  )
  SELECT
    item->>'numfatura',
    NULLIF(item->>'numsequencia', '')::INT,
    NULLIF(TRIM(item->>'contrato'), ''),   -- branco → NULL
    NULLIF(item->>'codigocliente', '')::BIGINT,
    item->>'cliente',
    NULLIF(item->>'valoremissao', '')::NUMERIC,
    NULLIF(item->>'dataemissao', '')::DATE,
    NULLIF(item->>'datavencto', '')::DATE,
    item->>'liquidado',
    item->>'tipodocumento',
    item->>'representante',
    item->>'representante_nome',
    NOW()
  FROM jsonb_array_elements(p_data) AS item
  ON CONFLICT (numfatura) DO UPDATE SET
    numsequencia      = EXCLUDED.numsequencia,
    contrato          = EXCLUDED.contrato,
    codigocliente     = EXCLUDED.codigocliente,
    cliente           = EXCLUDED.cliente,
    valoremissao      = EXCLUDED.valoremissao,
    dataemissao       = EXCLUDED.dataemissao,
    datavencto        = EXCLUDED.datavencto,
    liquidado         = EXCLUDED.liquidado,
    tipodocumento     = EXCLUDED.tipodocumento,
    representante     = EXCLUDED.representante,
    representante_nome = EXCLUDED.representante_nome,
    sincronizado_em   = EXCLUDED.sincronizado_em;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;


-- Permissões para as novas funções
GRANT EXECUTE ON FUNCTION public.sync_bi_movimentacoes(JSONB) TO anon;
GRANT EXECUTE ON FUNCTION public.sync_bi_ctprod(JSONB)        TO anon;
GRANT EXECUTE ON FUNCTION public.sync_bi_faturamento(JSONB)   TO anon;


-- =============================================================================
-- BLOCO 3 — Tabela e função para catálogo de ativos (equip + produtos + posição)
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.bi_ativos (
    codigo              TEXT PRIMARY KEY,   -- equip.codigo (ID do equipamento)
    codigoproduto       TEXT,               -- equip.codigoproduto
    produto_descricao   TEXT,               -- equip.produto
    serial_fabricante   TEXT,               -- equip.seriefabricante
    situacao            TEXT,               -- INDISPONÍVEL / DISPONÍVEL
    tipo_equipamento    TEXT,               -- produtos.grupo_descricao
    subtipo_equipamento TEXT,               -- produtos.grupo2_descricao
    contrato_atual      TEXT,               -- ctmequip último movimento (contrato)
    ultimo_envret       CHAR(1),            -- 'E' = em contrato, 'R' = devolvido
    data_ultimo_mov     DATE,               -- data do último movimento
    inconsistente       BOOLEAN DEFAULT FALSE, -- situacao × envret divergem
    sincronizado_em     TIMESTAMPTZ DEFAULT NOW(),
    bi_updated_at       TIMESTAMPTZ         -- equip.created_at do BI
);

CREATE INDEX IF NOT EXISTS idx_bi_ativos_situacao       ON public.bi_ativos (situacao);
CREATE INDEX IF NOT EXISTS idx_bi_ativos_contrato       ON public.bi_ativos (contrato_atual);
CREATE INDEX IF NOT EXISTS idx_bi_ativos_codigoproduto  ON public.bi_ativos (codigoproduto);
CREATE INDEX IF NOT EXISTS idx_bi_ativos_tipo           ON public.bi_ativos (tipo_equipamento);


-- ---------------------------------------------------------------------------
-- 13. sync_bi_ativos — upsert do catálogo de equipamentos
--     Recebe array de {codigo, codigoproduto, produto_descricao,
--                      serial_fabricante, situacao, tipo_equipamento,
--                      subtipo_equipamento, contrato_atual, ultimo_envret,
--                      data_ultimo_mov, inconsistente, bi_updated_at}
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
