"""
analisar_bi_completo.py — Análise das tabelas ctmequip, ctprod e docrec do BI
Objetivo: entender estrutura e volume antes de sincronizar com o CRM

Uso:
  BI_PASSWORD="..." python3 src/analisar_bi_completo.py
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
# 1. CTMEQUIP — Movimentações de equipamentos
# ══════════════════════════════════════════════════════════════════════
print(SEP)
print("1. CTMEQUIP — Movimentações de equipamentos")
print(SEP)

print("\n--- Contagem total ---")
cur.execute("SELECT COUNT(*) AS total FROM ctmequip")
print(cur.fetchone())

print("\n--- Valores de envret (E=entrega, R=retirada) ---")
cur.execute("SELECT envret, COUNT(*) AS qtd FROM ctmequip GROUP BY envret ORDER BY qtd DESC")
for r in cur.fetchall(): print(dict(r))

print("\n--- Range de datas ---")
cur.execute("""
    SELECT
        CONVERT(VARCHAR(10), MIN(data), 120) AS data_min,
        CONVERT(VARCHAR(10), MAX(data), 120) AS data_max,
        CONVERT(VARCHAR(10), MIN(created_at), 120) AS criado_min,
        CONVERT(VARCHAR(10), MAX(created_at), 120) AS criado_max
    FROM ctmequip
""")
print(dict(cur.fetchone()))

print("\n--- Amostra (10 últimas movimentações) ---")
cur.execute("""
    SELECT TOP 10
        equipamento, contrato, envret,
        CONVERT(VARCHAR(10), data, 120) AS data,
        setor, numos,
        CONVERT(VARCHAR(10), created_at, 120) AS created_at
    FROM ctmequip
    ORDER BY created_at DESC, seq DESC
""")
for r in cur.fetchall(): print(dict(r))

print("\n--- Equipamentos únicos vs contratos ---")
cur.execute("""
    SELECT
        COUNT(DISTINCT equipamento) AS equipamentos_unicos,
        COUNT(DISTINCT contrato) AS contratos_unicos,
        COUNT(*) AS total_movimentos
    FROM ctmequip
""")
print(dict(cur.fetchone()))

print("\n--- Setores distintos ---")
cur.execute("SELECT DISTINCT setor FROM ctmequip WHERE setor IS NOT NULL AND setor != '' ORDER BY setor")
setores = [r['setor'] for r in cur.fetchall()]
print(f"Setores ({len(setores)}): {setores}")


# ══════════════════════════════════════════════════════════════════════
# 2. CTPROD — Produtos por contrato
# ══════════════════════════════════════════════════════════════════════
print(SEP)
print("2. CTPROD — Produtos por contrato")
print(SEP)

print("\n--- Contagem total ---")
cur.execute("SELECT COUNT(*) AS total FROM ctprod")
print(cur.fetchone())

print("\n--- Amostra (10 registros) ---")
cur.execute("""
    SELECT TOP 10
        contrato, produto, setor, valor, valorvenda, valorunitario,
        quantidade, custo,
        CONVERT(VARCHAR(10), dataini, 120) AS dataini,
        CONVERT(VARCHAR(10), datafim, 120) AS datafim
    FROM ctprod
    ORDER BY contrato, setor
""")
for r in cur.fetchall(): print(dict(r))

print("\n--- Contratos únicos e produtos únicos ---")
cur.execute("""
    SELECT
        COUNT(DISTINCT contrato) AS contratos_unicos,
        COUNT(DISTINCT produto) AS produtos_unicos,
        COUNT(*) AS total_itens,
        SUM(valorunitario * quantidade) AS valor_total
    FROM ctprod
""")
print(dict(cur.fetchone()))

print("\n--- Valores nulos em campos críticos ---")
cur.execute("""
    SELECT
        SUM(CASE WHEN valorunitario IS NULL OR valorunitario = 0 THEN 1 ELSE 0 END) AS sem_valor_unit,
        SUM(CASE WHEN quantidade IS NULL OR quantidade = 0 THEN 1 ELSE 0 END) AS sem_qtd,
        SUM(CASE WHEN produto IS NULL OR produto = '' THEN 1 ELSE 0 END) AS sem_produto,
        SUM(CASE WHEN dataini IS NULL THEN 1 ELSE 0 END) AS sem_dataini,
        SUM(CASE WHEN datafim IS NULL THEN 1 ELSE 0 END) AS sem_datafim
    FROM ctprod
