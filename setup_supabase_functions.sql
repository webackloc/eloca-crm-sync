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
-- Permissões: permite que a anon key chame as funções
-- ---------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION public.log_sync_inicio()            TO anon;
GRANT EXECUTE ON FUNCTION public.log_sync_fim(BIGINT, INT, INT, INT, TEXT[], FLOAT, TEXT) TO anon;
GRANT EXECUTE ON FUNCTION public.sync_carteira_contratos(JSONB) TO anon;
GRANT EXECUTE ON FUNCTION public.sync_ativos_contratos(JSONB)   TO anon;
GRANT EXECUTE ON FUNCTION public.sync_ativos(JSONB)             TO anon;
GRANT EXECUTE ON FUNCTION public.sync_ordens_servico(JSONB)     TO anon;
