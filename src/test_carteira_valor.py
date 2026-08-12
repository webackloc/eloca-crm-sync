import pymssql, os
conn = pymssql.connect(
    server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
    port=1433, user="weback",
    password=os.environ["BI_PASSWORD"],
    database="biweback", timeout=60, charset="UTF-8"
)
cur = conn.cursor(as_dict=True)

print("=== Contrato 51 — quantos setores em ctprod? ===")
cur.execute("""
    SELECT setor, COUNT(*) AS linhas,
           SUM(CONVERT(DECIMAL(18,2), valorunitario)) AS valor_setor
    FROM ctprod WHERE contrato = '51'
    GROUP BY setor ORDER BY valor_setor DESC
""")
for r in cur.fetchall(): print(dict(r))

print("\n=== Contrato 51 — equipamentos reais em campo (ctmequip) ===")
cur.execute("""
    WITH last_move AS (
        SELECT CONVERT(VARCHAR(20), equipamento) AS equipamento,
               CONVERT(VARCHAR(20), contrato) AS contrato,
               CONVERT(VARCHAR(1), envret) AS envret,
               ROW_NUMBER() OVER (PARTITION BY equipamento ORDER BY data DESC, seq DESC) AS rn
        FROM ctmequip
    )
    SELECT COUNT(*) AS qtd
    FROM last_move lm
    JOIN equip e ON CONVERT(VARCHAR(20), e.codigo) = lm.equipamento
    WHERE lm.rn=1 AND lm.contrato='51' AND lm.envret='E'
      AND ISNULL(CONVERT(VARCHAR(50), e.situacao),'') NOT LIKE '%INATIV%'
""")
print(dict(cur.fetchone()))

print("\n=== Contrato 51 — valor usando setor vazio (principal) ===")
cur.execute("""
    WITH last_move AS (
        SELECT CONVERT(VARCHAR(20), equipamento) AS equipamento,
               CONVERT(VARCHAR(20), contrato) AS contrato,
               CONVERT(VARCHAR(1), envret) AS envret,
               ROW_NUMBER() OVER (PARTITION BY equipamento ORDER BY data DESC, seq DESC) AS rn
        FROM ctmequip
    ),
    preco AS (
        SELECT contrato, produto, MIN(CONVERT(DECIMAL(18,2), valorunitario)) AS valorunitario
        FROM ctprod
        WHERE contrato = '51'
        GROUP BY contrato, produto
    )
    SELECT COUNT(lm.equipamento) AS qtd, SUM(ISNULL(p.valorunitario,0)) AS valor
    FROM last_move lm
    JOIN equip e ON CONVERT(VARCHAR(20), e.codigo) = lm.equipamento
    LEFT JOIN preco p ON p.contrato = lm.contrato AND p.produto = e.codigoproduto
    WHERE lm.rn=1 AND lm.contrato='51' AND lm.envret='E'
      AND ISNULL(CONVERT(VARCHAR(50), e.situacao),'') NOT LIKE '%INATIV%'
""")
print(dict(cur.fetchone()))
conn.close()
