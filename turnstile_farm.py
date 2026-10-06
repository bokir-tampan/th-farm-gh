#!/usr/bin/env python3
"""turnstile_farm.py — daftar akun di host new-api ber-Turnstile.

Pakai Camoufox (browser stealth) buat solve Turnstile + harvest token,
lalu register via API. Vision LLM (9router) opsional buat captcha interaktif.

usage: turnstile_farm.py HOST COUNT SHARD
env  : VISION_BASE_URL, VISION_MODEL, VISION_API_KEY
"""
import sys, os, json, time, random, string, base64, tempfile
import urllib.request, urllib.error

HOST = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SHARD = sys.argv[3] if len(sys.argv) > 3 else "0"
BASE = "http://" + HOST
OUT = f"tst_{SHARD}.jsonl"
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

VISION_BASE = os.getenv("VISION_BASE_URL", "").rstrip("/")
VISION_MODEL = os.getenv("VISION_MODEL", "gemini-3.8-flash-high")
VISION_KEY = os.getenv("VISION_API_KEY", "")


def rq(m, p, b=None, h=None, t=40):
    req = urllib.request.Request(BASE + p, data=json.dumps(b).encode() if b is not None else None,
                                 method=m, headers={**UA, **(h or {})})
    try:
        with urllib.request.urlopen(req, timeout=t) as x:
            return x.status, x.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return 0, str(e)[:60]


