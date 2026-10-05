#!/usr/bin/env python3
"""scan_http.py — sapu /16 (http-only) cari New-API di port 3000/3001.
TCP open -> http /api/status -> register -> quota. http, JANGAN https.
Arg: prefixes(csv a.b)  ports(csv)  shard  nshards  out
Inkremental. VPS-hemat (batch)."""
import asyncio, json, random, string, socket, sys, time
import aiohttp

PFX = [p.strip() for p in sys.argv[1].split(",") if p.strip()]
PORTS = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "3000,3001").split(",")]
SHARD = int(sys.argv[3]) if len(sys.argv) > 3 else 0
NS = int(sys.argv[4]) if len(sys.argv) > 4 else 1
OUT = sys.argv[5] if len(sys.argv) > 5 else f"scan_http_{SHARD}.jsonl"
TUNE = 1.0
CONC = 800
UA = {"User-Agent": "Mozilla/5.0 Chrome/131.0", "Accept": "application/json",
      "Content-Type": "application/json"}
fo = open(OUT, "a")


async def tcp_open(sem, ip, port):
    async with sem:
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=TUNE)
            w.close()
            return True
        except Exception:
            return False


def jparse(t):
    try:
        return json.loads(t)
    except Exception:
        return None


async def check(sess, ip, port):
    base = f"http://{ip}:{port}"
    try:
        async with sess.get(base + "/api/status", timeout=6) as r:
            if r.status != 200:
                return None
            j = jparse(await r.text())
    except Exception:
        return None
    if not isinstance(j, dict) or "data" not in j:
        return None
    d = j.get("data") or {}
    rec = {"host": f"{ip}:{port}", "register": d.get("register_enabled"),
           "pwd": d.get("password_register_enabled"), "email": d.get("email_verification"),
           "turnstile": d.get("turnstile_check"), "name": d.get("system_name")}
    if not d.get("register_enabled"):
        rec["verdict"] = "REG_TUTUP"
    else:
        tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
        u = "s" + tag
        pw = "S" + "".join(random.choices(string.ascii_letters + string.digits, k=10))
        try:
            async with sess.post(base + "/api/user/register",
                    json={"username": u, "password": pw, "password2": pw,
                          "email": f"{tag}@gmail.com", "verification_code": ""}, timeout=12) as r:
                b = await r.text()
        except Exception:
            b = ""
        low = b.lower()
        if '"success":true' in low or '"success": true' in low:
            # login + quota
            try:
                async with sess.post(base + "/api/user/login",
                        json={"username": u, "password": pw}, timeout=12) as r:
                    lj = jparse(await r.text()) or {}
            except Exception:
                lj = {}
            dd = (lj.get("data") if isinstance(lj, dict) else {}) or {}
            uid = dd.get("id") or (dd.get("user") or {}).get("id")
            hd = {"New-Api-User": str(uid), "New-API-User": str(uid)}
            q = None
            try:
                async with sess.get(base + "/api/user/self", headers=hd, timeout=12) as r:
                    sd = jparse(await r.text()) or {}
                q = (sd.get("data") or {}).get("quota")
            except Exception:
                pass
            rec.update({"verdict": "REG_OK", "user": u, "pass": pw, "uid": uid, "quota": q})
        elif "turnstile" in low or "security verification" in low:
            rec["verdict"] = "TURNSTILE"
        elif "verificat" in low or "验证" in b:
            rec["verdict"] = "NEED_CODE"
        elif "disabled" in low or "关闭" in b:
            rec["verdict"] = "CLOSED"
        else:
            rec["verdict"] = "OTHER"
    fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
    return rec


async def main():
    sem = asyncio.Semaphore(CONC)
    conn = aiohttp.TCPConnector(limit=CONC + 200, ssl=False, force_close=True)
    t0 = time.time()
    gen = []
    for p in PFX:
        a, b = p.split(".")
        for c in range(1, 255):
            for d in range(1, 255):
                gen.append(f"{a}.{b}.{c}.{d}")
    # shard
    ips = gen[SHARD::NS]
    hits = 0
    async with aiohttp.ClientSession(connector=conn, headers=UA) as sess:
        for i in range(0, len(ips), 3000):
            chunk = ips[i:i + 3000]
            opens = await asyncio.gather(*[tcp_open(sem, ip, p) for ip in chunk for p in PORTS])
            oip = [ip for ip, ok in zip(chunk, opens[::len(PORTS)]) if ok] if False else []
            # rebuild open list
            k = 0
            for ip in chunk:
                for p in PORTS:
                    if opens[k]:
                        oip.append((ip, p))
                    k += 1
            res = await asyncio.gather(*[check(sess, ip, p) for ip, p in oip], return_exceptions=True)
            for r in res:
                if isinstance(r, dict) and r.get("verdict") in ("REG_OK", "NEED_CODE", "TURNSTILE"):
                    hits += 1
                    print(f"  {r['host']:22s} {r['verdict']:10s} q={r.get('quota')} {r.get('name','')}", flush=True)
            print(f"  {min(i+3000,len(ips))}/{len(ips)} open={len(oip)} hits={hits} {round(time.time()-t0)}s", flush=True)
    print(f"DONE shard {SHARD} {round(time.time()-t0)}s hits={hits}")

asyncio.run(main())
