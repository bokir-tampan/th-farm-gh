#!/usr/bin/env python3
"""zoya_worker.py — 1 runner GitHub Action = 1 akun Zoyalink.

Alur:
  naytra inbox -> register (OTP) -> tarik OTP -> verify -> login
  -> (opsional) upload video via /upload URL-flow
  -> tulis result.json (akun mentah) + state.txt

Env:
  ZOYA_PROXY   proxy tunggal (mis. http://u:p@host:port) — kalau kosong, langsung
  ZOYA_REF     kode referral (default a66b1a6f)
  ZOYA_VIDEO   URL .mp4 untuk auto-upload (opsional)
  NAYTRA_USER  / NAYTRA_PW  kredensial inbox
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from naytra_client import Naytra  # noqa: E402
from zoya import Zoya            # noqa: E402

REF = os.environ.get("ZOYA_REF", "a66b1a6f")
PROXY = os.environ.get("ZOYA_PROXY", "").strip()
OUT = "result.json"
STATE = "state.txt"
PLIST = [p.strip() for p in os.environ.get("PROXY_LIST", "").splitlines() if p.strip()]


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def pick_proxy():
    """Sticky proxy per runner: pilih dari PROXY_LIST pakai hash nama job."""
    if PROXY:
        return PROXY
    if not PLIST:
        return ""
    key = os.environ.get("GITHUB_JOB", "") or os.environ.get("GITHUB_RUN_ID", "0")
    idx = sum(map(ord, key)) % len(PLIST)
    return PLIST[idx]


def otp_from_inbox(n, addr, timeout=180):
    start = time.time()
    seen = set()
    while time.time() - start < timeout:
        d = n._get(f"/api/inbox/{addr}")
        for e in (d.get("emails") or []):
            eid = e.get("id")
            if eid in seen:
                continue
            seen.add(eid)
            subj = e.get("subject", "") or ""
            ed = n._get(f"/api/email/{eid}") if eid is not None else {}
            blob = f"{subj}\n{ed.get('body','')}\n{ed.get('body_html','')}"
            m = re.search(r"(?<!\d)(\d{4})(?!\d)", blob)
            if m:
                return m.group(1)
        time.sleep(4)
    return None


def upload_video(z, url, title="Coba Video"):
    """/upload punya jalur POST upload.php (title+url .mp4) -> {vid}."""
    r = z.s.post("https://zoyalink.com/upload.php",
                 data={"title": title, "url": url}, timeout=120)
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:200], "status": r.status_code}


def main():
    px = pick_proxy()
    os.environ["ZOYA_PROXY"] = px
    if px:
        os.environ.setdefault("HTTP_PROXY", px)
        os.environ.setdefault("HTTPS_PROXY", px)

    ip = requests.get("https://ipv4.icanhazip.com", timeout=25).text.strip() if not px else "(proxy)"
    log("proxy:", px or "DIRECT", "| exit-ip:", ip)

    n = Naytra()
    addr = n.create_inbox()
    log("inbox:", addr)

    z = Zoya(ref=REF)
    rec = {"host": "zoyalink.com", "user": addr, "ref": REF, "ts": time.strftime("%F %T")}

    # register — retry kalau SMTP beku (451) / DB flaky
    ok = False
    msg = ""
    for attempt in range(20):
        ok, msg = z.register(addr, name="Budi Santoso",
                             bio="Suka berbagi cerita, foto, dan video harian.")
        m = str(msg)
        if ok:
            break
        if "SMTP" in m or "db_unavailable" in m or "Ratelimit" in m:
            log(f"register attempt {attempt+1}: {m[:70]} — tunggu 30s")
            time.sleep(30)
            continue
        break
    rec["register"] = ok
    if not ok:
        rec["error"] = str(msg)[:200]
        json.dump(rec, open(OUT, "w"), indent=1)
        log("GAGAL register:", str(msg)[:120])
        return 1

    log("OTP menunggu...")
    otp = otp_from_inbox(n, addr)
    if not otp:
        rec["error"] = "OTP tidak masuk"
        json.dump(rec, open(OUT, "w"), indent=1)
        return 2
    log("OTP:", otp)

    v_ok, v_msg = z.verify(otp, addr)
    rec["verify"] = v_ok
    if not v_ok:
        rec["error"] = str(v_msg)[:150]
        json.dump(rec, open(OUT, "w"), indent=1)
        return 3
    log("verify OK")

    r = z.login(addr, z.passwd)
    rec["pass"] = z.passwd
    rec["otp"] = otp
    rec["login_status"] = r.status_code
    rec["session"] = z.s.cookies.get_dict()
    log("login:", r.status_code)

    vid = os.environ.get("ZOYA_VIDEO", "").strip()
    if vid:
        rec["upload"] = upload_video(z, vid)
        log("upload:", rec["upload"])

    json.dump(rec, open(OUT, "w"), indent=1)
    open(STATE, "w").write(json.dumps(rec))
    log("SELESAI", addr, "pw=", z.passwd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
