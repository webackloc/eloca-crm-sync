"""
validar_dados_bi.py — Simula exatamente o que seria enviado ao CRM
para bi_movimentacoes, bi_ctprod e bi_faturamento.

NÃO escreve nada no Supabase. Apenas mostra o que seria enviado.

Uso:
  BI_PASSWORD="..." python3 src/validar_dados_bi.py
"""
import os
import pymssql

conn = pymssql.connect(
    server   = os.getenv("BI_HOST", "og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com"),
    port     = int(os.getenv("BI_PORT", "1433")),
    user     = os.getenv("BI_USER", "weback"),
    password = os.getenv("BI_PASSWORD", ""),
    database = os.getenv("BI_DATABASE", "biweback"),
    timeout  = 120, charset="UTF-8",
)
cur = conn.cursor(as_dict=True)
SEP = "\n" + "═"*70

# ══════════════════════════════════════════════════════════════════════
# 1. BI_MOVIMENTACOES (ctmequip)
# ══════════════════════════════════════════════════════════════════════
print(SEP)
print("1. BI_MOVIMENTACOES — o que seria enviado (ctmequip)")
print(SEP)

cur.execute("""
    SELECT
        CONVERT(VARCHAR(20), recnum)    AS recnum,
        CONVERT(VARCHAR(20), equipamento) AS equipamento,
        CONVERT(VARCHAR(20), contrato)  AS contrato,
        CONVERT(VARCHAR(1),  envret)    AS envret,
        CONVERT(VARCHAR(10), data, 120) AS data,
        ISNULL(CONVERT(VARCHAR(500), setor), '') AS setor,
        CONVERT(VARCHAR(20), numos)     AS numos,
        ISNULL(CONVERT(VARCHAR(100), local), '') AS local,
        CONVERT(VARCHAR(20), seq)       AS seq,
        CONVERT(VARCHAR(30), quantidade) AS quantidade,
        CONVERT(VARCHAR(30), valor)     AS valor,
        CONVERT(VARCHAR(30), horimetro) AS horimetro,
        ISNULL(CONVERT(VARCHAR(1000), observacao), '') AS observacao
    FROM ctmequip
    ORDER BY recnum
""")
rows = cur.fetchall()

print(f"\nTotal de registros: {len(rows)}")

# Amostra — 5 mais recentes
print("\n--- Amostra (5 mais recentes por recnum) ---")
for r in rows[-5:]:
    print(dict(r))

# Qualidade dos campos chave
sem_recnum    = sum(1 for r in rows if not r['recnum'])
sem_equip     = sum(1 for r in rows if not r['equipamento'])
sem_contrato  = sum(1 for r in rows if not r['contrato'])
sem_data      = sum(1 for r in rows if not r['data'])
sem_envret    = sum(1 for r in rows if not r['envret'])
print(f"\n--- Qualidade dos campos chave ---")
print(f"  sem recnum:    {sem_recnum}")
print(f"  sem equipamento: {sem_equip}")
print(f"  sem contrato:  {sem_contrato}")
print(f"  sem data:      {sem_data}")
print(f"  sem envret:    {sem_envret}")

# Equipamentos que existem no BI mas NÃO existem em ctmequip (para checar cobertura)
cur.execute("""
    SELECT COUNT(DISTINCT equipamento) AS equip_com_mov
    FROM ctmequip
    WHERE equipamento IS NOT NULL AND equipamento != ''
""")
print(f"\n--- Equipamentos únicos com movimentação: {cur.fetchone()['equip_com_mov']} ---")


# ══════════════════════════════════════════════════════════════════════
# 2. BI_CTPROD (ctprod)
# ══════════════════════════════════════════════════════════════════════
print(SEP)
print("2. BI_CTPROD — o que seria enviado (ctprod)")
print(SEP)

cur.execute("""
    SELECT
        CONVERT(VARCHAR(20), cp.recnum)       AS recnum,
        CONVERT(VARCHAR(20), cp.contrato)     AS contrato,
        CONVERT(VARCHAR(20), cp.produto)      AS produto,
        ISNULL(CONVERT(VARCHAR(500), p.descricao), cp.produto) AS produto_descricao,
        ISNULL(CONVERT(VARCHAR(500), cp.setor), '') AS setor,
        CONVERT(VARCHAR(30), cp.valor)        AS valor,
        CONVERT(VARCHAR(30), cp.valorunitario) AS valorunitario,
        CONVERT(VARCHAR(20), cp.seqequip)     AS seqequip
    FROM ctprod cp
    LEFT JOIN produtos p ON p.codigo = cp.produto
    ORDER BY cp.recnum
""")
rows_ctprod = cur.fetchall()

print(f"\nTotal de registros: {len(rows_ctprod)}")

print("\n--- Amostra (10 primeiros) ---")
for r in rows_ctprod[:10]:
    print(dict(r))

# Qualidade
sem_recnum_cp = sum(1 for r in rows_ctprod if not r['recnum'])
sem_contrato_cp = sum(1 for r in rows_ctprod if not r['contrato'])
sem_produto_cp = sum(1 for r in rows_ctprod if not r['produto'])
sem_valor_cp = sum(1 for r in rows_ctprod if not r['valor'] or r['valor'] == Decimal('0'))
sem_valunit_cp = sum(1 for r in rows_ctprod if not r['valorunitario'] or r['valorunitario'] == Decimal('0'))
sem_desc_cp = sum(1 for r in rows_ctprod if r['produto_descricao'] == r['produto'])  # fallback

