#!/usr/bin/env python3
"""Konversi akun Grok (email+password) -> OAuth token via flow Grok CLI.

Kenapa: URL sign-in yang dipakai Grok CLI membawa scope `api:access` dan
`grok-cli:access`, redirect ke 127.0.0.1:<port>/callback (PKCE). Kita:

  1. Bikin pasangan PKCE sendiri (verifier + challenge); client_id publik,
     jadi verifier milik CLI tidak diperlukan.
  2. Jalankan authorize di browser: login email+password (+OTP bila diminta).
  3. Redirect ke http://127.0.0.1:<port>/callback?code=... GAGAL konek
     (tidak ada server di sana) — tapi URL-nya tertangkap, jadi `code` kita
     dapat tanpa menjalankan server callback.
  4. Tukar code -> access_token + refresh_token di endpoint token xAI.

Output per akun: {email, access_token, refresh_token, expires_in, scope}.
Token inilah yang dipakai grok-cli / 9Router, dan yang menentukan apakah
password memang benar.
"""
from __future__ import annotations

import asyncio
import base64
import glob
import hashlib
import json
import os
import re
import secrets
import sys
import urllib.parse

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
REDIRECT = "http://127.0.0.1:56121/callback"
SCOPES = "openid profile email offline_access grok-cli:access api:access"
AUTHORIZE = "https://accounts.x.ai/oauth2/authorize"
TOKEN_URLS = [
    "https://accounts.x.ai/oauth2/token",
    "https://auth.x.ai/oauth2/token",
    "https://accounts.x.ai/api/oauth2/token",
]


def pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def authorize_url(verifier, challenge):
    q = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "scope": SCOPES,
        "state": secrets.token_urlsafe(24),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "nonce": secrets.token_hex(16),
        "referrer": "cli-proxy-api",
        "plan": "generic",
        "email": "true",
    }
    return AUTHORIZE + "?" + urllib.parse.urlencode(q), q["state"]


async def login_and_capture(page, email, password, state, timeout=180,
                            skip_login=False):
    """Login lalu tangkap ?code= dari redirect ke 127.0.0.1."""
    captured = {"code": None, "url": None}

    # Tangkap redirect ke 127.0.0.1/callback?code=... lewat event REQUEST
    # (sinkron, tidak balapan dengan teardown frame seperti framenavigated,
    # yang bikin crash 'Cannot read properties of undefined').
    def _on_req(req):
        try:
            u = req.url
        except Exception:
            return
        if "127.0.0.1" in u or "/callback" in u:
            m = re.search(r'[?&]code=([^&]+)', u)
            if m and not captured["code"]:
                captured["code"] = urllib.parse.unquote(m.group(1))
                captured["url"] = u[:300]

    page.on("request", _on_req)
    page.on("response", lambda r: _on_req(r.request))

    await asyncio.sleep(4)

    # Cookie SSO sudah disuntik: halaman authorize idealnya langsung
    # redirect ke 127.0.0.1/callback. Tunggu sebentar; kalau code muncul,
    # tidak perlu login sama sekali.
    if skip_login:
        t0 = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - t0 < 12:
            if captured["code"]:
                return captured["code"], "ok (cookie)"
            await asyncio.sleep(1)

    for lbl in ["Accept All Cookies", "Accept all"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=2500)
                break
        except Exception:
            pass

    # Halaman sign-in OAuth menampilkan PILIHAN dulu (X / email / Apple /
    # Google / GitHub). Tanpa klik 'Sign in with email' tidak ada field
    # email sama sekali -> itu penyebab 'no email field'.
    for lbl in ["Sign in with email", "sign in with email",
                "Sign up with email", "Use email", "Continue with email",
                "Sign in with a different method", "Email"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count() and await b.is_visible():
                await b.click(timeout=4000)
                await asyncio.sleep(2.5)
                break
        except Exception:
            pass
    # fallback: klik teks apa pun yang memuat 'email'
    if not captured["code"]:
        try:
            el = page.get_by_text(re.compile(r"with email", re.I)).first
            if await el.count():
                await el.click(timeout=4000)
                await asyncio.sleep(2.5)
        except Exception:
            pass

    # form email
    got_email = False
    for sel in ['input[type="email"]', 'input[name="email"]',
                'input[autocomplete="email"]']:
        try:
            i = page.locator(sel).first
            if await i.count() and await i.is_visible():
                await i.click()
                await page.keyboard.type(email, delay=25)
                got_email = True
                break
        except Exception:
            pass
    if not got_email:
        try:
            dbg = await page.evaluate("document.body ? document.body.innerText.slice(0,300) : ''")
        except Exception:
            dbg = ""
        return None, f"no email field; url={page.url[:140]} body={dbg[:140]!r}"
    for lbl in ["Continue", "Next", "Sign in", "Continue with email"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=4000)
                await asyncio.sleep(3)
                break
        except Exception:
            pass

    # form password (bisa jadi sudah muncul sekaligus)
    for sel in ['input[type="password"]', 'input[name="password"]']:
        try:
            i = page.locator(sel).first
            if await i.count() and await i.is_visible():
                await i.click()
                await page.keyboard.type(password, delay=35)
                break
        except Exception:
            pass
    for lbl in ["Sign in", "Log in", "Continue", "Submit"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=5000)
                await asyncio.sleep(4)
                break
        except Exception:
            pass

    # tunggu code / OTP / error
    t0 = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - t0 < 30:
        if captured["code"]:
            return captured["code"], "ok"
        body = ""
        try:
            body = (await page.evaluate(
                "document.body ? document.body.innerText.slice(0,400) : ''")) or ""
        except Exception:
            pass
        low = body.lower()
        if any(w in low for w in ["incorrect", "invalid", "wrong", "salah"]):
            return None, f"BAD_PASSWORD: {body[:150]!r}"
        await asyncio.sleep(2)

    try:
        body = await page.evaluate("document.body ? document.body.innerText.slice(0,400) : ''")
    except Exception:
        body = ""
    return None, f"no code; url={page.url[:160]} body={body[:150]!r}"


def exchange(code, verifier):
    import urllib.request
    last = None
    for url in TOKEN_URLS:
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "grok-cli/0.1",
        })
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = (e.code, e.read().decode()[:300])
        except Exception as e:
            last = (0, f"{type(e).__name__}: {str(e)[:150]}")
    return last


