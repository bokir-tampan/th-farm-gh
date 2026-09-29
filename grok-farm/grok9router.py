#!/usr/bin/env python3
"""Grok farm -> 9router-ready OAuth token, full device-code chain.

Chain (persis 9r-bulk-add --grok):
  1. warm-up session accounts.x.ai dengan cookie sso (fan-out ke semua domain)
  2. POST auth.x.ai/oauth2/device/code   -> device_code + user_code
  3. buka verification_uri_complete (user_code sudah terisi) dengan cookie sso
  4. klik **Allow** pada halaman consent
  5. poll auth.x.ai/oauth2/token (grant_type=device_code) -> access+refresh token
  6. bukti: GET cli-chat-proxy.grok.com/v1/models dengan Bearer  -> daftar model

Output: grok_oauth.json  [{email, token:{access_token,refresh_token,scope,expires_in}}]
Token inilah yang bisa di-import ke 9router / Hermes sebagai provider grok-cli.
"""
from __future__ import annotations

import asyncio
import glob
import json
import re
import sys
import time

import requests

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = ("openid profile email offline_access grok-cli:access api:access "
         "conversations:read conversations:write")
DEVICE_CODE = "https://auth.x.ai/oauth2/device/code"
TOKEN = "https://auth.x.ai/oauth2/token"
PROXY = "https://cli-chat-proxy.grok.com/v1"
CLIENT_VERSION = "0.2.103"
CLIENT_IDENT = "xai-grok-cli"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def load_accounts():
    out = []
    for pat in ("sso_art/*.txt", "*/sso.txt"):
        for f in sorted(glob.glob(pat)):
            for line in open(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    seen, uniq = set(), []
    for a in out:
        if a.get("email") and a["email"] not in seen:
            seen.add(a["email"]); uniq.append(a)
    return uniq


def http_session(acct):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    sso = acct.get("sso") or ""
    for dom in (".x.ai", "accounts.x.ai", "auth.x.ai", "grok.com"):
        if sso:
            s.cookies.set("sso", sso, domain=dom, path="/")
            s.cookies.set("sso-rw", sso, domain=dom, path="/")
    for c in (acct.get("cookies") or []):
        try:
            s.cookies.set(c["name"], c["value"],
                          domain=c.get("domain", ".x.ai"),
                          path=c.get("path", "/"))
        except Exception:
            pass
    return s


async def click_allow(page, verify_url, log):
    """Jalani dua halaman: /device (Continue) lalu /device/consent (Allow).

    Tombolnya berbeda tiap halaman — jangan berhenti setelah klik pertama
    (bug: 'Continue' ikut ke-klik lalu loop selesai sebelum Allow).
    Selesai bila URL mengandung /device/done.
    """
    await page.goto(verify_url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(5)

    for _ in range(10):
        url = page.url
        if "/device/done" in url:
            log.append("    ✔ device authorized (/done)")
            return True, "done"

        try:
            body = (await page.evaluate(
                "document.body ? document.body.innerText.slice(0,600) : ''")) or ""
        except Exception:
            body = ""
        flat = re.sub(r"\s+", " ", body).strip()
        low = flat.lower()
        log.append(f"    {url.split('?')[0][-34:]} | {flat[:110]!r}")
        if any(w in low for w in ["denied", "not authorized", "not available"]):
            return False, flat

        # pilih label sesuai halaman
        if "/consent" in url:
            labels = ["Allow", "Authorize", "Approve", "Accept"]
        else:
            labels = ["Continue", "Sign in", "Next"]
        clicked = False
        for lbl in labels:
            try:
                b = page.get_by_role("button",
                                     name=re.compile(rf"^{lbl}$", re.I)).first
                if await b.count() and await b.is_visible():
                    await b.click(timeout=6000)
                    log.append(f"    klik '{lbl}'")
                    clicked = True
                    break
            except Exception:
                pass
        # cookie banner
        if not clicked:
            for lbl in ["Accept All Cookies", "Accept all"]:
                try:
                    b = page.get_by_role("button", name=lbl).first
                    if await b.count():
                        await b.click(timeout=2500)
                        clicked = True
                        break
                except Exception:
                    pass
        if not clicked:
            log.append("    (tidak ada tombol)")
        await asyncio.sleep(4)

    return ("/done" in page.url), "timeout"


async def main():
    from camoufox.async_api import AsyncCamoufox

    accounts = load_accounts()
    if len(sys.argv) > 2:
        accounts = [{"email": sys.argv[1], "password": sys.argv[2],
                     "sso": "", "cookies": []}]
    if not accounts:
        print("tidak ada akun", flush=True); return
    import os as _os
    limit = int(_os.environ.get("LIMIT", len(accounts)))
    accounts = accounts[:limit]
    print(f"menguji {len(accounts)} akun\n", flush=True)

    cam = AsyncCamoufox(headless=True, humanize=True, block_webrtc=True,
                        locale="en-US")
    await cam.start()
    out = []
    try:
        for acct in accounts:
            email = acct["email"]
            log = []
            s = http_session(acct)
            try:
                r0 = s.get("https://grok.com/api/auth/session", timeout=25)
                ok_sess = r0.status_code == 200 and "authenticated" in r0.text
            except Exception:
                ok_sess = False
            log.append(f"  session={ok_sess}")

            r = s.post(DEVICE_CODE, data={"client_id": CLIENT_ID, "scope": SCOPE},
                       timeout=40)
            if r.status_code != 200:
                print(f"  ✗ {email:24} device/code {r.status_code} {r.text[:90]}",
                      flush=True)
                continue
            dc = r.json()
            log.append(f"  user_code={dc.get('user_code')}")

            ctx = await cam.browser.new_context()
            # suntik cookie sso supaya halaman consent mengenali akun
            try:
                ck = []
                for c in (acct.get("cookies") or []):
                    if c.get("domain"):
                        ck.append({k: v for k, v in c.items()
                                   if k in ("name", "value", "domain", "path",
                                            "httpOnly", "secure", "sameSite")})
                if not ck and acct.get("sso"):
                    for dom in (".x.ai", "accounts.x.ai"):
                        ck.append({"name": "sso", "value": acct["sso"],
                                   "domain": dom, "path": "/"})
                if ck:
                    await ctx.add_cookies(ck)
            except Exception:
                pass
            page = await ctx.new_page()
            clicked = False
            try:
                clicked, note = await click_allow(
                    page, dc["verification_uri_complete"], log)
            except Exception as e:
                log.append(f"  ERR {type(e).__name__}: {str(e)[:90]}")
            await page.close()
            try:
                await ctx.close()
            except Exception:
                pass

            if not clicked:
                print(f"  ✗ {email:24} consent gagal: {note[:80]}", flush=True)
                for l in log:
                    print("   ", l, flush=True)
                continue

            # poll token
            tok = None
            deadline = time.time() + 40
            while time.time() < deadline:
                tr = s.post(TOKEN, data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": dc["device_code"], "client_id": CLIENT_ID},
                    timeout=40)
                if tr.status_code == 200:
                    tok = tr.json(); break
                if "authorization_pending" not in tr.text and "slow_down" not in tr.text:
                    log.append(f"  token {tr.status_code} {tr.text[:110]}")
                    break
                await asyncio.sleep(3)

            if tok and tok.get("access_token"):
                at = tok["access_token"]
                # bukti akhir: panggil proxy grok-cli
                try:
                    pv = s.get(f"{PROXY}/models", timeout=30, headers={
                        "Authorization": f"Bearer {at}",
                        "x-grok-client-version": CLIENT_VERSION,
                        "x-grok-client-identifier": CLIENT_IDENT,
                        "User-Agent": "xai-grok-cli",
                        "X-XAI-Token-Auth": "xai-grok-cli",
                    })
                    proof = f"proxy/models {pv.status_code} {pv.text[:90]}"
                except Exception as e:
                    proof = f"proxy ERR {type(e).__name__}"
                print(f"  ✓ {email:24} TOKEN OK scope={tok.get('scope','')[:60]}",
                      flush=True)
                print(f"      {proof}", flush=True)
                out.append({"email": email, "password": acct.get("password"),
                            "token": tok, "proof": proof})
            else:
                print(f"  ~ {email:24} consent ok tapi token tidak keluar", flush=True)
                for l in log:
                    print("   ", l, flush=True)
    finally:
        try:
            await cam.stop()
        except Exception:
            pass

    if out:
        json.dump(out, open("grok_oauth.json", "w"), indent=2)
        print(f"\n>>> {len(out)} token -> grok_oauth.json", flush=True)
    else:
        print("\n>>> tidak ada token", flush=True)


asyncio.run(main())