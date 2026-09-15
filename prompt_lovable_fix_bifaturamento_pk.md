# Prompt para o Lovable — Corrigir PK da tabela bi_faturamento

Cole este prompt inteiro no Lovable (projeto de integração CRM/BI).

---

Preciso de uma correção urgente na tabela `bi_faturamento` e na Edge Function `bi-ingest`.

## Contexto do problema

A tabela `bi_faturamento` usa atualmente `numfatura` como chave primária. Porém, o BI possui faturas com o **mesmo numfatura e numsequencia diferente** (ex: uma fatura parcelada tem uma linha por sequência). Quando a Edge Function tenta fazer upsert de um lote com duas linhas do mesmo numfatura, o PostgreSQL lança:

```
ON CONFLICT DO UPDATE command cannot affect row a second time
```

Isso impediu o carregamento histórico de ~1000 registros no backfill.

## O que precisa ser feito

### 1. Migration no Supabase

Mudar a PK de `bi_faturamento` de `numfatura` (single) para composta `(numfatura, numsequencia)`:

```sql
-- Remove a PK atual
ALTER TABLE bi_faturamento DROP CONSTRAINT IF EXISTS bi_faturamento_pkey;

-- Garante que numsequencia existe (campo já deve estar presente, mas por segurança)
ALTER TABLE bi_faturamento ADD COLUMN IF NOT EXISTS numsequencia text;

-- Adiciona a nova PK composta
ALTER TABLE bi_faturamento ADD PRIMARY KEY (numfatura, numsequencia);
```

> ⚠️ Antes de rodar, verifique se existem linhas com numsequencia NULL — se houver, faça:
> `UPDATE bi_faturamento SET numsequencia = '0' WHERE numsequencia IS NULL;`
> e só depois adicione a PK.

### 2. Atualizar a Edge Function bi-ingest

No handler da tabela `bi_faturamento` dentro da Edge Function `bi-ingest`, mudar o `onConflict` de:

```ts
// ANTES
.upsert(rows, { onConflict: 'numfatura' })
```

Para:

```ts
// DEPOIS
.upsert(rows, { onConflict: 'numfatura,numsequencia' })
```

Isso garante que cada combinação (numfatura + numsequencia) é tratada como registro único, sem conflito dentro do mesmo lote.

---

Após essa correção, vou re-rodar o workflow de backfill histórico para carregar os ~1000 registros que falharam.
