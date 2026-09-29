#!/usr/bin/env python3
"""Verifikasi password: login beneran ke accounts.x.ai pakai email+password.

Password yang tercatat di sso.txt bisa salah kalau ada mangling saat submit.
Skrip ini membuktikan: buka sign-in, isi email+password, submit, baca hasil.
"""
import asyncio
import glob
import json
import sys

SIGNIN = "https://accounts.x.ai/sign-in?redirect=grok-com"


async def try_login(page, email, password):
    await page.goto(SIGNIN, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(5)
    # cookie
    for lbl in ["Accept All Cookies", "Accept all"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=2500)
                break
        except Exception:
            pass
    await asyncio.sleep(1)

    # mungkin perlu klik 'Sign in with email'
    for lbl in ["Sign in with email", "sign in with email", "Use email"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=4000)
                await asyncio.sleep(2)
                break
        except Exception:
            pass

    filled_email = False
    for sel in ['input[type="email"]', 'input[name="email"]']:
        try:
            i = page.locator(sel).first
            if await i.count() and await i.is_visible():
                await i.click()
                await page.keyboard.type(email, delay=30)
                filled_email = True
                break
        except Exception:
            pass
    if not filled_email:
        return "NO_EMAIL_FIELD", ""

    # lanjut ke password
    for lbl in ["Continue", "Next", "Sign in", "Continue with email"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=4000)
                await asyncio.sleep(4)
                break
        except Exception:
            pass

    filled_pw = False
    for sel in ['input[type="password"]', 'input[name="password"]']:
        try:
            i = page.locator(sel).first
            if await i.count() and await i.is_visible():
                await i.click()
                await page.keyboard.type(password, delay=40)
                filled_pw = True
                break
        except Exception:
            pass
    if not filled_pw:
        try:
            body = await page.evaluate("document.body ? document.body.innerText.slice(0,400) : ''")
        except Exception:
            body = ""
        return "NO_PASSWORD_FIELD", body

    for lbl in ["Sign in", "Log in", "Continue", "Submit"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=5000)
                await asyncio.sleep(6)
                break
        except Exception:
            pass

    body = await page.evaluate("document.body ? document.body.innerText.slice(0,500) : ''")
    low = (body or "").lower()
    if any(w in low for w in ["incorrect", "invalid", "wrong", "salah"]):
        return "WRONG_PASSWORD", body
    if any(w in low for w in ["verify", "code", "one time", "otp"]):
        return "PASSWORD_OK_NEEDS_OTP", body
    if "sign up with" in low or "create your account" in low:
        return "STILL_ON_LOGIN", body
    # cek session
    try:
        ck = await page.context.cookies()
        has = any(c.get("name") == "sso" for c in ck)
    except Exception:
        has = False
    urls = page.url
    if has or "grok.com" in urls:
        return "LOGIN_OK", body
    return "UNCLEAR", body


async def main():
    from camoufox.async_api import AsyncCamoufox

    # ambil akun dari artefak
    accounts = []
    for f in sorted(glob.glob("grok-farm/../grok-art/*/sso.txt")) + \
             sorted(glob.glob("sso_art/*/sso.txt")) + \
             sorted(glob.glob("*/sso.txt")):
        for line in open(f):
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            accounts.append((j["email"], j["password"]))
    # fallback: dari argumen
    if not accounts and len(sys.argv) > 2:
        accounts = [(sys.argv[1], sys.argv[2])]
    # dedup
    seen = set()
    accounts = [a for a in accounts if not (a[0] in seen or seen.add(a[0]))]

    if not accounts:
        print("tidak ada akun ditemukan", flush=True)
        return
    print(f"menguji {len(accounts)} akun\n", flush=True)

    cam = AsyncCamoufox(headless=True, humanize=True, block_webrtc=True,
                        locale="en-US")
    await cam.start()
    try:
        for email, pw in accounts:
            page = await cam.browser.new_page()
            try:
                res, body = await try_login(page, email, pw)
            except Exception as e:
                res, body = f"ERR {type(e).__name__}", str(e)[:120]
            print(f"  {email:26} pass={pw:22} -> {res}", flush=True)
            if body:
                print(f"      body: {body[:160]!r}", flush=True)
            await page.close()
    finally:
        try:
            await cam.stop()
        except Exception:
            pass


asyncio.run(main())