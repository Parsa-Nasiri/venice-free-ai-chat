// ultimate-venice-proxy.js — Cloudflare Worker: OpenAI-compatible Venice free-proxy
// with auto IP rotation. On each 429/403/5xx from Venice it retries; every retry is a
// fresh Worker invocation = a fresh Cloudflare edge egress IP (the "proxy change system").
// Browser-spoofing headers + per-request attestation keep the anonymous path open.

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const auth = req.headers.get("Authorization") || "";
    const WANT_KEY = env.VENICE_KEY || "sk-venice-free-proxy";
    if (auth !== "Bearer " + WANT_KEY && url.pathname.startsWith("/v1/chat/completions")) {
      return json(401, { error: "invalid api key" });
    }

    if (url.pathname === "/v1/models") {
      return json(200, {
        object: "list",
        data: [{ id: "deepseek-v4-1-flash-free", object: "model", owned_by: "venice" }],
      });
    }
    if (url.pathname === "/" || url.pathname === "/v1") {
      return json(200, {
        base_url: "https://outerface.venice.ai",
        models: { chat: [{ id: "deepseek-v4-1-flash-free", pricing: "free" }] },
        rate_limit: "per-IP daily; Cloudflare edge IPs auto-rotate via retry on 429/403",
        api_key: "Bearer " + WANT_KEY,
      });
    }

    if (req.method === "GET" && url.pathname.startsWith("/v1/chat/completions")) {
      return new Response(JSON.stringify({ error: "POST /v1/chat/completions" }), {
        status: 405, headers: { "content-type": "application/json", Allow: "POST" },
      });
    }

    if (req.method === "POST" && url.pathname === "/v1/chat/completions") {
      return handleChat(req, env);
    }
    return json(404, { error: "not found" });
  },
};

function json(code, obj, extra = {}) {
  const h = { "content-type": "application/json", "access-control-allow-origin": "*" };
  return new Response(JSON.stringify(obj), { status: code, headers: { ...h, ...extra } });
}

function browserHeaders(nonce) {
  return {
    "sec-ch-ua": '"Google Chrome";v="130", "Chromium";v="130", "Not?A_Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "User-Agent":
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    Origin: "https://venice.ai",
    Referer: "https://venice.ai/",
    "x-venice-version": "interface@20261023.172051+9e9fe40",
    "x-venice-middleface-version": "0.1.1161",
    "x-venice-client-attestation": nonce || "",
  };
}

// Mint a fresh anonymous attestation token (no auth needed).
async function attest() {
  const r = await fetch("https://outerface.venice.ai/api/app/user/client_attestation/mint", {
    method: "POST",
    headers: { ...browserHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ count: 1, env: { a: true } }),
  });
  if (!cr.ok) return null;
  const j = await attest.json();
  const t = j.tokens && j.tokens[0];
  return t && t.token ? t.token : null;
}

// Translate Venice SSE -> OpenAI streaming, ending cleanly so clients stop "Thinking".
function sseToOpenAI(veniceStream) {
  const { readable, writable } = new TransformStream();
  const enc = new TextEncoder();
  const w = writable.getWriter();
  (async () => {
    const reader = veniceStream.getReader();
    let buf = "";
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += new TextDecoder().decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const ev = buf.slice(0, nl);
          buf = buf.slice(nl + 1);
          if (ev.startsWith("event: response.output_text.delta")) {
            // next 'data:' line on the wire
          }
          if (ev.startsWith("data: ")) {
            const payload = ev.slice(6).trim();
            if (payload === "[DONE]") {
              await w.write(enc.encode("data: [DONE]\n\n"));
              continue;
            }
            try {
              const d = JSON.parse(payload);
              if (d.delta != null) {
                const chunk = {
                  id: "chatcmpl-venice",
                  object: "chat.completion.chunk",
                  created: Math.floor(Date.now() / 1000),
                  model: "deepseek-v4-1-flash-free",
                  choices: [{ index: 0, delta: { role: "assistant", content: d.delta }, finish_reason: null }],
                };
                await w.write(enc.encode("data: " + JSON.stringify(chunk) + "\n\n"));
              }
            } catch {}
          }
        }
      }
    } catch (e) {
      await w.write(enc.encode("data: [DONE]\n\n"));
    } finally {
      await w.write(enc.encode("data: [DONE]\n\n"));
      await w.close();
    }
  })();
  return readable;
}

async function handleChat(req, env) {
  let body;
  try {
    body = await req.json();
  } catch {
    return json(400, { error: "bad json" });
  }

  const messages = (body.messages || []).map((m) => {
    const role = m.role === "assistant" ? "assistant" : "user";
    const content = typeof m.content === "string" ? m.content : (m.content || "").toString();
    return { role, content };
  });
  if (!messages.length) return json(400, { error: "no messages" });

  const stream = body.stream !== false; // default stream
  const MAX_TRIES = 4; // each try = a new Cloudflare edge IP
  let attempt = 0;
  let lastStatus = 0;
  while (attempt < MAX_TRIES) {
    attempt++;
    const token = await attest();
    let headers = browserHeaders(token);
    headers["Content-Type"] = "application/json";
    let cr;
    try {
      cr = await fetch("https://outerface.venice.ai/api/inference/chat/agents/venice", {
        method: "POST",
        headers,
        body: JSON.stringify({ input: { messages } }),
      });
    } catch {
      // network glitch on this edge -> retry (new IP)
      lastStatus = 0;
      continue;
    }
    const rem = cr.headers.get("x-ratelimit-remaining");
    if (cr.status === 429 || cr.status === 403 || (cr.status >= 500 && cr.status < 600)) {
      // IP/quota-flagged on THIS edge -> retry = a different Cloudflare egress IP
      lastStatus = cr.status;
      continue;
    }
    if (!cr.ok) {
      return json(cr.status, { error: `venice: ${cr.status}`, rate_limit_remaining: rem });
    }
    if (!stream) {
      // non-streaming: buffer and parse the SSE.
      const txt = await cr.text();
      // crude: take last 'data:' line payload as the answer
      let out = "";
      for (const line of txt.split("\n")) {
        if (line.startsWith("data:") && line.trim() !== "data: [DONE]") {
          try {
            const d = JSON.parse(line.slice(5).trim());
            if (d.delta != null) out += d.delta;
          } catch {}
        }
      }
      return json(200, {
        id: "chatcmpt-venice",
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: "deepseek-v4-1-flash-free",
        choices: [{ index: 0, message: { role: "assistant", content: out }, finish_reason: "stop" }],
      });
    }
    // streaming: translate SSE -> OpenAI, end cleanly (EOF => client stops "Thinking")
    return new Response(sseToOpenAI(cr.body), {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        "connection": "close",
        "access-control-allow-origin": "*",
      },
    });
  }
  return json(lastStatus || 502, { error: "all edge IPs failed (rate limited / blocked)" });
}
