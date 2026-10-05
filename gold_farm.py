#!/usr/bin/env python3
"""gold_farm.py — farm akun di host golden, dari runner GH (IP Azure fresh).
usage: gold_farm.py HOST COUNT_PER_RUNNER SHARD
Pakai naytra (HTTP, no browser). Output gold_<shard>.jsonl"""
import sys, json, re, time, random, string, base64
import urllib.request, urllib.error

HOST = sys.argv[1] if len(sys.argv) > 1 else "43.166.9.34:3000"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
SHARD = sys.argv[3] if len(sys.argv) > 3 else "0"
BASE = "http://" + HOST
OUT = f"gold_{SHARD}.jsonl"
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"}
CODE_RE = re.compile(r'<strong>\s*([A-Za-z0-9]{4,8})\s*</strong>')

# --- naytra inline (no local dep) ---
import os
NAYTRA = "https://mail.naytra.net"
S = urllib.request.build_opener()
import http.cookiejar
CJ = http.cookiejar.CookieJar()
OP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CJ))


def nlogin():
    body = urllib.parse.urlencode({"username": os.environ.get("NAYTRA_USER", "asu22"),
                                   "password": os.environ.get("NAYTRA_PW", "Germand26")}).encode()
    r = urllib.request.Request(NAYTRA + "/login", data=body, headers={"User-Agent": UA["User-Agent"],
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        OP.open(r, timeout=30).read()
    except Exception:
        pass


def nget(path):
    r = urllib.request.Request(NAYTRA + path, headers={"User-Agent": UA["User-Agent"], "Accept": "application/json"})
    try:
        return json.loads(OP.open(r, timeout=40).read().decode())
    except Exception:
        return {}


import urllib.parse


def new_inbox():
    nlogin()
    d = nget("/api/generate")
    a = d.get("address") or ""
    if a:
        try:
            r = urllib.request.Request(NAYTRA + "/api/saved", data=json.dumps({"address": a}).encode(),
                headers={"User-Agent": UA["User-Agent"], "Content-Type": "application/json"})
            OP.open(r, timeout=25).read()
        except Exception:
            pass
    return a


def wait_code(addr, timeout=240):
    start = time.time()
    while time.time() - start < timeout:
        d = nget(f"/api/inbox/{addr}")
        for e in (d.get("emails") or []):
            ed = nget(f"/api/email/{e['id']}")
            m = CODE_RE.search(ed.get("body_html", ""))
            if m:
                return m.group(1)
        time.sleep(6)
    return None


def rq(m, p, b=None, h=None, t=40):
    r = urllib.request.Request(BASE + p, data=json.dumps(b).encode() if b is not None else None,
        method=m, headers={**UA, **(h or {})})
    try:
        with urllib.request.urlopen(r, timeout=t) as x:
            return x.status, x.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return 0, str(e)[:60]


def farm_one():
    addr = new_inbox()
    if not addr:
        return {"verdict": "NO_MAILBOX"}
    rq("GET", f"/api/verification?email={addr}")
    code = wait_code(addr)
    if not code:
        return {"verdict": "NO_CODE", "email": addr}
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    u = "s" + tag; pw = "S" + "".join(random.choices(string.ascii_letters + string.digits, k=10))
    s, b = rq("POST", "/api/user/register",
              {"username": u, "password": pw, "password2": pw, "email": addr, "verification_code": code})
    if '"success":true' not in b.replace(" ", ""):
        return {"verdict": "REG_FAIL", "body": b[:60], "email": addr}
    s, lb = rq("POST", "/api/user/login", {"username": u, "password": pw})
    uid = tok = None
    try:
        dd = json.loads(lb)["data"]; uid = dd.get("id"); tok = dd.get("access_token")
        if not uid and tok:
            uid = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))["sub"]
    except Exception:
        pass
    hd = {"New-Api-User": str(uid)}
    if tok:
        hd["Authorization"] = "Bearer " + tok
    rq("POST", "/api/token/", {"name": "t1", "remain_quota": 500000000, "unlimited_quota": True,
       "expired_time": -1, "model_limits_enabled": False, "group": ""}, hd)
    s, tl = rq("GET", "/api/token/?p=0&size=20", h=hd)
    key = None
    try:
        it = json.loads(tl)["data"]["items"][-1]
        s, kk = rq("POST", f"/api/token/{it['id']}/key", h=hd)
        key = json.loads(kk)["data"]["key"]
    except Exception:
        pass
    if not key:
        return {"verdict": "NO_KEY", "user": u, "pass": pw, "email": addr}
    s, cb = rq("POST", "/v1/chat/completions",
               {"model": "claude-haiku-4-5", "messages": [{"role": "user", "content": "PONG"}], "max_tokens": 8},
               {"Authorization": "Bearer " + key})
    ok = s == 200 and '"content"' in cb
    rec = {"host": HOST, "verdict": "LIVE" if ok else "KEY_NO_CHAT", "user": u, "pass": pw, "email": addr, "key": key, "uid": uid}
    with open(OUT, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


ok = 0
for i in range(N):
    r = farm_one()
    if r.get("verdict") == "LIVE":
        ok += 1
    print(f"[{i}] {r.get('verdict')} {r.get('email','')} {r.get('body','')}", flush=True)
    time.sleep(3)
print(f"DONE shard={SHARD} live={ok}/{N}")