def vision_ask(img_path, prompt, timeout=120):
    """Tanya vision model (9router) soal screenshot. Return teks."""
    if not VISION_BASE or not VISION_KEY:
        return ""
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {"model": VISION_MODEL, "temperature": 0.0, "stream": False,
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]}
    req = urllib.request.Request(VISION_BASE + "/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + VISION_KEY})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
        return r["choices"][0]["message"].get("content", "") or ""
    except Exception as e:
        print("  vision err:", str(e)[:60], flush=True)
        return ""


def solve_turnstile(page, timeout_s=90):
    """Tunggu Turnstile render, klik checkbox kalau interaktif, ambil token."""
    deadline = time.time() + timeout_s
    clicked = False
    while time.time() < deadline:
        # token dari hidden input atau API
        token = page.evaluate("""() => {
            const el = document.querySelector('input[name="cf-turnstile-response"]')
                    || document.querySelector('textarea[name="cf-turnstile-response"]');
            if (el && el.value) return el.value;
            try { if (window.turnstile && window.turnstile.getResponse) {
                    const t = window.turnstile.getResponse(); if (t) return t; } } catch(e){}
            const d = document.querySelector('.cf-turnstile');
            if (d && d.dataset && d.dataset.response) return d.dataset.response;
            return '';
        }""")
        if token:
            return token
        # belum ada token → coba klik checkbox di iframe
        if not clicked:
            try:
                for fr in page.frames:
                    if "challenges.cloudflare.com" in (fr.url or ""):
                        box = fr.query_selector("input[type=checkbox], #challenge-stage, .ctp-checkbox-label")
                        if box:
                            box.click(timeout=3000)
                            clicked = True
                            print("  klik checkbox turnstile", flush=True)
                            break
            except Exception:
                pass
            # fallback: klik koordinat widget
            if not clicked:
                try:
                    el = page.query_selector(".cf-turnstile")
                    if el:
                        bb = el.bounding_box()
                        if bb:
                            page.mouse.click(bb["x"] + 30, bb["y"] + bb["height"] / 2)
                            clicked = True
                            print("  klik koordinat turnstile", flush=True)
                except Exception:
                    pass
        time.sleep(2)
    return ""


def register_one(page, i):
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    u = "t" + tag
    pw = "Tz9" + "".join(random.choices(string.ascii_letters + string.digits, k=9))
    email = f"{tag}@gmail.com"

    page.goto(BASE + "/register", wait_until="domcontentloaded", timeout=45000)
    time.sleep(3)
    # tunggu widget turnstile muncul
    for _ in range(15):
        has = page.evaluate("() => !!(document.querySelector('.cf-turnstile') || document.querySelector('iframe[src*=\"challenges.cloudflare.com\"]'))")
        if has:
            break
        time.sleep(1)
    token = solve_turnstile(page, timeout_s=75)
    if not token:
        # DEBUG: dump state
        try:
            dbg = page.evaluate("""() => {
                const all = [];
                document.querySelectorAll('input,textarea,iframe,div').forEach(el => {
                    const t = (el.tagName||'').toLowerCase();
                    const cls = el.className || '';
                    const nm = el.name || '';
                    const src = el.src || '';
                    if (t==='iframe'||nm.includes('turnstile')||cls.includes('turnstile')||cls.includes('cf-'))
                        all.push(t+'.'+String(cls).slice(0,40)+' name='+nm+' src='+String(src).slice(0,60));
                });
                return {url:location.href, title:document.title, n:all.length, els:all.slice(0,25),
                        bodyLen:document.body.innerHTML.length};
            }""")
            print("  DEBUG:", json.dumps(dbg)[:800], flush=True)
            page.screenshot(path=f"dbg_{SHARD}.png", full_page=True)
        except Exception as e:
            print("  debug err:", str(e)[:80], flush=True)
        return {"host": HOST, "verdict": "NO_TOKEN"}
    print(f"[{i}] token={token[:16]}...", flush=True)

    s, b = rq("POST", "/api/user/register", {
        "username": u, "password": pw, "password2": pw, "email": email,
        "verification_code": "", "turnstile_token": token, "aff_code": ""})
    if '"success":true' not in b.replace(" ", ""):
        return {"host": HOST, "verdict": "REG_FAIL", "msg": b[:90]}

    s, lb = rq("POST", "/api/user/login", {"username": u, "password": pw})
    uid = tok = None
    try:
        dd = json.loads(lb)["data"]; uid = dd.get("id"); tok = dd.get("access_token")
        if not uid and tok:
            uid = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))["sub"]
    except Exception:
        return {"host": HOST, "verdict": "LOGIN_FAIL", "msg": lb[:80]}
    hd = {"New-Api-User": str(uid)}
    if tok:
        hd["Authorization"] = "Bearer " + tok
    s, sf = rq("GET", "/api/user/self", h=hd)
    q = None
    try:
        q = json.loads(sf)["data"]["quota"]
    except Exception:
        pass
    rq("POST", "/api/token/", {"name": "t1", "remain_quota": 500000000, "unlimited_quota": True,
       "expired_time": -1, "model_limits_enabled": False, "group": ""}, hd)
    s, tl = rq("GET", "/api/token/?p=0&size=20", h=hd)
    key = None
    try:
        tid = json.loads(tl)["data"]["items"][-1]["id"]
        s, kk = rq("POST", f"/api/token/{tid}/key", h=hd)
        key = json.loads(kk)["data"]["key"]
    except Exception:
        pass
    live = False
    if key:
        s, mo = rq("GET", "/v1/models", h={"Authorization": "Bearer " + key})
        ids = []
        try:
            ids = [m["id"] for m in json.loads(mo).get("data", [])]
        except Exception:
            pass
        for m in (ids[:4] or ["deepseek-chat"]):
            s, cb = rq("POST", "/v1/chat/completions",
                       {"model": m, "messages": [{"role": "user", "content": "PONG"}], "max_tokens": 6},
                       {"Authorization": "Bearer " + key})
            try:
                mm = json.loads(cb)["choices"][0]["message"]
                if mm.get("content") or mm.get("reasoning_content"):
                    live = True
                    break
            except Exception:
                pass
    rec = {"host": HOST, "verdict": "LIVE" if live else ("KEY_NO_CHAT" if key else "NO_KEY"),
           "user": u, "pass": pw, "uid": uid, "quota": q, "key": key, "email": email}
    return rec


def main():
    from camoufox.sync_api import Camoufox
    ok = 0
    with Camoufox(headless=True, humanize=True, geoip=True) as browser:
        page = browser.new_page()
        for i in range(N):
            try:
                rec = register_one(page, i)
            except Exception as e:
                rec = {"host": HOST, "verdict": "ERR", "msg": str(e)[:90]}
            print(f"[{i}] {rec['verdict']} q={rec.get('quota')}", flush=True)
            if rec["verdict"] == "LIVE":
                ok += 1
            if rec.get("key"):
                open(OUT, "a").write(json.dumps(rec, ensure_ascii=False) + "\n")
            time.sleep(2)
    print(f"DONE shard={SHARD} live={ok}/{N}")


if __name__ == "__main__":
    main()
