#!/bin/bash
# setup_github_secrets.sh
# Cadastra todos os secrets do GitHub Actions em um comando só.
#
# Pré-requisito: gh CLI instalado e autenticado
#   brew install gh
#   gh auth login
#
# Uso:
#   chmod +x setup_github_secrets.sh
#   ./setup_github_secrets.sh SEU_USUARIO/eloca-crm-sync

REPO="${1:-}"

if [ -z "$REPO" ]; then
  echo "Uso: ./setup_github_secrets.sh USUARIO/REPO"
  echo "Exemplo: ./setup_github_secrets.sh leonardo/eloca-crm-sync"
  exit 1
fi

echo "Cadastrando secrets em: $REPO"

gh secret set SUPABASE_URL         --repo "$REPO" --body "https://qipzqthzogmrhiktqbbp.supabase.co"
gh secret set SUPABASE_SERVICE_KEY --repo "$REPO" --body "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFpcHpxdGh6b2dtcmhpa3RxYmJwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MTAxNTAzNSwiZXhwIjoyMDk2NTkxMDM1fQ.G6yTtu_zhmJmpPNJrDvL42U357K1EVnBHnvXO4J_0-I"

gh secret set BI_HOST     --repo "$REPO" --body "og-bi.crwm94zs8mf9.sa-east-1.rds.amazonaws.com"
gh secret set BI_PORT     --repo "$REPO" --body "1433"
gh secret set BI_DATABASE --repo "$REPO" --body "biweback"
gh secret set BI_USER     --repo "$REPO" --body "weback"
gh secret set BI_PASSWORD --repo "$REPO" --body "0%,t,v,]~t6V^BH6L>CM"

gh secret set ELOCA_EMPRESA       --repo "$REPO" --body "WEBACK"
gh secret set ELOCA_USER          --repo "$REPO" --body "LEONARDO"
gh secret set ELOCA_PASSWORD      --repo "$REPO" --body "Ferrari32@"
gh secret set TWOCAPTCHA_API_KEY  --repo "$REPO" --body "debfe499f8108ddebb618f66b1343a06"

echo ""
echo "✓ Secrets cadastrados com sucesso!"
echo "Acesse: https://github.com/$REPO/settings/secrets/actions"
