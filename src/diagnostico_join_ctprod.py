"""
diagnostico_join_ctprod.py — Testa se ctprod.produto = ctmequip.equipamento
para entender como fazer o join correto de valorunitario por equipamento.
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
SEP = "═" * 70

# 1. Colunas exatas da tabela ctprod
print(f"\n{SEP}")
print("1. TODAS AS COLUNAS DE ctprod (INFORMATION_SCHEMA)")
print(SEP)
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'ctprod'
    ORDER BY ORDINAL_POSITION
""")
for r in cur.fetchall():
    print(f"  {r['COLUMN_NAME']:<30} {r['DATA_TYPE']:<20} {r['CHARACTER_MAXIMUM_LENGTH'] or ''}")

# 2. Colunas de ctmequip também
print(f"\n{SEP}")
print("2. TODAS AS COLUNAS DE ctmequip (INFORMATION_SCHEMA)")
print(SEP)
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'ctmequip'
    ORDER BY ORDINAL_POSITION
""")
for r in cur.fetchall():
    print(f"  {r['COLUMN_NAME']:<30} {r['DATA_TYPE']:<20} {r['CHARACTER_MAXIMUM_LENGTH'] or ''}")

# 3. Para contrato 1: equipamentos vs produtos — overlap?
CONTRATO_TESTE = '1'
print(f"\n{SEP}")
print(f"3. CONTRATO {CONTRATO_TESTE} — equipamentos em ctmequip (últimos movimentos ativos)")
print(SEP)
cur.execute(f"""
    WITH last_move AS (
        SELECT equipamento, contrato, envret,
               ROW_NUMBER() OVER (PARTITION BY equipamento ORDER BY data DESC, seq DESC) AS rn
        FROM ctmequip WHERE contrato = '{CONTRATO_TESTE}'
    )
    SELECT CONVERT(VARCHAR(20), equipamento) AS equipamento
    FROM last_move
    WHERE rn = 1 AND envret = 'E'
""")
equips = [str(r['equipamento']) for r in cur.fetchall()]
print(f"  Equipamentos ({len(equips)}): {equips}")

print(f"\n{SEP}")
print(f"4. CONTRATO {CONTRATO_TESTE} — produtos em ctprod")
print(SEP)
cur.execute(f"""
    SELECT
        CONVERT(VARCHAR(20), produto) AS produto,
        CONVERT(VARCHAR(30), valorunitario) AS valorunitario,
        ISNULL(CONVERT(VARCHAR(500), setor), '') AS setor
    FROM ctprod WHERE contrato = '{CONTRATO_TESTE}'
    ORDER BY produto
""")
prods = cur.fetchall()
for r in prods:
    print(f"  produto={r['produto']:<12} valorunitario={r['valorunitario']:<12} setor={r['setor']}")

print(f"\n{SEP}")
print(f"5. OVERLAP: equipamentos que também existem como produto no ctprod (contrato {CONTRATO_TESTE})")
print(SEP)
prod_set = set(str(r['produto']) for r in prods)
overlap = [e for e in equips if e in prod_set]
nao_overlap = [e for e in equips if e not in prod_set]
print(f"  Com match em ctprod.produto: {overlap}")
print(f"  SEM match em ctprod.produto: {nao_overlap}")

# 4. Teste global: quantos equipamentos ativos têm match direto em ctprod
print(f"\n{SEP}")
print("6. TESTE GLOBAL — join ctmequip.equipamento = ctprod.produto (mesmo contrato)")
print(SEP)
cur.execute("""
    WITH last_move AS (
        SELECT equipamento, contrato, envret,
               ROW_NUMBER() OVER (PARTITION BY equipamento ORDER BY data DESC, seq DESC) AS rn
        FROM ctmequip
    ),
    ativos AS (
        SELECT CONVERT(VARCHAR(20), equipamento) AS equipamento,
               CONVERT(VARCHAR(20), contrato)    AS contrato
        FROM last_move
        WHERE rn = 1 AND envret = 'E'
    )
    SELECT
        COUNT(*) AS total_equip,
        SUM(CASE WHEN cp.produto IS NOT NULL THEN 1 ELSE 0 END) AS com_match,
        SUM(CASE WHEN cp.produto IS NULL     THEN 1 ELSE 0 END) AS sem_match
    FROM ativos a
    JOIN contract c ON c.codigo = a.contrato AND c.situacao = '3'
    LEFT JOIN ctprod cp
           ON CONVERT(VARCHAR(20), cp.contrato) = a.contrato
          AND CONVERT(VARCHAR(20), cp.produto)  = a.equipamento
