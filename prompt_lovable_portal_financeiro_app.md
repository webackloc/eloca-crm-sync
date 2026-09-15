# Prompt para o Portal Financeiro (Lovable) — Atualização com novos dados do BI

## Contexto

O portal financeiro já existe e já consome dados do nosso BI (banco SQL Server da ELOCA) sincronizados para o Supabase a cada 15 minutos via integração própria. Novos campos e tabelas foram adicionados ao Supabase — agora temos dados muito mais ricos para melhorar o DRE, a visão de inadimplência e o controle de pagamentos.

Este prompt descreve **o que mudou** e **como usar** cada dado novo.

---

## O que foi adicionado ao Supabase

### 3 tabelas novas

#### `bi_baixas_receber` — Recebimentos efetivos (o dinheiro que entrou de fato)
Esta tabela registra **quando e quanto foi realmente recebido** de cada fatura. Liga a `bi_faturamento` pelos campos `numfatura` + `numsequencia`.

| Campo | O que representa |
|---|---|
| `recnum` | PK |
| `numfatura` + `numsequencia` | Liga à fatura em `bi_faturamento` |
| `valorpago` | Valor efetivamente recebido (R$) |
| `valordesconto` | Desconto concedido ao cliente |
| `valorabatimento` | Abatimento |
| `valorjuros` | Juros cobrados por atraso |
| `valormulta` | Multa cobrada por atraso |
| `datacredito` | **Data real de entrada no caixa** ← usar esta para DRE de caixa |
| `datapagamento` | Data do pagamento pelo cliente |
| `databaixa` | Data da baixa no sistema |
| `tipobaixa` | Como foi recebido: "DEPOSITO EM CONTA", "PGTO EM BOLETO" etc. |
| `banco` / `agencia` / `contacorrente` | Conta que recebeu |

#### `bi_baixas_pagar` — Pagamentos efetivos (o dinheiro que saiu de fato)
Esta tabela registra **quando e quanto foi realmente pago** de cada título. Liga a `bi_contas_pagar` pelos campos `numfatura` + `numsequencia`.

| Campo | O que representa |
|---|---|
| `recnum` | PK |
| `numfatura` + `numsequencia` | Liga ao título em `bi_contas_pagar` |
| `valorpago` | Valor efetivamente pago (R$) |
| `valordesconto` | Desconto obtido do fornecedor |
| `valorabatimento` | Abatimento |
| `valorjuros` | Juros pagos por atraso |
| `valormulta` | Multa paga por atraso |
| `datapagamento` | **Data real de saída do caixa** ← usar esta para DRE de caixa |
| `databaixa` | Data da baixa no sistema |
| `tipobaixa` | Como foi pago: "PGTO DE BOLETO", "PGTO EM CHEQUE" etc. |
| `banco` / `agencia` / `contacorrente` | Conta que pagou |
| `fornecedor` | Nome do fornecedor |

#### `bi_tipo_receita` — Classificação de cada fatura por tipo de receita
Liga a `bi_faturamento` e diz o **que gerou aquela receita**.

| Campo | O que representa |
|---|---|
| `recnum` | PK |
| `numfatura` + `numsequencia` | Liga à fatura |
| `tiporeceita` | Descrição: "LOCAÇÃO DE EQUIPAMENTOS", "SERVIÇOS", etc. |
| `percentual` | % da fatura neste tipo (pode ser 100% ou dividida) |

---

### Campos novos em tabelas existentes

#### `bi_faturamento` (contas a receber — docrec)
| Campo novo | O que representa |
|---|---|
| `dataprevpagto` | Previsão de pagamento acordada |
| `datavenctoutil` | Vencimento ajustado para dia útil |
| `tiporeceita_descricao` | Tipo de receita direto na fatura (ex: "LOCAÇÃO DE EQUIPAMENTOS") |
| `valorretido` | Total retido na fonte (IR + PIS + COFINS + CSLL) |
| `valissretido` | ISS retido especificamente |
| `status_doc` | Status adicional do documento |

#### `bi_contas_pagar` (docpag)
| Campo novo | O que representa |
|---|---|
| `datavenctoutil` | Vencimento ajustado para dia útil — usar para calendário de pagamentos |

#### `bi_ativos` (equipamentos)
| Campo novo | O que representa |
|---|---|
| `marca` | Marca do equipamento (ex: HP, Lenovo) |
| `modelo` | Modelo do equipamento |
| `valcompra` | Valor de aquisição (R$) — base para depreciação |
| `dataaquisicao` | Data de compra |

---

## Como usar estes dados no portal