""")
print(dict(cur.fetchone()))

print("\n--- Join com contract e produtos ---")
cur.execute("""
    SELECT TOP 10
        cp.contrato,
        c.cliente AS cod_cliente,
        p.descricao AS produto_descricao,
        cp.valorunitario,
        cp.quantidade,
        cp.setor,
        CONVERT(VARCHAR(10), cp.dataini, 120) AS dataini,
        CONVERT(VARCHAR(10), cp.datafim, 120) AS datafim
    FROM ctprod cp
    LEFT JOIN contract c ON c.codigo = cp.contrato
    LEFT JOIN produtos p ON p.codigo = cp.produto
    ORDER BY cp.contrato
""")
for r in cur.fetchall(): print(dict(r))


# ══════════════════════════════════════════════════════════════════════
# 3. DOCREC — Faturamento / Recebimentos
# ══════════════════════════════════════════════════════════════════════
print(SEP)
print("3. DOCREC — Faturamento e Recebimentos")
print(SEP)

print("\n--- Contagem total ---")
cur.execute("SELECT COUNT(*) AS total FROM docrec")
print(cur.fetchone())

print("\n--- Por status de liquidação ---")
cur.execute("""
    SELECT
        liquidado,
        COUNT(*) AS qtd,
        SUM(valoremissao) AS valor_total
    FROM docrec
    GROUP BY liquidado
""")
for r in cur.fetchall(): print(dict(r))

print("\n--- Range de datas ---")
cur.execute("""
    SELECT
        CONVERT(VARCHAR(10), MIN(dataemissao), 120) AS emissao_min,
        CONVERT(VARCHAR(10), MAX(dataemissao), 120) AS emissao_max,
        CONVERT(VARCHAR(10), MIN(datavencto),  120) AS vencto_min,
        CONVERT(VARCHAR(10), MAX(datavencto),  120) AS vencto_max
    FROM docrec
""")
print(dict(cur.fetchone()))

print("\n--- Sequências de parcela distintas ---")
cur.execute("""
    SELECT MIN(numsequencia) AS seq_min, MAX(numsequencia) AS seq_max,
           COUNT(DISTINCT numsequencia) AS seq_distintas
    FROM docrec WHERE numsequencia IS NOT NULL
""")
print(dict(cur.fetchone()))

print("\n--- Parcelas 1 (primeiras — 10% comissão) ---")
cur.execute("""
    SELECT COUNT(*) AS total_primeiras_parcelas,
           SUM(valoremissao) AS valor_total
    FROM docrec WHERE numsequencia = 1
""")
print(dict(cur.fetchone()))

print("\n--- Tipos de documento ---")
cur.execute("""
    SELECT tipodocumento, COUNT(*) AS qtd
    FROM docrec GROUP BY tipodocumento ORDER BY qtd DESC
""")
for r in cur.fetchall(): print(dict(r))

print("\n--- Amostra com join completo ---")
cur.execute("""
    SELECT TOP 5
        d.numfatura, d.numsequencia, d.contrato,
        d.codigocliente, d.cliente,
        d.valoremissao,
        CONVERT(VARCHAR(10), d.dataemissao, 120) AS dataemissao,
        CONVERT(VARCHAR(10), d.datavencto, 120) AS datavencto,
        d.liquidado, d.tipodocumento,
        c.representante_nome AS vendedor
    FROM docrec d
    LEFT JOIN contract c ON c.codigo = d.contrato
    WHERE d.contrato IS NOT NULL AND d.contrato != ''
    ORDER BY d.dataemissao DESC
""")
for r in cur.fetchall(): print(dict(r))

conn.close()
print(f"\n{'═'*70}")
print("✓ Análise concluída.")
