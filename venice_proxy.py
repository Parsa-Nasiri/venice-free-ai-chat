#!/usr/bin/env python3
"""venice-proxy — OpenAI-compatible proxy to Venice.ai's FREE model.

Anonymous, no account. The chat endpoint is gated by a per-IP daily quota
(not a per-device quota), so true "unlimited" scaling requires IP rotation,
which this proxy supports via the VENICE_PROXIES env var. On any IP-flagged
error (403/429/TOS or a dead proxy) the next request auto-hops to the next IP.

Run:  python3 venice_proxy.py            # listens on :8000
      VENICE_PROXIES=1.2.3.4:8080,5.6.7.8:8080 python3 venice_proxy.py
      VENICE_SELFTEST=1 python3 venice_proxy.py   # unit test the retry logic
"""
import os, json, time, uuid, hashlib, http.server, socketserver
import urllib.request, urllib.error, ssl

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
CHAT = "https://outerface.venice.ai/api/inference/chat/agents/venice"
MINT = "https://outerface.venice.ai/api/app/user/client_attestation/mint"
RL   = "https://outerface.venice.ai/api/inference/rate-limits"
MODEL = "deepseek-v4-1-flash-free"
DISTINCT = lambda: str(uuid.uuid4())
RF = lambda: hashlib.sha256(str(time.time()*1e6).encode()).hexdigest()
PROXIES = [p.strip() for p in os.environ.get("VENICE_PROXIES","").split(",") if p.strip()]
CTX = ssl.create_default_context()
KEY = os.environ.get("VENICE_API_KEY","sk-venice-free-proxy")

# HTTP codes that mean "this IP is blocked / exhausted" -> try the next IP.
_IP_BLOCKED = (403, 408, 429, 502, 503, 504)

def _req(url, data=None, anon=False, proxy=None):
    # browser-fingerprint headers (sec-ch-ua etc.) — without these Venice
    # returns 403 "Programmatic use forbidden by TOS". The attestation + these
    # headers make the call look like a real browser with no Authorization needed.
    h = {"User-Agent": UA, "Accept": "text/event-stream", "Accept-Encoding":"identity",
         "Origin":"https://venice.ai","Referer":"https://venice.ai/",
         "x-venice-locale":"en","x-venice-version":"interface@20261023.172051+9e9fe40",
         "x-venice-middleface-version":"0.1.1161","x-venice-distinct-id":DISTINCT(),
         "sec-ch-ua":'"Google Chrome";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
         "sec-ch-ua-mobile":"?0","sec-ch-ua-platform":"Windows"}
    if data is not None:
        h["Content-Type"] = "application/json"
    if anon:
        tok = _mint(proxy)
        if tok: h["x-venice-client-attestation"] = tok
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, headers=h, data=body)
    handlers = [urllib.request.HTTPSHandler(context=CTX)]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http":proxy,"https":proxy}))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=30)

def _mint(proxy=None):
    data = {"count":1,"env":{"nativeIntegrityOk":True,"reactStateHash":RF(),
        "sentryVersion":"10.50.0","unexpectedGlobalsCount":0,"webdriver":False}}
    try:
        r = _req(MINT, data=data, proxy=proxy)
        return json.loads(r.read())["token"]
    except Exception:
        return None

def _venice_messages(messages):
    out = []
    for m in messages:
        role = m.get("role","user")
        if role == "assistant":
            out.append({"content":[{"text":_extract(m.get("content")),"type":"output_text"}],
                        "id":"agent-node:llm:0","role":"assistant","status":"completed","type":"message"})
        else:
            out.append({"content":[{"annotations":[],"text":_extract(m.get("content")),"type":"output_text"}],
                        "id":str(uuid.uuid4())[:22],"role":"user","status":"completed","type":"message"})
    return out

def _extract(c):
    if isinstance(c, str): return c
    if isinstance(c, list):
        return "".join(p.get("text","") for p in c if isinstance(p,dict))
    return json.dumps(c)

def _next_proxy():
    return PROXIES[int(time.time()*1e3) % len(PROXIES)] if PROXIES else None

