# Prompt para o Lovable — Novos campos e tabelas do BI

Cole este prompt inteiro no Lovable.

---

Preciso que você faça duas coisas:

## 1. Migrations no Supabase

### Tabelas novas

```sql
-- bi_baixas_pagar: pagamentos efetivos de contas a pagar (fonte: dbaicp do BI)
CREATE TABLE IF NOT EXISTS bi_baixas_pagar (
    recnum              text PRIMARY KEY,
    numfatura           text,
    numsequencia        text,
    codigofornecedor    text,
    fornecedor          text,
    banco               text,
    agencia             text,
    contacorrente       text,
    valorpago           numeric(14,2),
    valordesconto       numeric(14,2),
    valorabatimento     numeric(14,2),
    valorjuros          numeric(14,2),
    valormulta          numeric(14,2),
    datapagamento       date,
    databaixa           date,
    tipobaixa           text,
    observacao          text,
    synced_at           timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bi_baixas_pagar_numfatura ON bi_baixas_pagar (numfatura, numsequencia);
CREATE INDEX IF NOT EXISTS idx_bi_baixas_pagar_datapagamento ON bi_baixas_pagar (datapagamento);

-- bi_baixas_receber: recebimentos efetivos de contas a receber (fonte: dbaicr do BI)
CREATE TABLE IF NOT EXISTS bi_baixas_receber (
    recnum              text PRIMARY KEY,
    numfatura           text,
    numsequencia        text,
    banco               text,
    agencia             text,
    contacorrente       text,
    valorpago           numeric(14,2),
    valordesconto       numeric(14,2),
    valorabatimento     numeric(14,2),
    valorjuros          numeric(14,2),
    valormulta          numeric(14,2),
    datapagamento       date,
    databaixa           date,
    datacredito         date,
    tipobaixa           text,
    observacao          text,
    synced_at           timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bi_baixas_receber_numfatura ON bi_baixas_receber (numfatura, numsequencia);
CREATE INDEX IF NOT EXISTS idx_bi_baixas_receber_datacredito ON bi_baixas_receber (datacredito);

-- bi_tipo_receita: classificação de receita por fatura (fonte: rreceitr do BI)
CREATE TABLE IF NOT EXISTS bi_tipo_receita (
    recnum              text PRIMARY KEY,
    numfatura           text,
    numsequencia        text,
    codigotiporeceita   text,
    tiporeceita         text,
    percentual          numeric(16,8),
    synced_at           timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bi_tipo_receita_numfatura ON bi_tipo_receita (numfatura, numsequencia);
```

### Colunas novas em tabelas existentes

```sql
-- bi_faturamento: campos novos vindos do docrec
ALTER TABLE bi_faturamento
    ADD COLUMN IF NOT EXISTS dataprevpagto          date,
    ADD COLUMN IF NOT EXISTS datavenctoutil         date,
    ADD COLUMN IF NOT EXISTS tiporeceita_descricao  text,
    ADD COLUMN IF NOT EXISTS valorretido            numeric(14,2),
    ADD COLUMN IF NOT EXISTS valissretido           numeric(16,2),
    ADD COLUMN IF NOT EXISTS status_doc             text;

-- bi_contas_pagar: campo novo vindo do docpag
ALTER TABLE bi_contas_pagar
    ADD COLUMN IF NOT EXISTS datavenctoutil         date;

-- bi_ativos: campos novos vindos do equip
ALTER TABLE bi_ativos
    ADD COLUMN IF NOT EXISTS marca                  text,
    ADD COLUMN IF NOT EXISTS modelo                 text,
    ADD COLUMN IF NOT EXISTS valcompra              numeric(16,4),
    ADD COLUMN IF NOT EXISTS dataaquisicao          date;
```

### RLS nas novas tabelas

Habilite RLS nas 3 novas tabelas com política de leitura para `authenticated`, igual ao padrão das demais tabelas `bi_*`.

---

## 2. Atualizar a Edge Function bi-ingest

A Edge Function `bi-ingest` recebe POST com `?table=nome_da_tabela` e faz upsert. Adicione as 3 novas tabelas ao mapa de tabelas permitidas, com upsert por `recnum`:

- `bi_baixas_pagar` — PK: `recnum`
- `bi_baixas_receber` — PK: `recnum`
- `bi_tipo_receita` — PK: `recnum`
