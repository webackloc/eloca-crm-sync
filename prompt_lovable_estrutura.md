# Contexto da integração ELOCA ↔ CRM — novas tabelas BI

Atualizamos a estrutura de dados do CRM. Além das tabelas já existentes (`ativos`, `ordens_servico`, `carteira_contratos`), foram criadas 4 novas tabelas sincronizadas diretamente do banco BI da ELOCA (SQL Server). Todos os preços, movimentações e faturamento devem vir dessas novas tabelas.

---

## Tabelas criadas (prefixo `bi_`)

### `bi_ativos`
Catálogo completo de equipamentos (fonte: tabela `equip` do BI).

| Coluna | Tipo | Descrição |
|---|---|---|
| `codigo` | text (PK) | Código do equipamento |
| `codigoproduto` | text | Código do produto/modelo |
| `produto_descricao` | text | Descrição do produto |
| `serial_fabricante` | text | Número de série |
| `situacao` | text | `Indisponível` (alugado), `Disponível`, `Inativo` |
| `tipo_equipamento` | text | Grupo do produto (ex: NOTEBOOK) |
| `subtipo_equipamento` | text | Subgrupo do produto |
| `contrato_atual` | text | Código do contrato ativo |
| `ultimo_envret` | text | `E` = enviado ao cliente, `R` = retornado |
| `data_ultimo_mov` | text | Data do último movimento |
| `inconsistente` | boolean | True quando situação e último movimento divergem |
| `synced_at` | timestamptz | Última atualização pela sync |

**Filtro correto para equipamentos em campo (alugados):**
```sql
situacao ILIKE '%Indispon%'
AND ultimo_envret = 'E'
AND situacao NOT ILIKE '%Inativ%'
```

---

### `bi_ctprod`
Produtos por contrato com **valor unitário de locação** (fonte: tabela `ctprod` do BI).
Este é o lugar correto para buscar preços.

| Coluna | Tipo | Descrição |
|---|---|---|
| `recnum` | text (PK) | Chave única |
| `contrato` | text | Código do contrato |
| `produto` | text | Código do produto |
| `produto_descricao` | text | Descrição do produto |
| `setor` | text | Setor do contrato |
| `valor` | text | Valor total do item no contrato |
| `valorunitario` | text | **Valor unitário mensal de locação (R$)** |
| `synced_at` | timestamptz | Última atualização pela sync |

**Como obter o preço de um equipamento:**
```sql
SELECT cp.valorunitario
FROM bi_ativos a
JOIN bi_ctprod cp
  ON cp.contrato = a.contrato_atual
 AND cp.produto  = a.codigoproduto
WHERE a.codigo = '7382'
```

---

### `bi_movimentacoes`
Histórico completo de movimentações de equipamentos (fonte: tabela `ctmequip` do BI).

| Coluna | Tipo | Descrição |
|---|---|---|
| `recnum` | text (PK) | Chave única (auto-incremental no BI) |
| `equipamento` | text | Código do equipamento |
| `contrato` | text | Código do contrato |
| `envret` | text | `E` = envio ao cliente, `R` = retorno |
| `data` | text | Data da movimentação (YYYY-MM-DD) |
| `setor` | text | Setor |
| `numos` | text | Número da OS relacionada |
| `seq` | text | Sequência (desempate de data) |
| `synced_at` | timestamptz | Última atualização pela sync |

---

### `bi_faturamento`
Faturas emitidas — últimos 90 dias (fonte: tabela `docrec` do BI).

| Coluna | Tipo | Descrição |
|---|---|---|
| `numfatura` | text (PK) | Número da fatura |
| `numsequencia` | text | Sequência |
| `contrato` | text | Código do contrato |
| `codigocliente` | text | Código do cliente |
| `cliente` | text | Nome do cliente |
| `valoremissao` | text | Valor da fatura (R$) |
| `dataemissao` | text | Data de emissão (YYYY-MM-DD) |
| `datavencto` | text | Data de vencimento |
| `liquidado` | text | `S` = pago, ` ` = em aberto |
| `tipodocumento` | text | Tipo do documento |
| `representante` | text | Código do representante |
| `representante_nome` | text | Nome do representante |
| `synced_at` | timestamptz | Última atualização pela sync |

---

## Relação entre tabelas

```
bi_ativos.contrato_atual  ──→  carteira_contratos.id
bi_ativos.codigoproduto   ──→  bi_ctprod.produto   (+ contrato_atual = bi_ctprod.contrato)
bi_ativos.codigo          ──→  bi_movimentacoes.equipamento
bi_ativos.codigo          ──→  ativos.codigo        (ativos = dados complementares da API ELOCA)
carteira_contratos.id     ──→  bi_faturamento.contrato
carteira_contratos.id     ──→  bi_ctprod.contrato
```

---

## Regras de negócio importantes

1. **Equipamentos INATIVO** devem ser excluídos de todos os cálculos. Filtrar com `situacao NOT ILIKE '%Inativ%'`.

2. **Equipamentos alugados** = `situacao ILIKE '%Indispon%' AND ultimo_envret = 'E'`. Ignorar registros onde `ultimo_envret = 'R'` mesmo com situação Indisponível (inconsistência temporária do BI).

3. **Preço do equipamento** sempre vem de `bi_ctprod.valorunitario` — join por `(contrato, produto)`. Nunca usar `valor_compra` ou `valor_mercado` de `ativos` para faturamento.

4. **Valor da carteira de um cliente** = soma de `bi_ctprod.valorunitario` para todos os equipamentos ativos (ENVIADO) do cliente, excluindo INATIVO.

5. **Sync incremental**: a tabela `sync_state` guarda o último `recnum` processado por tabela. `bi_movimentacoes` e `bi_ctprod` recebem apenas registros novos a cada ciclo. `bi_faturamento` sempre rebusca os últimos 90 dias. `bi_ativos` e `carteira_contratos` fazem full sync (tabelas menores).

---

## Tabelas existentes (mantidas)

- **`ativos`**: dados da API ELOCA — campos complementares como `endereco`, `setor`, `situacao_os`, `os_aberta`, `valor_compra`, `valor_mercado`. Use para dados de localização e OS.
- **`ordens_servico`**: OS abertas/fechadas nos últimos 60 dias, direto da API ELOCA.
- **`carteira_contratos`**: contratos ativos (situacao=APROVADO) com cliente e vigência.
