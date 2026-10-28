#!/usr/bin/env python3
"""venice — single entrypoint for the Ultimate Venice free-proxy.

One command does the right thing:
  - `venice deploy`  -> if a Cloudflare Worker is already up, use it.
                        if no CF_API_TOKEN, open the token page in your browser
                          (you log in + create the token, then re-run).
                        otherwise deploy to Cloudflare with wrangler.
  - `venice chat "hi"` / `venice models` / `venice info` / `venice health`
                       -> route through the deployed Worker (edge, auto-IP-rotation)
                          when configured & reachable; else auto-start the local
                          venice_proxy.py fallback.
  - `venice doctor`    -> print full status of every moving part.

Config (auto-created): ~/.venice/config.json   {worker_url, api_key, account_id}
Env overrides (take priority): VENICE_WORKER_URL, VENICE_API_KEY, CF_API_TOKEN,
CF_ACCOUNT_ID, VENICE_BASE_URL, VENICE_API_KEY (local proxy key).
"""
import base64, json, os, shutil, signal, socket, subprocess, sys, time, webbrowser
from urllib import request as ureq, error as uerr

HOME = os.path.expanduser("~")
CFG_DIR = os.path.join(HOME, ".venice")
CFG_PATH = os.path.join(CFG_DIR, "config.json")
DEFAULT_PROXY_KEY = "sk-venice-free-proxy"
TOKEN_PAGE = "https://dash.cloudflare.com/profile/api-tokens"
WRANGLER_DEPLOY_URL = "https://developers.cloudflare.com/api/resources/workers/subscripts/proxies/"  # perms doc pointer

def cfg_load():
    try:
        with open(CFG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

def cfg_save(c):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG_PATH, "w") as f:
        json.dump(c, f, indent=2)

def env(k, default=None):
    return os.environ.get(k, default)

def resolve_key():
    return env("VENICE_API_KEY", DEFAULT_PROXY_KEY)

def reachable(url, timeout=4):
    """Cheap HEAD/GET probe: is this base URL alive & responding like an OpenAI proxy."""
    if not url:
        return False
    try:
        r = ureq.urlopen(url.rstrip("/") + "/v1/models", timeout=timeout)
        return r.status == 200
    except Exception:
        return False

def worker_url():
    """Configured Cloudflare Worker base URL (no trailing /v1)."""
    u = env("VENICE_WORKER_URL")
    if u:
        return u.rstrip("/")
    c = cfg_load()
    w = c.get("worker_url")
    return (w.rstrip("/")) if w else None

def endpoint(path):
    """Return the full URL for a /v1 path, preferring the Worker over local proxy."""
    w = worker_url()
    if w and reachable(w + "/v1"):
        return w + "/v1/" + path.lstrip("/")
    # fall back to local proxy (auto-started)
    base = env("VENICE_BASE_URL", "http://127.0.0.1:8000/v1")
    return base.rstrip("/") + "/" + path.lstrip("/")

