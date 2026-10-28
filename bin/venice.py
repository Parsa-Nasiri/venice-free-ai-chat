#!/usr/bin/env python3
"""venice CLI — talk to the OpenAI-compatible proxy (local python or Cloudflare Worker).

Config: env vars
  VENICE_BASE_URL  http(s)://<host>/v1   (default http://127.0.0.1:8000/v1)
  VENICE_API_KEY   bearer token the proxy expects (default: sk-venice-free-proxy)

Commands:
  venice chat "prompt"        stream a chat (SSE -> stdout; ends on data: [DONE])
  venice chat -f file         chat, reading a transcript (see below)
  venice models               list models
  venice info                 proxy info / base_url
  venice health               GET /v1/models probe (exit 0 if up)
"""
import json, os, sys, urllib.request, urllib.error

BASE = os.environ.get("VENICE_BASE_URL", "http://127.0.0.1:8000/v1")
if not BASE.endswith("/"):
    BASE += "/"
KEY = os.environ.get("VENICE_API_KEY", "sk-venice-free-proxy")

def req(path, method="GET", body=None):
    headers = {"Authorization": "Bearer " + KEY}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    return urllib.request.urlopen(r, timeout=60)

def get(path):
    r = req(path)
    return r.status, r.read().decode()

def chat(args):
    prompt = None
    if len(args) > 1:
        prompt = " ".join(args[1:])
    else:
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("usage: venice chat \"<prompt>\"", file=sys.stderr); sys.exit(2)
    body = {"model": "deepseek-v4-1-flash-free", "messages": [{"role": "user", "content": prompt}], "stream": True}
    headers = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json", "Accept": "text/event-stream"}
    r = urllib.request.Request(BASE + "chat/completions", data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        sys.stdout.flush()
                        print()  # trailing newline on clean stream end
                        return
                    try:
                        d = json.loads(payload)
                        chunk = d.get("choices", [{}])[0].get("delta", {}).get("content")
                        if chunk is not None:
                            sys.stdout.write(chunk)
                            sys.stdout.flush()
                    except Exception:
                        pass
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)

def models(args):
    print(json.dumps(json.loads(get("models")[1]), indent=2))

def info(args):
    print(json.dumps(json.loads(get("")[1]), indent=2))

def health(args):
    try:
        st, _ = get("models")
        print("up", st); sys.exit(0)
    except Exception as e:
        print("down:", e); sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[0]); print("run 'venice chat' or 'venice models'"); sys.exit(2)
    cmd = sys.argv[1]
    {
        "chat": chat,
        "models": models,
        "info": info,
        "health": health,
    }.get(cmd, lambda a: (print("unknown: " + cmd, file=sys.stderr), sys.exit(2)))(sys.argv[1:])

if __name__ == "__main__":
    main()
