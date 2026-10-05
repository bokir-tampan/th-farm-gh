#!/usr/bin/env python3
"""relayfarm.py — farm akun New-API dari domain relay (helpcoder.cc dst).
Dipakai di GH Actions: 1 runner = 1 IP fresh.
Arg: base_url  count  per_job  shard
Output: relay_shard<shard>.jsonl"""
import json, random, string, sys, time
import requests

BASE = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 6
WORK = int(sys.argv[3]) if len(sys.argv) > 3 else 3
SHARD = sys.argv[4] if len(sys.argv) > 4 else "1"
OUT = f"relay_shard{SHARD}.jsonl"
fo = open(OUT, "a")


def one(_):
    for _a in range(3):
        try:
            s = requests.Session()
            s.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/131.0",
                              "Content-Type": "application/json",
                              "Origin": BASE, "Referer": BASE + "/"})
            tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
            u = "r" + tag
            p = "R" + "".join(random.choices(string.ascii_letters + string.digits, k=11))
            rg = s.post(BASE + "/api/user/register",
                        json={"username": u, "password": p, "password2": p,
                              "email": f"{tag}@gmail.com", "verification_code": ""}, timeout=25)
            if not rg.text.strip().startswith("{"):
                time.sleep(4); continue
            j = s.post(BASE + "/api/user/login", json={"username": u, "password": p}, timeout=25).json()
            uid = (j.get("data") or {}).get("id")
            if not uid:
                time.sleep(3); continue
            hd = {"New-Api-User": str(uid), "New-API-User": str(uid)}
            sd = s.get(BASE + "/api/user/self", headers=hd, timeout=25).json().get("data") or {}
            q = sd.get("quota")
            items = (s.get(BASE + "/api/token/?p=0&size=20", headers=hd, timeout=25).json().get("data") or {}).get("items") or []
            key = None
            if items:
                tid = items[-1]["id"]
                kr = s.post(BASE + f"/api/token/{tid}/key", headers=hd, timeout=25).json()
                d2 = kr.get("data")
                key = (d2.get("key") if isinstance(d2, dict) else d2)
                if not key or len(str(key)) < 40:
                    key = None
            rec = {"host": BASE, "user": u, "pass": p, "uid": uid, "quota": q, "key": key,
                   "verdict": "KEY" if key else "NO_KEY"}
            if key:
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
            return rec
        except Exception:
            time.sleep(3)
    return {"host": BASE, "verdict": "EXC"}


import threading
ok = 0
lk = threading.Lock()
res = []


def w():
    global ok
    while True:
        with lk:
            if not queue:
                return
            queue.pop()
        r = one(0)
        if r.get("key"):
            with lk:
                ok += 1
            print(f"OK {r['user']} q={r['quota']} {r['key'][:16]}...", flush=True)


queue = list(range(N))
ths = [threading.Thread(target=w) for _ in range(WORK)]
[t.start() for t in ths]
[t.join() for t in ths]
print(f"shard {SHARD}: {ok}/{N} -> {OUT}")