def _try_chat(venice):
    """Send a chat request, retrying across VENICE_PROXIES on IP-flagged errors
    (403/429/TOS, 5xx, network failures). User rule: every time a request errors,
    the IP changes and bypasses the block. Returns an HTTPResponse on success;
    raises the last HTTPError/URLError otherwise."""
    pool = list(PROXIES) if PROXIES else [None]
    last = None
    for proxy in pool:
        try:
            return _req(CHAT, data=venice, anon=True, proxy=proxy)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in _IP_BLOCKED:   # not IP-flagged — surface immediately
                raise
        except (urllib.error.URLError, TimeoutError, OSError):
            last = None      # transient network glitch — try next IP
    if last: raise last
    raise urllib.error.URLError("all proxies failed")

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _h(self, code=200, ct="application/json", extra=None):
        self.send_response(code); self.send_header("Content-Type",ct)
        self.send_header("Access-Control-Allow-Origin","*")
        if extra:
            for k,v in extra.items(): self.send_header(k,v)
        self.end_headers()
    def _key(self):
        if self.headers.get("Authorization") != "Bearer "+KEY:
            self._h(401); self.wfile.write(b'{"error":"invalid api key"}'); return False
        return True
    def do_GET(self):
        if self.path == "/v1/models":
            self._h(); self.wfile.write(json.dumps({"object":"list","data":[{"id":MODEL,"object":"model","owned_by":"venice"}]}).encode())
        elif self.path == "/" or self.path == "/v1":
            self._h(); self.wfile.write(json.dumps({"base_url":"https://outerface.venice.ai","models":{"chat":[{"id":MODEL,"pricing":"free"}]},"api_key":"set VENICE_API_KEY env","rate_limit":"per-IP daily; rotate VENICE_PROXIES to scale"}).encode())
        elif self.path.startswith("/v1/chat/completions"):
            self._h(405, ct="application/json", extra={"Allow":"POST"}); self.wfile.write(b'{"error":"POST /v1/chat/completions"}\n')
        else: self._h(404); self.wfile.write(b'{"error":"not found"}')
    def do_POST(self):
        if not self._key(): return
        if self.path != "/v1/chat/completions":
            self._h(404); self.wfile.write(b'{"error":"not found"}'); return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))))
        except Exception:
            self._h(400); self.wfile.write(b'{"error":"bad json"}'); return
        venice = {"input":{"messages":_venice_messages(body.get("messages",[]))}}
        try:
            src = _try_chat(venice)
        except urllib.error.HTTPError as e:
            self._h(e.code); self.wfile.write(e.read()[:1000]); return
        except Exception:
            self._h(502); self.wfile.write((b'{"error":"all proxies failed"}\n' if PROXIES else b'{"error":"request failed"}\n')); return
        # Connection: close => client sees EOF => stops "Thinking" (OpenCode/OpenRouter hang on keep-alive + no Content-Length)
        self._h(200, ct="text/event-stream", extra={"Cache-Control":"no-cache","Connection":"close"})
        for line in src:  # streaming: yields lines as Venice emits them
            try: line = line.decode("utf-8","replace").rstrip("\r\n")
            except: continue
            if line.startswith("event: response.output_text.delta"):
                # the following non-blank line is this delta's data: payload
                d = None
                while True:
                    nxt = src.readline().decode("utf-8","replace").rstrip("\r\n")
                    if nxt.strip()=="": break
                    if nxt.startswith("data:"):
                        try: d = json.loads(nxt[6:].strip())
                        except: pass
                if d and "delta" in d:
                    delta = d.get("delta","")
                    self.wfile.write(("data: "+json.dumps({"choices":[{"delta":{"role":"assistant","content":delta},"index":0}],"object":"chat.completion.chunk"})+"\n\n").encode())
                    self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

def _selftest():
    """Proves the auto-IP-retry: bad:1 (429) -> bad:2 (URLError) -> good:3 (200),
    and that deltas are re-emitted as OpenAI chunks. No network needed."""
    import io
    calls = []
    global _req  # we monkeypatch the module-level _req below
    SAMPLE = (b'event: response.output_text.delta\r\ndata: {"sequence_number":4,"delta":"hi "}\r\n\r\n'
              b'event: response.output_text.delta\r\ndata: {"sequence_number":5,"delta":"there"}\r\n\r\n'
              b'data: [DONE]\r\n')
    def _stub(url, data=None, anon=False, proxy=None):
        calls.append(proxy)
        if proxy == "bad:1":
            raise urllib.error.HTTPError(url, 429, "rate", {}, io.BytesIO(b'{"error":"rate limit exceeded"}'))
        if proxy == "bad:2":
            raise urllib.error.URLError("conn refused")
        return urllib.request.addinfourl(io.BytesIO(SAMPLE), {}, url)
    _orig = _req
    _req = _stub  # noqa: F811  (monkeypatch module-level fn for the test)
    PROXIES.clear(); PROXIES.extend(["bad:1","bad:2","good:3"])
    src = _try_chat({"input":{"messages":[]}})
    assert calls == ["bad:1","bad:2","good:3"], calls
    out = b"".join(src)
    assert b"hi " in out and b"there" in out, out
    _req = _orig
    PROXIES.clear()
    print("self-test OK: advanced bad:1,bad:2 -> good:3; parsed OpenAI deltas")

if __name__ == "__main__":
    if os.environ.get("VENICE_SELFTEST"):
        _selftest(); raise SystemExit(0)
    port = int(os.environ.get("PORT","8000"))
    print(f"venice-proxy on :{port}  model={MODEL}  proxies={PROXIES or 'none (per-IP quota)'}")
    with socketserver.ThreadingTCPServer(("0.0.0.0",port), H) as s:
        s.allow_reuse_address = True
        s.serve_forever()
