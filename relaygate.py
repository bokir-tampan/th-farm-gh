#!/usr/bin/env python3
"""relaygate.py — dari IP fresh (GH runner): untuk tiap host relay, register 1 akun
+ baca quota. Output relay_gate.jsonl."""
import json, random, string, sys, time, re
import requests

HOSTS = [h.strip() for h in open(sys.argv[1]) if h.strip()]
OUT = sys.argv[2] if len(sys.argv) > 2 else "relay_gate.jsonl"
fo = open(OUT, "a")


def one(host):
    if not host.startswith("http"):
        host = "https://" + host
    for _a in range(2):
        try:
            s = requests.Session()
            s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/131.0",
                              "Content-Type": "application/json",
                              "Origin": host, "Referer": host + "/"})
            tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
            u = "r" + tag
            p = "R" + "".join(random.choices(string.ascii_letters + string.digits, k=11))
            rg = s.post(host + "/api/user/register",
                        json={"username": u, "password": p, "password2": p,
                              "email": f"{tag}@gmail.com", "verification_code": ""}, timeout=20)
            body = rg.text[:160]
            low = body.lower()
            if not body.strip().startswith("{"):
                if "502" in body or "504" in body or "521" in body:
                    return {"host": host, "verdict": "DOWN", "body": body[:60]}
                time.sleep(3); continue
            if '"success":true' in low or '"success": true' in low:
                j = s.post(host + "/api/user/login", json={"username": u, "password": p}, timeout=20).json()
                uid = (j.get("data") or {}).get("id")
                hd = {"New-Api-User": str(uid), "New-API-User": str(uid)}
                sd = s.get(host + "/api/user/self", headers=hd, timeout=20).json().get("data") or {}
                return {"host": host, "verdict": "REG_OK", "user": u, "pass": p,
                        "uid": uid, "quota": sd.get("quota"), "body": ""}
            if "turnstile" in low or "security verification" in low:
                return {"host": host, "verdict": "TURNSTILE", "body": body[:70]}
            if "verificat" in low or "验证" in body:
                return {"host": host, "verdict": "NEED_CODE", "body": body[:70]}
            if "disabled" in low or "关闭" in body or "邀请码" in body:
                return {"host": host, "verdict": "CLOSED", "body": body[:70]}
            if "qq.com" in body:
                return {"host": host, "verdict": "QQ_ONLY", "body": body[:70]}
            return {"host": host, "verdict": "OTHER", "body": body[:90]}
        except Exception as e:
            time.sleep(2)
    return {"host": host, "verdict": "ERR"}


for h in HOSTS:
    r = one(h)
    fo.write(json.dumps(r, ensure_ascii=False) + "\n"); fo.flush()
    if r["verdict"] in ("REG_OK", "NEED_CODE", "QQ_ONLY"):
        print(f"  {h:30s} {r['verdict']:10s} q={r.get('quota')} {r.get('body','')[:40]}", flush=True)
    else:
        print(f"  {h:30s} {r['verdict']}", flush=True)
