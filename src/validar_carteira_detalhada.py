"""
validar_carteira_detalhada.py — Validação detalhada da carteira por contrato

Mostra para cada contrato ativo:
  - Dados do contrato (cliente, vigência, situação)
  - Equipamentos ativos (último movimento = 'E' no ctmequip)
  - Produtos e valores (ctprod)
  - Cruzamento: equip ativos vs itens do ctprod
  - Faturamento recente (docrec)

NÃO escreve nada. Apenas lê e valida.

Uso:
  BI_PASSWORD="..." python3 src/validar_carteira_detalhada.py
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


# ══════════════════════════════════════════════════════════════════════
# 1. RESUMO GERAL DA CARTEIRA ATIVA
# ══════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("RESUMO GERAL — Carteira ativa (situacao=3)")
print(SEP)

cur.execute("""
    SELECT
        COUNT(DISTINCT c.codigo) AS total_contratos,
        COUNT(DISTINCT c.cliente) AS total_clientes
    FROM contract c
    WHERE c.situacao = '3'
""")
print("\nContratos e clientes ativos:")
print(dict(cur.fetchone()))

# Equipamentos com último movimento = E em contrato ativo
cur.execute("""
    WITH last_move AS (
        SELECT
            equipamento, contrato, envret,
            ROW_NUMBER() OVER (PARTITION BY equipamento ORDER BY data DESC, seq DESC) AS rn
        FROM ctmequip
    )
    SELECT
        COUNT(*) AS equip_ativos,
        COUNT(DISTINCT lm.contrato) AS contratos_com_equip
    FROM last_move lm
    JOIN contract c ON c.codigo = lm.contrato
    WHERE lm.rn = 1 AND lm.envret = 'E' AND c.situacao = '3'
""")
print("\nEquipamentos ativos (último mov = E, contrato ativo):")
print(dict(cur.fetchone()))

# Valor total da carteira (ctprod)
cur.execute("""
    SELECT
        COUNT(*) AS linhas_ctprod,
        SUM(CONVERT(FLOAT, valor)) AS valor_total_carteira,
        AVG(CONVERT(FLOAT, valorunitario)) AS ticket_medio_unitario
    FROM ctprod cp
    JOIN contract c ON c.codigo = cp.contrato
    WHERE c.situacao = '3'
      AND cp.valorunitario IS NOT NULL AND CONVERT(FLOAT, cp.valorunitario) > 0
""")
print("\nValores da carteira ativa (ctprod):")
r = cur.fetchone()
print(f"  Linhas ctprod:        {r['linhas_ctprod']}")
print(f"  Valor total:          R$ {float(r['valor_total_carteira'] or 0):,.2f}")
print(f"  Ticket médio unitário: R$ {float(r['ticket_medio_unitario'] or 0):,.2f}")


# ══════════════════════════════════════════════════════════════════════
# 2. DETALHAMENTO POR CONTRATO
# ══════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("DETALHAMENTO POR CONTRATO (todos os ativos, situacao=3)")
print(SEP)

# Busca todos os contratos ativos com dados agregados
cur.execute("""
    WITH last_move AS (
        SELECT
            equipamento, contrato, envret,
            ROW_NUMBER() OVER (PARTITION BY equipamento ORDER BY data DESC, seq DESC) AS rn
        FROM ctmequip
    ),
    equip_ativos AS (
        SELECT lm.contrato, COUNT(*) AS qtd_equip
        FROM last_move lm
        JOIN contract c ON c.codigo = lm.contrato
        WHERE lm.rn = 1 AND lm.envret = 'E' AND c.situacao = '3'
        GROUP BY lm.contrato
    ),
    prod_contrato AS (
        SELECT
            cp.contrato,
            COUNT(*) AS qtd_produtos,
            SUM(CONVERT(FLOAT, cp.valor)) AS valor_total,
            MIN(CONVERT(FLOAT, cp.valorunitario)) AS valor_min,
            MAX(CONVERT(FLOAT, cp.valorunitario)) AS valor_max
        FROM ctprod cp
        WHERE cp.valorunitario IS NOT NULL
        GROUP BY cp.contrato
    ),
    fat_recente AS (
        SELECT
            contrato,
            MAX(CONVERT(VARCHAR(10), dataemissao, 120)) AS ultima_fatura,
            SUM(CONVERT(FLOAT, valoremissao)) AS total_faturado
        FROM docrec
        WHERE LTRIM(RTRIM(ISNULL(contrato, ''))) != ''
          AND dataemissao >= '2026-01-01'
        GROUP BY contrato
    )
    SELECT
        c.codigo AS contrato,
        c.cliente AS cod_cliente,
        -- nome do cliente via docrec
        (SELECT TOP 1 d.cliente FROM docrec d WHERE d.codigocliente = c.cliente ORDER BY d.recnum DESC) AS cliente_nome,
        CONVERT(VARCHAR(10), c.datavigini, 120) AS data_inicio,
        CONVERT(VARCHAR(10), c.datavigfim, 120) AS data_fim,
        ISNULL(ea.qtd_equip, 0) AS equip_ativos,
        ISNULL(pc.qtd_produtos, 0) AS qtd_produtos,
        ISNULL(pc.valor_total, 0) AS valor_total,
        ISNULL(pc.valor_min, 0) AS valor_unit_min,
        ISNULL(pc.valor_max, 0) AS valor_unit_max,
        ISNULL(fr.ultima_fatura, '') AS ultima_fatura_2026,
        ISNULL(fr.total_faturado, 0) AS total_faturado_2026
    FROM contract c
    LEFT JOIN equip_ativos ea ON ea.contrato = c.codigo
    LEFT JOIN prod_contrato pc ON pc.contrato = c.codigo
    LEFT JOIN fat_recente fr ON fr.contrato = c.codigo
    WHERE c.situacao = '3'
    ORDER BY CONVERT(INT, c.codigo)