async def main():
    from camoufox.async_api import AsyncCamoufox

    accounts = []
    for pat in ("sso_art/*.txt", "*/sso.txt"):
        for f in sorted(glob.glob(pat)):
            for line in open(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                accounts.append((j["email"], j["password"], j.get("cookies") or []))
    if len(sys.argv) > 2:
        accounts = [(sys.argv[1], sys.argv[2], [])]
    seen = set()
    accounts = [a for a in accounts if not (a[0] in seen or seen.add(a[0]))]
    if not accounts:
        print("tidak ada akun", flush=True)
        return
    print(f"menguji {len(accounts)} akun\n", flush=True)

    cam = AsyncCamoufox(headless=True, humanize=True, block_webrtc=True,
                        locale="en-US")
    await cam.start()
    out = []
    try:
        for email, pw, ck_list in accounts:
            verifier, challenge = pkce()
            url, state = authorize_url(verifier, challenge)
            ctx = await cam.browser.new_context()
            # Jalur utama: suntik cookie SSO yang sudah ada -> authorize
            # langsung mengembalikan code tanpa login ulang.
            injected = False
            if ck_list:
                try:
                    fixed = []
                    for c in ck_list:
                        c = dict(c)
                        c.pop("expires", None) if c.get("expires") is None else None
                        if not c.get("domain"):
                            continue
                        fixed.append({k: v for k, v in c.items()
                                      if k in ("name", "value", "domain",
                                               "path", "httpOnly", "secure",
                                               "sameSite")})
                    await ctx.add_cookies(fixed)
                    injected = True
                except Exception as e:
                    print(f"  ! {email} cookie gagal disuntik: {str(e)[:90]}", flush=True)
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if injected:
                    code, note = await login_and_capture(page, email, pw, state,
                                                         skip_login=True)
                else:
                    code, note = await login_and_capture(page, email, pw, state)
                if code:
                    st, tok = exchange(code, verifier)
                    if st == 200 and isinstance(tok, dict) and tok.get("access_token"):
                        print(f"  ✓ {email:26} TOKEN OK scope={tok.get('scope','')}",
                              flush=True)
                        out.append({"email": email, "password": pw, "token": tok})
                    else:
                        print(f"  ~ {email:26} code OK, tukar gagal: {st} {str(tok)[:140]}",
                              flush=True)
                else:
                    print(f"  ✗ {email:26} {note}", flush=True)
            except Exception as e:
                print(f"  ✗ {email:26} ERR {type(e).__name__}: {str(e)[:120]}",
                      flush=True)
            await page.close()
            try:
                await ctx.close()
            except Exception:
                pass
        if out:
            with open("grok_oauth.json", "w") as fh:
                json.dump(out, fh, indent=2)
            print(f"\n>>> {len(out)} token disimpan ke grok_oauth.json", flush=True)
    finally:
        try:
            await cam.stop()
        except Exception:
            pass


asyncio.run(main())