def ensure_local_proxy():
    """Start venice_proxy.py in the background if localhost isn't answering."""
    base = env("VENICE_BASE_URL", "http://127.0.0.1:8000/v1")
    if reachable(base):
        return None
    here = os.path.dirname(os.path.abspath(__file__))
    proxy = os.path.join(here, "venice_proxy.py")
    if not os.path.exists(proxy):
        return None
    proc = subprocess.Popen([sys.executable, proxy], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        time.sleep(0.25)
        if reachable(base):
            return proc
    return proc

# ---- deploy -------------------------------------------------------------

PERMS = ("Workers Scripts: Edit  (Account resource)")
def deploy():
    c = cfg_load()
    w = worker_url()
    if w and reachable(w + "/v1"):
        print(f"OK — Cloudflare Worker already live at {w}\n  (route: {w}/v1)")
        return 0
    token = env("CF_API_TOKEN")
    acct = env("CF_ACCOUNT_ID")
    if not token or not acct:
        print("To deploy the Ultimate proxy to Cloudflare, I need a Cloudflare API")
        print("token with this permission:\n    " + PERMS + "\n")
        print("Opening the token page in your browser (log in if needed, click")
        print('"Create Token", select "Custom token", grant the permission above",')
        print("then re-run:\n    CF_API_TOKEN=... CF_ACCOUNT_ID=... venice deploy")
        webbrowser.open(TOKEN_PAGE)
        return 2
    # deploy via wrangler
    if not shutil.which("npx"):
        print("install node.js/npx first"); return 1
    here = os.path.dirname(os.path.abspath(__file__))
    envp = dict(os.environ, CF_API_TOKEN=token, CF_ACCOUNT_ID=acct)
    print("Deploying venice-free-ai-proxy to Cloudflare (edge IPs auto-rotate)...")
    try:
        out = subprocess.run(["npx", "--yes", "wrangler", "deploy",
                              os.path.join(here, "worker.js"),
                              "--name", "venice-free-ai-proxy"],
                             check=True, env=envp, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        txt = out.stdout
    except subprocess.CalledProcessError as e:
        print(e.stdout or e); return e.returncode
    except subprocess.TimeoutExpired:
        print("wrangler deploy timed out"); return 1
    # parse URL
    import re
    m = re.search(r"https://[a-z0-9-]+\.workers\.dev", txt)
    if not m:
        print(txt[-500:]); print("deploy output above — set VENICE_WORKER_URL manually"); return 1
    url = m.group(0)
    envp_secret = "sk-venice-free-proxy"
    c["worker_url"] = url
    c["api_key"] = envp_secret
    cfg_save(c)
    print(f"Live: {url}\nPoint clients at: VENICE_BASE_URL={url}/v1 VENICE_API_KEY={envp_secret}")
    print('Next:  venice chat "hello"')
    return 0

# ---- commands -----------------------------------------------------------

def _auth_headers(extra=None):
    h = {"Authorization": "Bearer " + resolve_key()}
    if extra:
        h.update(extra)
    return h

def _post(body):
    p = endpoint("chat/completions")
    data = json.dumps(body).encode()
    req = ureq.Request(p, data=data, method="POST",
                       headers=_auth_headers({"Content-Type": "application/json",
                                              "Accept": "text/event-stream"}))
    return ureq.urlopen(req, timeout=120)

def chat(args):
    prompt = " ".join(args) if args else None
    if not prompt:
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("usage: venice chat \"<prompt>\"", file=sys.stderr); return 2
    body = {"model": "deepseek-v4-1-flash-free",
            "messages": [{"role": "user", "content": prompt}], "stream": True}
    try:
        resp = _post(body)
    except uerr.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        if e.code in (401, 403, 429):
            print("-> no live Worker & local proxy unavailable: run 'venice deploy'", file=sys.stderr)
        return 1
    except uerr.URLError as e:
        print(f"connection failed: {e}\n-> run 'venice deploy' or start venice_proxy.py", file=sys.stderr); return 1
    got = False
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("data: "):
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            try:
                d = json.loads(payload)
                chunk = d.get("choices", [{}])[0].get("delta", {}).get("content")
                if chunk is not None:
                    sys.stdout.write(chunk); sys.stdout.flush(); got = True
            except Exception:
                pass
    if got:
        print()
    else:
        print("\n(no response)")
    return 0

def models(args):
    r = ureq.urlopen(endpoint("models"), timeout=30)
    print(json.dumps(json.loads(r.read()), indent=2)); return 0

def info(args):
    base = endpoint("")  # ends with /v1/ -> strip to base
    base = base.rstrip("/").rsplit("/", 1)[0]  # -> http(s)://host  (drops /v1)
    r = ureq.urlopen(base + "/", timeout=30)
    print(json.dumps(json.loads(r.read()), indent=2)); return 0

def health(args):
    b = endpoint("models")
    print(f"OK  {b}" if reachable(b) else f"DOWN {b}"); return 0 if reachable(b) else 1

def doctor(args):
    print(f"config: {cfg_load()}")
    print(f"VENICE_WORKER_URL env: {env('VENICE_WORKER_URL') or '(unset)'}")
    w = worker_url()
    if w:
        up = reachable(w + "/v1")
        print(f"Cloudflare Worker {w}: {'UP (edge, auto-IP-rotation)' if up else 'configured but unreachable — run: venice deploy'}")
    else:
        print("Cloudflare Worker: none configured  ->  run: venice deploy")
    ensure_local_proxy()
    base = env("VENICE_BASE_URL", "http://127.0.0.1:8000/v1")
    print(f"Local proxy {base}: {'UP' if reachable(base) else 'DOWN'}")
    return 0

def main():
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[0]); print("run 'venice deploy' first, then 'venice chat \"hi\"'. see: venice doctor"); return 2
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "deploy":
        return deploy()
    if cmd == "chat":
        return chat(rest)
    if cmd == "models":
        return models(rest)
    if cmd == "info":
        return info(rest)
    if cmd == "health":
        return health(rest)
    if cmd == "doctor":
        return doctor(rest)
    print("unknown command:", cmd, file=sys.stderr); return 2

if __name__ == "__main__":
    sys.exit(main())
