#!/usr/bin/env python3
"""Tes backend inbox yang domainnya DITERIMA xAI.

Prioritas:
  1) emailnator.com  -> generate @gmail.com (pasti diterima xAI) + API/browser
  2) mail.gw         -> API ala mail.tm (502 dari VPS, cek dari Azure)
  3) mailserver.lol  -> domain 1secmail baru?
  4) pony.gg         -> alias service
"""
import asyncio
import json
import random
import re
import string
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def http(url, method="GET", data=None, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return 0, f"{type(e).__name__}: {str(e)[:130]}"


def rnd(n=12):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


print("=" * 72)
print("1) mail.gw — API ala mail.tm (retry)")
print("=" * 72)
for base in ["https://api.mail.gw", "https://api.mail.gw/v1"]:
    s, t = http(base + "/domains")
    print(f"  GET {base}/domains -> {s} {t[:150]}")
addr = rnd() + "@mail.gw"
pw = "Tg!" + rnd(14)
s, t = http("https://api.mail.gw/accounts", "POST", {"address": addr, "password": pw})
print(f"  POST /accounts -> {s} {t[:200]}")

print()
print("=" * 72)
print("2) mailserver.lol — konfigurasi / API")
print("=" * 72)
for u in ["https://mailserver.lol/api", "https://mailserver.lol/api/domains",
          "https://api.mailserver.lol/domains", "https://mailserver.lol/"]:
    s, t = http(u)
    print(f"  GET {u} -> {s} {t[:130]}")

print()
print("=" * 72)
print("3) pony.gg — alias service")
print("=" * 72)
for u in ["https://pony.gg/api/health", "https://pony.gg/"]:
    s, t = http(u)
    print(f"  GET {u} -> {s} {t[:130]}")

print()
print("=" * 72)
print("4) emailnator.com via BROWSER (Camoufox) — generate @gmail.com")
print("=" * 72)


async def emailnator_browser():
    from camoufox.async_api import AsyncCamoufox
    cam = AsyncCamoufox(headless=True, humanize=True, block_webrtc=True,
                        locale="en-US")
    await cam.start()
    try:
        page = await cam.browser.new_page()
        # intercept API responses
        api_bodies = []

        async def on_resp(r):
            if "emailnator" in r.url and "/api/" in r.url:
                try:
                    api_bodies.append((r.url.split("/api/")[-1][:40], r.status,
                                       (await r.text())[:300]))
                except Exception:
                    pass
        page.on("response", lambda r: asyncio.ensure_future(on_resp(r)))

        await page.goto("https://www.emailnator.com/", wait_until="domcontentloaded",
                        timeout=60000)
        await asyncio.sleep(6)
        print(f"  title: {await page.title()}")
        body = await page.evaluate("document.body ? document.body.innerText.slice(0,600) : ''")
        print(f"  body: {body[:400]!r}")

        # klik tombol generate / copy
        for lbl in ["Generate", "Generate Email", "New Email", "Get Email",
                    "googleMail", "Go"]:
            try:
                b = page.get_by_role("button", name=re.compile(lbl, re.I)).first
                if await b.count():
                    await b.click(timeout=4000)
                    print(f"  clicked: {lbl}")
                    await asyncio.sleep(5)
                    break
            except Exception:
                pass

        # cari email di halaman
        txt = await page.evaluate("document.body.innerText")
        mails = re.findall(r'[\w.\-+]+@[\w.\-]+\.\w+', txt)
        print(f"  email ditemukan: {mails[:5]}")
        for u, st, bd in api_bodies[-6:]:
            print(f"  API {u} -> {st} {bd[:150]}")
    finally:
        try:
            await cam.stop()
        except Exception:
            pass


try:
    asyncio.run(emailnator_browser())
except Exception as e:
    print(f"  browser err: {type(e).__name__}: {str(e)[:200]}")