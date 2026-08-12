# Conhecimento Base — BI ELOCA + Integração CRM

Este documento consolida todo o conhecimento técnico construído na integração
ELOCA ERP ↔ CRM Lovable. Use como contexto inicial em novas conversas.

---

## 1. Infraestrutura

### BI SQL Server (AWS RDS)
```
Host:     og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com
Port:     1433
Database: biweback
User:     weback
Driver:   pymssql (requer freetds-dev no Linux)
```
> **Importante**: o BI só é acessível a partir do GitHub Actions (IP do runner).
> Acesso local e de outras IPs é bloqueado pelo firewall da AWS.
> Lag de atualização: ~24h (o ELOCA atualiza o BI diariamente).

### Supabase
```
Project URL: https://dxkbqxualiqdhvsudshr.supabase.co
```
> O projeto é gerenciado pelo Lovable. Acesso direto às tabelas via dashboard
> é bloqueado. Todas as escritas são feitas via funções SECURITY DEFINER (RPC).

### GitHub Actions
```
Repositório: webackloc/eloca-crm-sync
Workflow:    .github/workflows/sync.yml
Trigger:     Cloudflare Worker (a cada 15 min, seg-sex, 07h-19h BRT)
             + workflow_dispatch (manual)
```

### Cloudflare Worker
- Worker `webackeloca` dispara `workflow_dispatch` no GitHub a cada 15 min
- Crons: `0,15,30,45 10-21 * * 1-5` e `0 22 * * 1-5` (UTC)
- Variável de ambiente: `GITHUB_TOKEN` (scope: workflow)

---

## 2. Tabelas do BI SQL Server

### `contract` — Contratos
| Campo | Descrição |
|---|---|
| `codigo` | Código do contrato (PK) |
| `cliente` | Código do cliente |
| `situacao` | `3` = APROVADO (ativo), outros = inativo |
| `datavigini` | Início da vigência |
| `datavigfim` | Fim da vigência |
| `representante` | Código do representante comercial |
| `representante_nome` | Nome do representante |

**Query padrão (contratos ativos):**
```sql
SELECT c.codigo, c.cliente, c.situacao,
       CONVERT(VARCHAR(10), c.datavigini, 120) AS datavigini,
       CONVERT(VARCHAR(10), c.datavigfim, 120) AS datavigfim
FROM contract c
WHERE c.situacao = '3'
```

---

### `equip` — Equipamentos (catálogo completo)
| Campo | Descrição |
|---|---|
| `codigo` | Código do equipamento (PK, varchar) |
| `codigoproduto` | Código do produto/modelo |
| `produto` | Descrição do produto |
| `seriefabricante` | Número de série |
| `situacao` | `Indisponível` (alugado), `Disponível`, `Inativo` |
| `created_at` | Data de criação/atualização no BI |

> **Regra crítica**: equipamentos com `situacao LIKE '%INATIV%'` devem ser
> **excluídos de todos os cálculos**. Uma vez INATIVO, o equipamento não está
> em uso de forma alguma.

---

### `ctmequip` — Movimentações de equipamentos
| Campo | Descrição |
|---|---|
| `recnum` | Chave auto-incremental (usar para sync incremental) |
| `equipamento` | Código do equipamento (varchar) |
| `contrato` | Código do contrato |
| `envret` | `E` = Enviado ao cliente, `R` = Retornado |
| `data` | Data da movimentação |
| `seq` | Sequência (desempate quando mesma data) |
| `numos` | Número da OS relacionada |
| `setor` | Setor do cliente |

> **Bug corrigido (ORDER BY)**: A query de posição atual deve ordenar por
> `data DESC, seq DESC` globalmente — **nunca** por `contrato` primeiro.
> Ordenar por contrato fazia pegar o movimento do menor contrato, não o mais recente.

**Query correta para posição atual de cada equipamento:**
```sql
WITH last_move AS (
    SELECT
        CONVERT(VARCHAR(20), equipamento) AS equipamento,
        CONVERT(VARCHAR(20), contrato)    AS contrato,
        CONVERT(VARCHAR(1),  envret)      AS envret,
        CONVERT(VARCHAR(10), data, 120)   AS data_mov,
        ROW_NUMBER() OVER (
            PARTITION BY equipamento
            ORDER BY data DESC, seq DESC  -- NUNCA ordenar por contrato primeiro
        ) AS rn
    FROM ctmequip
)
SELECT * FROM last_move WHERE rn = 1
```