""")
contratos = cur.fetchall()

print(f"\nTotal de contratos ativos: {len(contratos)}\n")
print(f"{'CONT':>5} | {'CLIENTE':<40} | {'VIGÊNCIA':<23} | {'EQUIP':>5} | {'PROD':>4} | {'VALOR TOTAL':>12} | {'UNIT MIN':>9} | {'UNIT MAX':>9} | {'ÚLT FAT':>10} | {'FAT 2026':>12}")
print("-" * 170)

sem_equip = []
sem_produtos = []
divergentes = []  # equip_ativos != qtd_produtos

for r in contratos:
    contrato   = r['contrato'] or ''
    cliente    = (r['cliente_nome'] or '')[:38]
    inicio     = r['data_inicio'] or ''
    fim        = r['data_fim'] or ''
    vigencia   = f"{inicio} → {fim}"
    equip      = int(r['equip_ativos'] or 0)
    produtos   = int(r['qtd_produtos'] or 0)
    val_total  = float(r['valor_total'] or 0)
    val_min    = float(r['valor_unit_min'] or 0)
    val_max    = float(r['valor_unit_max'] or 0)
    ult_fat    = r['ultima_fatura_2026'] or ''
    fat_2026   = float(r['total_faturado_2026'] or 0)

    flag = ''
    if equip == 0:
        sem_equip.append(contrato)
        flag += ' ⚠️ SEM_EQUIP'
    if produtos == 0:
        sem_produtos.append(contrato)
        flag += ' ⚠️ SEM_PROD'
    if equip > 0 and produtos > 0 and abs(equip - produtos) > 5:
        divergentes.append((contrato, equip, produtos))

    print(f"{contrato:>5} | {cliente:<40} | {vigencia:<23} | {equip:>5} | {produtos:>4} | {val_total:>12,.2f} | {val_min:>9,.2f} | {val_max:>9,.2f} | {ult_fat:>10} | {fat_2026:>12,.2f}{flag}")


# ══════════════════════════════════════════════════════════════════════
# 3. ALERTAS DE INCONSISTÊNCIA
# ══════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("ALERTAS DE INCONSISTÊNCIA")
print(SEP)

print(f"\n⚠️  Contratos SEM equipamentos ativos ({len(sem_equip)}): {sem_equip}")
print(f"⚠️  Contratos SEM produtos em ctprod ({len(sem_produtos)}): {sem_produtos}")

if divergentes:
    print(f"\n⚠️  Contratos com diferença > 5 entre equip ativos e linhas ctprod ({len(divergentes)}):")
    for contrato, equip, prod in divergentes:
        print(f"    Contrato {contrato}: {equip} equip ativos vs {prod} linhas ctprod")
else:
    print("\n✅  Sem divergências grandes entre equip ativos e linhas ctprod.")


# ══════════════════════════════════════════════════════════════════════
# 4. TOP 10 CONTRATOS POR VALOR
# ══════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("TOP 10 CONTRATOS POR VALOR TOTAL (ctprod)")
print(SEP)

cur.execute("""
    SELECT TOP 10
        cp.contrato,
        (SELECT TOP 1 d.cliente FROM docrec d WHERE d.codigocliente = c.cliente ORDER BY d.recnum DESC) AS cliente_nome,
        COUNT(*) AS qtd_linhas,
        SUM(CONVERT(FLOAT, cp.valor)) AS valor_total,
        AVG(CONVERT(FLOAT, cp.valorunitario)) AS avg_unitario
    FROM ctprod cp
    JOIN contract c ON c.codigo = cp.contrato
    WHERE c.situacao = '3'
      AND cp.valorunitario IS NOT NULL AND CONVERT(FLOAT, cp.valorunitario) > 0
    GROUP BY cp.contrato, c.cliente
    ORDER BY valor_total DESC
