#!/usr/bin/env python3
"""Probe: apa yang muncul SETELAH OTP diterima di accounts.x.ai?

Tujuan: kalau create-account replay ditolak 401, kita perlu tahu
(a) layar apa yang dirender setelah OTP valid, dan
(b) body request create-account yang dikirim halaman sendiri
    (dengan token Castle/Turnstile yang FRESH, bukan yang sudah terpakai).

Hook window.fetch + XMLHttpRequest dulu, lalu jalankan flow lewat UI.
"""
import asyncio
import json
import time

from camoufox.async_api import AsyncCamoufox
from emailnator_client import Emailnator

SIGNUP = "https://accounts.x.ai/sign-up?redirect=grok-com"

HOOK_JS = """
(() => {
    if (window.__hooked) return;
    window.__hooked = true;
    window.__reqs = [];
    const of = window.fetch;
    window.fetch = async function(...a) {
        try {
            const req = a[0];
            const opt = a[1] || {};
            const url = (typeof req === 'string') ? req : (req && req.url) || '';
            let body = opt.body;
            if (body && typeof body !== 'string') { try { body = JSON.stringify(body); } catch(e){} }
            window.__reqs.push({url: String(url), method: opt.method || 'GET',
                                body: body ? String(body).slice(0, 1200) : null});
        } catch (e) {}
        return of.apply(this, a);
    };
    const oo = XMLHttpRequest.prototype.open;
    const os = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(m, u, ...r) {
        this.__m = m; this.__u = u; return oo.call(this, m, u, ...r);
    };
    XMLHttpRequest.prototype.send = function(b) {
        try {
            window.__reqs.push({url: String(this.__u), method: this.__m,
                                body: b ? String(b).slice(0, 1200) : null});
        } catch (e) {}
        return os.call(this, b);
    };
})();
"""


async def dump(page, label):
    print(f"\n===== {label} =====", flush=True)
    try:
        print("url:", page.url, flush=True)
    except Exception:
        pass
    try:
        body = await page.evaluate("document.body ? document.body.innerText.slice(0,700) : ''")
        print("BODY:", repr(body), flush=True)
    except Exception as e:
        print("body err", e, flush=True)
    try:
        els = await page.evaluate("""JSON.stringify(Array.from(
            document.querySelectorAll('input,button,select,textarea,a[role=button]'))
            .map(e => ({tag: e.tagName, type: e.type||'', name: e.name||'',
                        id: e.id||'', ph: e.placeholder||'',
                        txt: (e.innerText||'').trim().slice(0,40),
                        vis: !!(e.offsetWidth||e.offsetHeight)}))
            .filter(x => x.vis))""")
        print("ELS:", els[:1400], flush=True)
    except Exception as e:
        print("els err", e, flush=True)


async def main():
    mail = Emailnator()
    addr = mail.create_inbox()
    print("inbox:", addr, flush=True)

    cam = AsyncCamoufox(headless=True, humanize=True, block_webrtc=True,
                        locale="en-US")
    await cam.start()
    try:
        page = await cam.browser.new_page()
        await page.add_init_script(HOOK_JS)
        await page.goto(SIGNUP, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(6)
        await dump(page, "1. halaman awal")

        # cookie
        for lbl in ["Accept All Cookies", "Accept all"]:
            try:
                b = page.get_by_role("button", name=lbl).first
                if await b.count():
                    await b.click(timeout=3000)
                    break
            except Exception:
                pass
        await asyncio.sleep(1)

        # sign up with email
        for lbl in ["sign up with email", "continue with email", "use email"]:
            try:
                b = page.get_by_role("button", name=lbl).first
                if await b.count():
                    await b.click(timeout=5000)
                    break
            except Exception:
                pass
        await asyncio.sleep(2)

        for sel in ['input[type="email"]', 'input[name="email"]']:
            try:
                inp = page.locator(sel).first
                if await inp.count() and await inp.is_visible():
                    await inp.fill(addr)
                    break
            except Exception:
                pass
        otp_task = asyncio.ensure_future(
            asyncio.to_thread(mail.wait_otp, addr, 90, time.time()))

        for lbl in ["Sign up", "sign up", "Continue", "Next"]:
            try:
                b = page.get_by_role("button", name=lbl).first
                if await b.count():
                    await b.click(timeout=5000)
                    break
            except Exception:
                pass
        await asyncio.sleep(8)
        await dump(page, "2. setelah submit email")

        code = await otp_task
        print("\nOTP:", code, flush=True)
        if not code:
            print("OTP tidak datang — berhenti", flush=True)
            return

        # isi OTP lewat keyboard asli
        boxes = page.locator('input[maxlength="1"]')
        n = await boxes.count()
        if n >= 6:
            await boxes.nth(0).click(timeout=4000)
            await page.keyboard.type(code, delay=90)
        else:
            for sel in ['input[name="code"]', 'input[inputmode="numeric"]']:
                try:
                    inp = page.locator(sel).first
                    if await inp.count() and await inp.is_visible():
                        await inp.click()
                        await page.keyboard.type(code, delay=90)
                        break
                except Exception:
                    pass
        await asyncio.sleep(1)
        await dump(page, "3. OTP sudah diketik (sebelum confirm)")

        for lbl in ["Confirm email", "Confirm", "Verify", "Continue"]:
            try:
                b = page.get_by_role("button", name=lbl).first
                if await b.count():
                    await b.click(timeout=5000)
                    break
            except Exception:
                pass
        await asyncio.sleep(8)
        await dump(page, "4. SETELAH confirm OTP")

        reqs = await page.evaluate("window.__reqs || []")
        print("\n===== REQUEST BODIES (auth) =====", flush=True)
        for r in (reqs or []):
            u = r.get("url", "")
            if any(k in u for k in ["x.ai", "auth", "sign-up", "verify", "code"]):
                print(f"  {r.get('method')} {u}", flush=True)
                if r.get("body"):
                    print(f"      body: {r['body'][:600]}", flush=True)
    finally:
        try:
            await cam.stop()
        except Exception:
            pass


asyncio.run(main())