### DRE de Caixa

O DRE de Caixa mostra o dinheiro que **efetivamente entrou e saiu**, não o que foi emitido ou vencido.

**Receitas do mês** = `bi_baixas_receber` agrupado por `datacredito` (mês/ano)
```
Receita bruta = SUM(valorpago)
(-) Descontos concedidos = SUM(valordesconto)
(+) Juros/multas recebidos = SUM(valorjuros + valormulta)
= Receita líquida recebida
```

**Despesas do mês** = `bi_baixas_pagar` agrupado por `datapagamento` (mês/ano)
```
Total pago = SUM(valorpago)
(-) Descontos obtidos = SUM(valordesconto)
(+) Juros/multas pagos = SUM(valorjuros + valormulta)
= Despesa líquida paga
```

**Resultado de caixa** = Receita líquida − Despesa líquida

> ⚠️ Não usar `dataemissao` nem `datavencto` para o DRE de Caixa — essas datas são de competência, não de caixa.

---

### Classificação de receitas (o que gerou cada R$)

Usar `bi_tipo_receita.tiporeceita` (ou `bi_faturamento.tiporeceita_descricao`) para quebrar a receita por categoria:
- LOCAÇÃO DE EQUIPAMENTOS
- SERVIÇOS
- outros tipos que existirem

Isso permite mostrar no DRE: "Receita de Locação: R$ X | Receita de Serviços: R$ Y"

---

### Classificação de despesas (o que foi pago e para quem)

Usar `bi_contas_pagar.centrocusto` e `bi_contas_pagar.historico` para agrupar despesas.
Join com `bi_baixas_pagar` para saber o que foi pago vs. o que ainda está em aberto.

---

### Pago vs. Em aberto

**Contas a receber:**
- **Recebido**: existe registro em `bi_baixas_receber` para aquela fatura → mostrar `datacredito` e `valorpago`
- **Em aberto no prazo**: `bi_faturamento.liquidado != 'S'` + `datavencto >= hoje` + sem baixa
- **Inadimplente**: `bi_faturamento.liquidado != 'S'` + `datavencto < hoje` + sem registro em `bi_baixas_receber`

**Contas a pagar:**
- **Pago**: existe registro em `bi_baixas_pagar` → mostrar `datapagamento` e `valorpago`
- **Em aberto no prazo**: `bi_contas_pagar.liquidado = 'N'` + `datavencto >= hoje` + sem baixa
- **Vencido e não pago**: `bi_contas_pagar.liquidado = 'N'` + `datavencto < hoje` + sem baixa

> Priorizar sempre a existência de baixa nas tabelas `bi_baixas_*` — é mais confiável que o campo `liquidado`, que tem lag de ~24h do BI.

---

### View pronta no Supabase: `vw_dre_caixa`

Já existe uma view no Supabase que consolida tudo:
```
vw_dre_caixa — colunas: mes (date), tipo ('receita'|'despesa'), valor_pago, desconto, juros, multa, qtd_titulos
```
Use-a como base para o gráfico e tabela do DRE.

Também existem:
- `vw_inadimplencia` — faturas vencidas sem recebimento
- `vw_pagar_aberto` — títulos a pagar em aberto nos próximos 90 dias

---

## Resumo do que atualizar no portal

1. **DRE de Caixa**: trocar a fonte para `bi_baixas_receber` (receitas) e `bi_baixas_pagar` (despesas), usando `datacredito` e `datapagamento` respectivamente. Pode usar `vw_dre_caixa` diretamente.

2. **Breakdown de receitas**: adicionar classificação por `tiporeceita` usando `bi_tipo_receita` ou `bi_faturamento.tiporeceita_descricao`.

3. **Breakdown de despesas**: usar `bi_contas_pagar.centrocusto` e `historico`, filtrando pelo join com `bi_baixas_pagar`.

4. **Status de pagamento**: atualizar lógica de pago/em aberto para priorizar existência de baixa em `bi_baixas_receber` / `bi_baixas_pagar` antes de olhar o campo `liquidado`.

5. **Detalhe de recebimento**: ao abrir uma fatura, mostrar os dados da baixa: `valorpago`, `valordesconto`, `valorjuros`, `datacredito`, `tipobaixa`.

6. **Detalhe de pagamento**: ao abrir um título CP, mostrar: `valorpago`, `valordesconto`, `datapagamento`, `tipobaixa`.

7. **Inadimplência**: usar `vw_inadimplencia` já pronta.

8. **Compromissos futuros CP**: usar `vw_pagar_aberto` já pronta.