---

### `ctprod` — Produtos por contrato (valores de locação)
| Campo | Descrição |
|---|---|
| `recnum` | Chave auto-incremental |
| `contrato` | Código do contrato |
| `produto` | Código do produto |
| `setor` | Setor |
| `valor` | Valor total |
| `valorunitario` | **Valor unitário mensal de locação (R$)** — campo principal |

> **Como obter preço de um equipamento:**
> JOIN `ctprod` por `(contrato, produto)` onde `contrato` = contrato atual
> do equipamento e `produto` = `codigoproduto` do equipamento.

---

### `docrec` — Faturamento (notas fiscais)
| Campo | Descrição |
|---|---|
| `numfatura` | Número da fatura (PK) |
| `numsequencia` | Sequência |
| `contrato` | Código do contrato |
| `codigocliente` | Código do cliente |
| `cliente` | Nome do cliente |
| `valoremissao` | Valor da fatura (R$) |
| `dataemissao` | Data de emissão |
| `datavencto` | Data de vencimento |
| `liquidado` | `S` = pago, ` ` = em aberto |
| `tipodocumento` | Tipo do documento |

---

### `produtos` — Catálogo de produtos
| Campo | Descrição |
|---|---|
| `codigo` | Código do produto (PK) |
| `descricao` | Descrição |
| `grupo_descricao` | Tipo do equipamento (ex: NOTEBOOK) |
| `grupo2_descricao` | Subtipo do equipamento |

---

## 3. Regras de Negócio Críticas

### Filtro correto para equipamentos em carteira (alugados):
```python
# Python:
sit = str(r['situacao_equip'] or '').upper()
er  = str(r['envret'] or '').strip()
em_carteira = 'INDISPON' in sit and 'INATIV' not in sit and er == 'E'
```
```sql
-- SQL:
WHERE equip.situacao LIKE '%Indispon%'
  AND ctmequip.envret = 'E'
  AND equip.situacao NOT LIKE '%Inativ%'
```

### Inconsistência INDISPONÍVEL + RETORNO:
Equipamentos marcados como `INDISPONÍVEL` no `equip.situacao` mas com último
movimento = `R` (RETORNO) são **inconsistências do BI** — o sistema ainda não
atualizou a situação. Devem ser **excluídos** do cálculo de carteira.
Flag: `inconsistente = True` na tabela `bi_ativos`.

### Validação realizada (jul/2026):
- BI: 7.363 equipamentos / R$ 1.644.935,50
- ELOCA oficial: 7.365 equipamentos / R$ 1.645.942,11
- Diferença: -2 eq / -R$ 1.006 (-0,06%) ← dentro da margem de lag do BI

---

## 4. Tabelas no Supabase (criadas pela integração)

### `bi_ativos` — Catálogo completo de equipamentos
Fonte: `equip` + `produtos` + posição atual de `ctmequip`

| Coluna | Tipo | Descrição |
|---|---|---|
| `codigo` | text (PK) | Código do equipamento |
| `codigoproduto` | text | Código do produto |
| `produto_descricao` | text | Descrição do produto |
| `serial_fabricante` | text | Número de série |
| `situacao` | text | Situação do equipamento |
| `tipo_equipamento` | text | Grupo (ex: NOTEBOOK) |
| `subtipo_equipamento` | text | Subgrupo |
| `contrato_atual` | text | Contrato ativo atual |
| `ultimo_envret` | text | `E` ou `R` |
| `data_ultimo_mov` | text | Data do último movimento |
| `inconsistente` | boolean | INDISPONÍVEL + último mov=R |
| `synced_at` | timestamptz | Última sync |

**Sync**: full sync a cada ciclo (tabela pequena ~8.800 registros, detecta mudanças de situação).

---

### `bi_movimentacoes` — Histórico de movimentações
Fonte: `ctmequip`

Sync **incremental** por `recnum`. Só busca registros novos (recnum > último processado).
Estado salvo em `sync_state` com chave `'bi_movimentacoes'`.

---

### `bi_ctprod` — Produtos/valores por contrato
Fonte: `ctprod` + join `produtos`

Sync **incremental** por `recnum`. Estado em `sync_state` com chave `'bi_ctprod'`.