""")
print(f"\n{'CONT':>5} | {'CLIENTE':<45} | {'LINHAS':>6} | {'VALOR TOTAL':>13} | {'UNIT MÉDIO':>11}")
print("-" * 95)
for r in cur.fetchall():
    print(f"{r['contrato']:>5} | {(r['cliente_nome'] or '')[:43]:<45} | {r['qtd_linhas']:>6} | R$ {float(r['valor_total'] or 0):>11,.2f} | R$ {float(r['avg_unitario'] or 0):>9,.2f}")


# ══════════════════════════════════════════════════════════════════════
# 5. PRODUTOS MAIS COMUNS NA CARTEIRA
# ══════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PRODUTOS MAIS COMUNS (TOP 15 por frequência em contratos ativos)")
print(SEP)

cur.execute("""
    SELECT TOP 15
        cp.produto,
        ISNULL(p.descricao, cp.produto) AS descricao,
        COUNT(DISTINCT cp.contrato) AS contratos,
        COUNT(*) AS linhas,
        MIN(CONVERT(FLOAT, cp.valorunitario)) AS val_min,
        MAX(CONVERT(FLOAT, cp.valorunitario)) AS val_max,
        AVG(CONVERT(FLOAT, cp.valorunitario)) AS val_avg
    FROM ctprod cp
    LEFT JOIN produtos p ON p.codigo = cp.produto
    JOIN contract c ON c.codigo = cp.contrato
    WHERE c.situacao = '3'
      AND cp.valorunitario IS NOT NULL AND CONVERT(FLOAT, cp.valorunitario) > 0
    GROUP BY cp.produto, p.descricao
    ORDER BY contratos DESC, linhas DESC
""")
print(f"\n{'COD':<8} | {'DESCRIÇÃO':<55} | {'CONTRATOS':>9} | {'LINHAS':>6} | {'MIN':>8} | {'MAX':>8} | {'MÉD':>8}")
print("-" * 115)
for r in cur.fetchall():
    print(f"{r['produto']:<8} | {(r['descricao'] or '')[:53]:<55} | {r['contratos']:>9} | {r['linhas']:>6} | {float(r['val_min'] or 0):>8,.2f} | {float(r['val_max'] or 0):>8,.2f} | {float(r['val_avg'] or 0):>8,.2f}")


# ══════════════════════════════════════════════════════════════════════
# 6. FATURAMENTO 2026 — RESUMO POR CONTRATO
# ══════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("FATURAMENTO 2026 — Contratos com maior volume")
print(SEP)

cur.execute("""
    SELECT TOP 15
        d.contrato,
        (SELECT TOP 1 d2.cliente FROM docrec d2 WHERE d2.contrato = d.contrato ORDER BY d2.recnum DESC) AS cliente_nome,
        COUNT(*) AS qtd_notas,
        SUM(CONVERT(FLOAT, d.valoremissao)) AS total_emitido,
        SUM(CASE WHEN LTRIM(RTRIM(ISNULL(d.liquidado,''))) = 'S'
                 THEN CONVERT(FLOAT, d.valoremissao) ELSE 0 END) AS total_liquidado,
        SUM(CASE WHEN LTRIM(RTRIM(ISNULL(d.liquidado,''))) != 'S'
                 THEN CONVERT(FLOAT, d.valoremissao) ELSE 0 END) AS total_aberto,
        MAX(CONVERT(VARCHAR(10), d.dataemissao, 120)) AS ultima_emissao
    FROM docrec d
    WHERE LTRIM(RTRIM(ISNULL(d.contrato, ''))) != ''
      AND d.dataemissao >= '2026-01-01'
    GROUP BY d.contrato
    ORDER BY total_emitido DESC
""")
print(f"\n{'CONT':>5} | {'CLIENTE':<40} | {'NOTAS':>5} | {'EMITIDO':>12} | {'LIQUIDADO':>12} | {'EM ABERTO':>10} | {'ÚLT EMISSÃO':>12}")
print("-" * 115)
for r in cur.fetchall():
    print(f"{(r['contrato'] or ''):>5} | {(r['cliente_nome'] or '')[:38]:<40} | {r['qtd_notas']:>5} | R$ {float(r['total_emitido'] or 0):>10,.2f} | R$ {float(r['total_liquidado'] or 0):>10,.2f} | R$ {float(r['total_aberto'] or 0):>8,.2f} | {r['ultima_emissao']:>12}")

conn.close()
print(f"\n{'═'*70}")
print("✓ Validação detalhada concluída — nenhum dado foi escrito no CRM.")
