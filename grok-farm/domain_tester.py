#!/usr/bin/env python3
"""Tes banyak domain tempmail ke xAI sekaligus — cari yang DITERIMA.

Untuk tiap domain: buka sign-up, isi email, submit, baca respons
send-verification-code. Domain yang lolos = tidak muncul 'email is invalid'.

Output: hasil per domain + file domain_ok.txt
"""
import asyncio, json, random, string, sys, time
from camoufox.async_api import AsyncCamoufox

SIGNUP = "https://accounts.x.ai/sign-up?redirect=grok-com"
SEND = "send-verification-code"

DOMAINS = [
    # niche / lama / jarang dipakai
    "mailnesia.com", "spam4.me", "grr.la", "mailcatch.com", "dispostable.com",
    "mailnull.com", "trbvm.com", "mailmetrash.com", "fakeinbox.com", "moakt.com",
    "emailondeck.com", "tempinbox.xyz", "mailtemp.info", "email-temp.com",
    "emailfake.com", "tempr.email", "discard.email", "mailsac.com",
    "zippymail.info", "throwam.com", "inboxkitten.com", "mohmal.com",
    "tempmail.plus", "temp-mail.io", "mail7.io", "harakirimail.com",
    "vomoto.com", "burnermail.io", "33mail.com", "anonbox.net",
    # guerrillamail family
    "sharklasers.com", "guerrillamail.info", "guerrillamail.biz",
    "guerrillamail.de", "guerrillamail.net", "guerrillamail.org",
    # 1secmail family
    "1secmail.com", "1secmail.net", "1secmail.org", "1secmail.xyz",
    "icloudmail.club", "dns4u.fun", "dns4u.online",
    # lain
    "mailbox.org", "disroot.org", "vmail.me", "spamgourmet.com",
    "yopmail.fr", "yopmail.net", "cool.fr.nf", "jetable.fr.nf",
]


def rnd_addr(dom):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)) + "@" + dom


async def probe(page, dom, resp_log):
    """Isi email dom, submit, return (ok, detail)."""
    addr = rnd_addr(dom)
    resp_log.clear()

    # balik ke form awal
    try:
        await page.goto(SIGNUP, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        return None, f"goto err {str(e)[:60]}"
    await asyncio.sleep(3)

    # dismiss cookie
    for lbl in ["Accept All Cookies", "Accept all", "Allow all"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=2500); break
        except Exception:
            pass

    # klik signup with email
    clicked = False
    for lbl in ["sign up with email", "continue with email", "use email"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=4000); clicked = True; break
        except Exception:
            try:
                el = page.get_by_text(lbl, exact=False).first
                if await el.count():
                    await el.click(timeout=4000); clicked = True; break
            except Exception:
                pass
    if not clicked:
        return None, "no email-signup btn"
    await asyncio.sleep(2)

    # isi email
    filled = False
    for sel in ['input[type="email"]', 'input[name="email"]', 'input[autocomplete="email"]']:
        try:
            inp = page.locator(sel).first
            if await inp.count() and await inp.is_visible():
                await inp.fill(addr); filled = True; break
        except Exception:
            pass
    if not filled:
        return None, "no email input"

    # submit
    for lbl in ["sign up", "continue", "next"]:
        try:
            b = page.get_by_role("button", name=lbl).first
            if await b.count():
                await b.click(timeout=4000); break
        except Exception:
            pass
    await asyncio.sleep(7)

    body = ""
    try:
        body = await page.evaluate("document.body ? document.body.innerText : ''") or ""
    except Exception as e:
        return None, f"eval err {str(e)[:50]}"

    low = body.lower()
    if any(w in low for w in ["invalid", "different email", "not valid", "tidak valid"]):
        return False, "REJECTED"
    if any(w in low for w in ["code", "verification", "we sent", "check your email",
                              "we emailed", "sent to"]):
        return True, f"ACCEPTED: {body[:80]!r}"
    return None, f"UNCLEAR: {body[:120]!r}"


async def main():
    domains = DOMAINS
    if len(sys.argv) > 1:
        domains = sys.argv[1:]
    cam = AsyncCamoufox(headless=True, humanize=True, block_webrtc=True, locale="en-US")
    await cam.start()
    browser = cam.browser
    ctx = await browser.new_context()
    page = await ctx.new_page()

    # log respons send-verification-code
    resp_log = []
    async def on_resp(resp):
        if SEND in resp.url:
            try:
                t = await resp.text()
                resp_log.append({"status": resp.status, "body": t[:300]})
            except Exception:
                pass
    page.on("response", lambda r: asyncio.ensure_future(on_resp(r)))

    ok, bad, unk = [], [], []
    try:
        for i, dom in enumerate(domains):
            print(f"\n[{i+1}/{len(domains)}] {dom}", flush=True)
            try:
                res, detail = await probe(page, dom, resp_log)
            except Exception as e:
                res, detail = None, f"err {type(e).__name__}: {str(e)[:70]}"
            if resp_log:
                print(f"    resp: {resp_log[-1]}", flush=True)
            print(f"    -> {res} | {detail}", flush=True)
            if res is True:
                ok.append(dom)
            elif res is False:
                bad.append(dom)
            else:
                unk.append(dom)
            await asyncio.sleep(2)

        print("\n" + "="*60, flush=True)
        print(f"ACCEPTED ({len(ok)}): {ok}", flush=True)
        print(f"REJECTED ({len(bad)}): {bad}", flush=True)
        print(f"UNCLEAR ({len(unk)}): {unk}", flush=True)
        if ok:
            open("domain_ok.txt", "w").write("\n".join(ok) + "\n")
            print("\n>>> ditulis ke domain_ok.txt", flush=True)
    finally:
        try: await cam.stop()
        except Exception: pass


asyncio.run(main())