> **Para obter valor mensal de locação de um equipamento:**
> ```sql
> SELECT cp.valorunitario
> FROM bi_ativos a
> JOIN bi_ctprod cp ON cp.contrato = a.contrato_atual
>                  AND cp.produto  = a.codigoproduto
> WHERE a.codigo = '7382'
> ```

---

### `bi_faturamento` — Faturas emitidas
Fonte: `docrec`

Sync por **janela deslizante de 90 dias** (rebusca sempre para capturar
atualizações no campo `liquidado`).

---

### `carteira_contratos` — Contratos ativos
Fonte: `contract` onde `situacao = '3'`

Full sync a cada ciclo. Inclui limpeza automática de contratos que saíram.

---

### `ativos` — Dados complementares da API ELOCA
Fonte: API REST ELOCA (não do BI)

Contém campos que o BI não tem: endereço completo, marca, modelo,
situacao_os, os_aberta, valor_compra, valor_mercado, fornecedor.

> **Nota**: `listar_ativos()` da API ELOCA está **desativado** no ciclo atual
> pois `bi_ativos` cobre o essencial. Reativar em `scheduler.py` se precisar
> dos campos exclusivos (endereço, marca, modelo).

---

### `ordens_servico` — OS dos últimos 60 dias
Fonte: CGI ELOCA (não do BI)

OS não existe no BI — vem exclusivamente da API/CGI do ELOCA.

---

### `sync_state` — Controle de sync incremental
| Coluna | Descrição |
|---|---|
| `tabela` | Nome da tabela (`bi_movimentacoes`, `bi_ctprod`, `bi_faturamento`) |
| `ultimo_recnum` | Último recnum processado |
| `ultima_sync` | Timestamp da última sync |

Funções RPC: `get_sync_state(p_tabela)` e `update_sync_state(p_tabela, p_recnum)`.

---

## 5. Arquitetura do Sync

```
Cloudflare Worker (cron a cada 15 min)
    → GitHub Actions workflow_dispatch
        → run_once.py → scheduler.executar_sincronizacao()
            ├── BI SQL Server
            │   ├── fetch_carteira_contratos()     → carteira_contratos (full)
            │   ├── fetch_equipamentos_ativos()    → sync_ativos_contratos (full)
            │   ├── fetch_bi_movimentacoes(recnum) → bi_movimentacoes (incremental)
            │   ├── fetch_bi_ctprod(recnum)        → bi_ctprod (incremental)
            │   ├── fetch_bi_faturamento(90 dias)  → bi_faturamento (janela)
            │   └── fetch_bi_ativos()              → bi_ativos (full)
            └── ELOCA CGI/API
                ├── listar_os()                    → ordens_servico
                └── processar_fila_criacao_os()    → cria OS no ELOCA
```

**Tempo médio por ciclo (com sessão cacheada):** ~44 segundos

---

## 6. Acesso ao BI — Código de Conexão

```python
import pymssql

def get_bi_conn():
    return pymssql.connect(
        server="og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com",
        port=1433,
        user="weback",
        password=os.getenv("BI_PASSWORD"),  # via secret
        database="biweback",
        timeout=60,
        charset="UTF-8",
        appname="meu-projeto",
    )
```

**Dependências:**
```bash
# Sistema (Ubuntu/Debian):
sudo apt-get install -y freetds-dev freetds-bin

# Python:
pip install pymssql
```

---

## 7. Notas Importantes

1. **Códigos de equipamento são varchar**, não int. Alguns têm prefixo alfanumérico
   (ex: `ARK012`, `ALT18768`). Sempre usar `CONVERT(VARCHAR(20), codigo)` nos joins.

2. **Nunca confiar em `equip.situacao` sozinho** para determinar se equipamento
   está alugado — cruzar sempre com o último movimento de `ctmequip`.

3. **Valor de locação** = `ctprod.valorunitario`, não `equip` nem `ativos`.
   Join por `(contrato, codigoproduto)`.

4. **Equipamentos INATIVO** = desativados permanentemente. Excluir de 100% dos
   cálculos com `WHERE situacao NOT LIKE '%INATIV%'`.

5. **Acesso ao BI apenas do GitHub Actions** — para qualquer consulta ao BI,
   criar um workflow com `workflow_dispatch` e rodar via Actions.