print(f"\n--- Qualidade dos campos ---")
print(f"  sem recnum:          {sem_recnum_cp}")
print(f"  sem contrato:        {sem_contrato_cp}")
print(f"  sem produto:         {sem_produto_cp}")
print(f"  valor = 0 ou null:   {sem_valor_cp}")
print(f"  valorunitario=0/null:{sem_valunit_cp}")
print(f"  sem descrição (usa código como fallback): {sem_desc_cp}")

# Distribuição de valorunitario
cur.execute("""
    SELECT
        COUNT(*) AS total,
        MIN(valorunitario) AS min_val,
        MAX(valorunitario) AS max_val,
        AVG(valorunitario) AS avg_val,
        SUM(valor) AS soma_valor
    FROM ctprod
    WHERE valorunitario IS NOT NULL AND valorunitario > 0
""")
print("\n--- Estatísticas de valorunitario (apenas > 0) ---")
print(dict(cur.fetchone()))

# Quais contratos do ctprod existem nos contracts do CRM?
# (simulado — listamos os contratos únicos)
contratos_ctprod = sorted(set(str(r['contrato']) for r in rows_ctprod if r['contrato']))
print(f"\n--- {len(contratos_ctprod)} contratos únicos no ctprod ---")
print(f"  Range: {contratos_ctprod[0]} até {contratos_ctprod[-1]}")
print(f"  Amostra: {contratos_ctprod[:10]}")


# ══════════════════════════════════════════════════════════════════════
# 3. BI_FATURAMENTO (docrec)
# ══════════════════════════════════════════════════════════════════════
print(SEP)
print("3. BI_FATURAMENTO — o que seria enviado (docrec)")
print(SEP)

cur.execute("""
    SELECT
        CONVERT(VARCHAR(20), d.numfatura)    AS numfatura,
        CONVERT(VARCHAR(10), d.numsequencia) AS numsequencia,
        ISNULL(CONVERT(VARCHAR(20), d.contrato), '') AS contrato,
        CONVERT(VARCHAR(20), d.codigocliente) AS codigocliente,
        ISNULL(CONVERT(VARCHAR(200), d.cliente), '') AS cliente,
        CONVERT(VARCHAR(30), d.valoremissao) AS valoremissao,
        CONVERT(VARCHAR(10), d.dataemissao, 120) AS dataemissao,
        CONVERT(VARCHAR(10), d.datavencto,  120) AS datavencto,
        ISNULL(CONVERT(VARCHAR(1), d.liquidado), ' ') AS liquidado,
        ISNULL(CONVERT(VARCHAR(100), d.tipodocumento), '') AS tipodocumento,
        ISNULL(CONVERT(VARCHAR(20), c.representante), '') AS representante,
        ISNULL(CONVERT(VARCHAR(200), c.representante_nome), '') AS representante_nome
    FROM docrec d
    LEFT JOIN contract c ON c.codigo = d.contrato
    ORDER BY d.numfatura
""")
rows_fat = cur.fetchall()

print(f"\nTotal de registros: {len(rows_fat)}")

print("\n--- Amostra (5 mais recentes) ---")
for r in rows_fat[-5:]:
    print(dict(r))

# Qualidade
sem_numfatura = sum(1 for r in rows_fat if not r['numfatura'])
sem_contrato_f = sum(1 for r in rows_fat if not r['contrato'])
sem_valor_f = sum(1 for r in rows_fat if not r['valoremissao'])
sem_dataemissao = sum(1 for r in rows_fat if not r['dataemissao'])
sem_representante = sum(1 for r in rows_fat if not r['representante_nome'])
liquidados = sum(1 for r in rows_fat if str(r['liquidado']).strip() == 'S')
em_aberto  = sum(1 for r in rows_fat if str(r['liquidado']).strip() != 'S')

print(f"\n--- Qualidade dos campos ---")
print(f"  sem numfatura:       {sem_numfatura}")
print(f"  sem contrato:        {sem_contrato_f}")
print(f"  sem valoremissao:    {sem_valor_f}")
print(f"  sem dataemissao:     {sem_dataemissao}")
print(f"  sem representante:   {sem_representante}")
print(f"\n  Liquidados (S):      {liquidados}")
print(f"  Em aberto:           {em_aberto}")

# Valor total por status
cur.execute("""
    SELECT
        CASE WHEN LTRIM(RTRIM(ISNULL(liquidado, ''))) = 'S' THEN 'Liquidado'
             ELSE 'Em aberto' END AS status,
        COUNT(*) AS qtd,
        SUM(valoremissao) AS valor_total
    FROM docrec
    GROUP BY CASE WHEN LTRIM(RTRIM(ISNULL(liquidado, ''))) = 'S' THEN 'Liquidado'
                  ELSE 'Em aberto' END
""")
print("\n--- Totais financeiros ---")
for r in cur.fetchall():
    print(f"  {r['status']}: {r['qtd']} registros, R$ {float(r['valor_total'] or 0):,.2f}")

# Representantes únicos
cur.execute("""
    SELECT DISTINCT c.representante_nome, COUNT(*) AS qtd
    FROM docrec d
    LEFT JOIN contract c ON c.codigo = d.contrato
    WHERE c.representante_nome IS NOT NULL AND c.representante_nome != ''
    GROUP BY c.representante_nome
    ORDER BY qtd DESC
""")
print("\n--- Representantes (faturamento por vendedor) ---")
for r in cur.fetchall():
    print(f"  {r['representante_nome']}: {r['qtd']} notas")

conn.close()
print(f"\n{'═'*70}")
print("✓ Validação concluída — nenhum dado foi escrito no CRM.")