""")
r = cur.fetchone()
total = r['total_equip']
com   = r['com_match']
sem   = r['sem_match']
print(f"  Total equipamentos ativos (contratos situacao=3): {total}")
print(f"  COM match ctprod.produto=equipamento:             {com}  ({100*com/total:.1f}%)")
print(f"  SEM match:                                        {sem}  ({100*sem/total:.1f}%)")

# 5. Amostra dos que têm match — confirma que valorunitario não está zerado
print(f"\n{SEP}")
print("7. AMOSTRA dos que TÊM match (10 primeiros) — valorunitario")
print(SEP)
cur.execute("""
    WITH last_move AS (
        SELECT equipamento, contrato, envret,
               ROW_NUMBER() OVER (PARTITION BY equipamento ORDER BY data DESC, seq DESC) AS rn
        FROM ctmequip
    ),
    ativos AS (
        SELECT CONVERT(VARCHAR(20), equipamento) AS equipamento,
               CONVERT(VARCHAR(20), contrato)    AS contrato
        FROM last_move
        WHERE rn = 1 AND envret = 'E'
    )
    SELECT TOP 10
        a.contrato,
        a.equipamento,
        CONVERT(VARCHAR(20), cp.produto) AS produto,
        CONVERT(VARCHAR(30), cp.valorunitario) AS valorunitario,
        ISNULL(CONVERT(VARCHAR(500), p.descricao), cp.produto) AS descricao
    FROM ativos a
    JOIN contract c ON c.codigo = a.contrato AND c.situacao = '3'
    JOIN ctprod cp
           ON CONVERT(VARCHAR(20), cp.contrato) = a.contrato
          AND CONVERT(VARCHAR(20), cp.produto)  = a.equipamento
    LEFT JOIN produtos p ON p.codigo = cp.produto
""")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  contrato={r['contrato']:<5} equip={r['equipamento']:<12} prod={r['produto']:<12} R${r['valorunitario']:<12} {r['descricao'][:40]}")
else:
    print("  (nenhum match encontrado)")

# 6. Amostra dos que NÃO têm match — entender o padrão
print(f"\n{SEP}")
print("8. AMOSTRA dos que NÃO TÊM match (10 primeiros)")
print(SEP)
cur.execute("""
    WITH last_move AS (
        SELECT equipamento, contrato, envret,
               ROW_NUMBER() OVER (PARTITION BY equipamento ORDER BY data DESC, seq DESC) AS rn
        FROM ctmequip
    ),
    ativos AS (
        SELECT CONVERT(VARCHAR(20), equipamento) AS equipamento,
               CONVERT(VARCHAR(20), contrato)    AS contrato
        FROM last_move
        WHERE rn = 1 AND envret = 'E'
    )
    SELECT TOP 10
        a.contrato,
        a.equipamento,
        (SELECT TOP 1 CONVERT(VARCHAR(20), cp2.produto) + '|R$' + CONVERT(VARCHAR(20), cp2.valorunitario)
         FROM ctprod cp2 WHERE CONVERT(VARCHAR(20), cp2.contrato) = a.contrato
         ORDER BY cp2.recnum) AS primeiro_prod_contrato
    FROM ativos a
    JOIN contract c ON c.codigo = a.contrato AND c.situacao = '3'
    LEFT JOIN ctprod cp
           ON CONVERT(VARCHAR(20), cp.contrato) = a.contrato
          AND CONVERT(VARCHAR(20), cp.produto)  = a.equipamento
    WHERE cp.produto IS NULL
""")
for r in cur.fetchall():
    print(f"  contrato={r['contrato']:<5} equip={r['equipamento']:<12}  primeiro_prod_no_contrato={r['primeiro_prod_contrato']}")

conn.close()
print(f"\n{'═'*70}")
print("✓ Diagnóstico concluído.")
