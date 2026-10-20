#!/usr/bin/env bash
# Run a command with .env loaded and its names mapped to the variables the app reads.
set -euo pipefail
cd "$(dirname "$0")/.."
# .env mixes notes with KEY=VALUE lines, so only the assignments are loaded (never executed).
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*)$ ]] || continue
  key="${BASH_REMATCH[2]}"
  val="${BASH_REMATCH[3]}"
  val="${val%"${val##*[![:space:]]}"}"
  if [[ "$val" =~ ^\"(.*)\"$ || "$val" =~ ^\'(.*)\'$ ]]; then
    val="${BASH_REMATCH[1]}"
  fi
  export "$key=$val"
done < ./.env
export AZURE_TENANT_ID="${Azure_tenant_ID:-}"
export AZURE_CLIENT_ID="${Azure_client_ID:-}"
export AZURE_CLIENT_SECRET="${Secret_value_Azure:-}"
export LLM_PROVIDER="${LLM_PROVIDER:-cortex}"
export CORTEX_USER="${CORTEX_USER:-mayank.upadhyaya@lilly.com}"
exec "$@"
