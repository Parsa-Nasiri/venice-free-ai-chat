#!/usr/bin/env bash
# Deploy the Ultimate Venice proxy to Cloudflare Workers.
# Needs: a Cloudflare API token with Account -> Workers Scripts: Edit on YOUR account.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TOKEN="${CF_API_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  echo "Open https://dash.cloudflare.com/profile/api-tokens to create a token with:"
  echo "  - Resource: Account   ->   Workers Scripts: Edit"
  echo "  - Resource: Account   ->   Account Settings: Read (optional, for account_id)"
  echo "Then: export CF_API_TOKEN=...  OR  run:  CF_API_TOKEN=... $0"
  exit 1
fi

# account_id (first 8-hex of your user id) — wrangler reads CF_ACCOUNT_ID or uses --account-id
: "${CF_ACCOUNT_ID:?set CF_ACCOUNT_ID (from https://dash.cloudflare.com -> your account URL)"
cp "$SCRIPT_DIR/config/wrangler.toml" "$SCRIPT_DIR/wrangler.toml"
export CF_API_TOKEN="$TOKEN"
echo "Deploying to Cloudflare (edge IPs auto-rotate on 429/403 via retry)..."
npx --yes wrangler deploy "$SCRIPT_DIR/worker.js" --name venice-free-ai-proxy --account-id "$CF_ACCOUNT_ID"
echo
echo "Live at: https://venice-free-ai-proxy.<subdomain>.workers.dev  (default account subdomain)"
echo "Point your client at: VENICE_BASE_URL=https://<that-url>/v1  VENICE_API_KEY=<the VENICE_KEY secret you set>"
