# venice-free-ai-chat

## Ultimate: one command

```bash
curl -fsSL https://raw.githubusercontent.com/Parsa-Nasiri/venice-free-ai-chat/main/install.sh | bash
#   -> installs the `venice` CLI globally (PATH)
venice deploy        # checks Cloudflare: Worker live -> use it;
                      # no CF_API_TOKEN -> opens the token page in your browser
                      #   (grant: Account -> Workers Scripts: Edit)
                      # token set       -> deploys to the edge with wrangler
venice chat "hi"      # routes through your edge Worker (auto-IP-rotation);
                      # or falls back to local venice_proxy.py if no Worker.
venice doctor         # full status of worker + local proxy + config
```

`venice` is the single entrypoint. It auto-detects a live Cloudflare Worker; if none exists
and you have no `CF_API_TOKEN`, it opens `https://dash.cloudflare.com/profile/api-tokens`
in your browser (you create the token, then re-run `CF_API_TOKEN=... CF_ACCOUNT_ID=... venice deploy`).


Free, **account-less** access to Venice.ai's uncensored model
(`DeepSeek V4.1 Flash` / `deepseek-v4-1-flash-free`) as an **OpenAI-compatible API**,
plus a browser-driven fallback.

- **No login. No credit card. No API key of your own.** Anonymous access is
  possible — you only need a free *client attestation* token, which the proxy
  mints on demand.
- One-liner install.
- Exposes `/v1/chat/completions` (OpenAI streaming) and `/v1/models`.
- **On each IP-flagged error (403/429/TOS, or a dead proxy) the proxy
  auto-advances to the next IP** — so "every time I get an error the IP changes
  and bypasses that" is literally how it behaves.

## The three things you need

| # | What | Why |
|---|------|-----|
| 1 | **`python3`** (stdlib only, no venv) | runs `venice_proxy.py` |
| 2 | **Proxies with fresh IPs** *(optional, to scale)* | Venice caps free access **per-IP per day**. Each fresh IP = a fresh daily quota. Set `VENICE_PROXIES=1.2.3.4:8080,5.6.7.8:8080`. |
| 3 | **A browser (fallback only)** | If Venice returns `403 "Programmatic use … forbidden by TOS"` to your IP, fall back to the browser-driven `venice_chat.py`, which drives a real Chrome session (never blocked). |

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Parsa-Nasiri/venice-free-ai-chat/main/setup.sh | bash
```

## Run the OpenAI-compatible proxy

```bash
export VENICE_API_KEY="sk-venice-free-proxy"        # required for requests
export VENICE_PROXIES="1.2.3.4:8080,5.6.7.8:8080"   # optional — rotate IPs to scale
python3 venice_proxy.py                             # listens on :8000
```

Set `PORT` to change the listen port. Set `VENICE_SELFTEST=1` to run the built-in
no-network unit test (proves a 429 → dead-proxy → fresh-IP success).

## Use it (9router / OpenRouter compatible)

- **Base URL:** `http://localhost:8000/v1`
- **API key:** `sk-venice-free-proxy`
- **Model:** `deepseek-v4-1-flash-free`

```bash
curl -H "Authorization: Bearer sk-venice-free-proxy"      -H "Content-Type: application/json"      -d '{"model":"deepseek-v1-v4-1-flash-free","messages":[{"role":"user","content":"hi"}],"stream":true}'      http://localhost:8000/v1/chat/completions
```

Streams OpenAI-format chunks ending in `data: [DONE]`.

## How it works (reverse-engineered from live traffic)

- **Base URL:** `https://outerface.venice.ai`
- **Chat API:** `POST /api/inference/chat/agents/venice` → `text/event-stream`
  (SSE). Deltas arrive as `event: response.output_text.delta` → `data: {"delta":...}`,
  ending in `data: [DONE]`.
- **Auth:** none needed. Anonymous works. Mint a free attestation at
  `POST /api/app/user/client_attestation/mint` (`{"count":1,"env":{…}}`) — no
  `Authorization` header required.
- **Model:** `deepseek-v4-1-flash-free` ("DeepSeek V4.1 Flash Uncensored").
- The proxy stamps real-browser fingerprint headers (`sec-ch-ua`, …) on every
  call so Venice doesn't treat it as a headless client, mints a fresh attestation
  per request, and rewrites Venice's SSE → OpenAI streaming chunks.

## Scaling / "unlimited"

Venice's free tier is capped **per source IP per day** — shared across classic +
agent chat; a fresh device fingerprint or account does *not* reset it (only a new
IP or the daily reset does). So "unlimited" = **IP rotation** via `VENICE_PROXIES`.
Without proxies, you're limited to one IP's daily quota (readable live at
`GET /api/inference/rate-limits`).

> ⚠️ Venice actively returns `403 "Programmatic use ... forbidden by TOS … will
> result in suspension"` to some HTTP clients. Browser-spoof headers reduce this
> but Venice can escalate any IP that looks programmatic. The browser-driven
> fallback (`venice_chat.py`) is immune because it *is* a real browser.

## Browser-driven fallback

```bash
python3 venice_chat.py "Say the single word: banana"
```

## License

MIT.
