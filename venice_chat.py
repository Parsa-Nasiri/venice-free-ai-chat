#!/usr/bin/env python3
"""Send a message to a logged-in Venice.ai chat and print the reply.

Requires: a `browser-act` session (chrome / chrome-direct / stealth) with
Venice.ai open and the user signed in. The message is typed into the page
input and Enter is pressed; the rendered reply is read back from the DOM.

Usage:
    python3 venice_chat.py "your message here"
"""
import asyncio, json, sys, time
import websockets

CDP_URL = sys.argv[1] if len(sys.argv) > 1 else ""
MESSAGE = sys.argv[2] if len(sys.argv) > 2 else "What is 2+2?"

JS_INPUT = ("(async()=>{const el=document.querySelector('textarea.chakra-textarea')"
            "||document.querySelector('textarea');if(!el)return 'NO_INPUT';"
            "el.focus();return JSON.stringify({tag:el.tagName,placeholder:el.placeholder,"
            "cls:el.className,role:el.getAttribute('role'),id:el.id})})()")
JS_READ = ("(async()=>{const ms=Array.from(document.querySelectorAll("
            "'[data-message-id],.message,[class*=message]'));const out=[];"
            "ms.forEach((m,i)=>{const t=(m.textContent||'').trim();"
            "if(t)out.push(i+':'+t.slice(0,800))});return JSON.stringify(out)})()")

async def main():
    ws = await websockets.connect(CDP_URL, max_size=None)
    q = asyncio.Queue()
    sid = [None]
    n = [900000]

    async def rd():
        while True:
            try:
                r = json.loads(await ws.recv())
            except Exception:
                return
            await q.put(r)

    async def cmd(method, params=None, timeout=25):
        n[0] += 1
        msg = {"id": n[0], "method": method, "params": params}
        if sid[0]:
            msg["sessionId"] = sid[0]
        await ws.send(json.dumps(msg))
        dl = time.time() + timeout
        while time.time() < dl:
            try:
                r = await asyncio.wait_for(q.get(), timeout=3)
            except asyncio.TimeoutError:
                continue
            if r.get("id") == n[0]:
                return r
        return None

    t = asyncio.create_task(rd())
    try:
        r = await cmd("Target.getTargets", {}, timeout=30)
        if r is None or "result" not in r:
            print("NO TARGETS:", r); return
        pages = [x for x in r["result"]["targetInfos"]
                 if x["type"] == "page" and "venice.ai" in x.get("url", "")]
        if not pages:
            print("NO VENICE PAGE:", [x.get("url") for x in r["result"]["targetInfos"]][:5]); return
        page = pages[0]

        r = await cmd("Target.attachToTarget",
                      {"targetId": page["targetId"], "flatten": True}, timeout=30)
        if r is None or "result" not in r:
            print("ATTACH FAILED:", r); return
        sid[0] = r["result"]["sessionId"]

        await cmd("Runtime.enable")
        await cmd("Network.enable", {"maxPostDataSize": 100000000})

        r = await cmd("Runtime.evaluate",
                      {"expression": JS_INPUT, "returnByValue": True, "awaitPromise": True})
        print("INPUT:", r["result"]["result"]["value"] if r else None)

        js = ("(async()=>{const el=document.querySelector('textarea.chakra-textarea')"
              "||document.querySelector('textarea');if(!el)return 'NO_INPUT';"
              "el.focus();el.value=" + json.dumps(MESSAGE) +
              ";el.dispatchEvent(new Event('input',{bubbles:true}));return 'typed'})()")
        await cmd("Runtime.evaluate", {"expression": js, "returnByValue": True,
                                       "awaitPromise": True})
        await asyncio.sleep(1)
        await cmd("Input.sendKey", {"key": "Enter", "code": "Enter",
                                    "text": "Enter", "location": 0})

        for _ in range(8):
            await asyncio.sleep(4)
            r = await cmd("Runtime.evaluate",
                          {"expression": JS_READ, "returnByValue": True,
                           "awaitPromise": True}, timeout=10)
            if r and r.get("result"):
                val = r["result"]["result"]["value"]
                try:
                    msgs = json.loads(val)
                except Exception:
                    msgs = [val]
                # last message is the assistant reply
                last = msgs[-1] if msgs else val
                if last and not str(last).startswith("0:What is 2+2") and "Worked for" in str(last):
                    print("REPLY:", last)
                    return
        r = await cmd("Runtime.evaluate", {"expression": JS_READ, "returnByValue": True,
                                           "awaitPromise": True})
        print("DOM:", r["result"]["result"]["value"] if r else None)
    finally:
        t.cancel()
        await ws.close()

if __name__ == "__main__":
    asyncio.run(main())