#!/usr/bin/env python3
"""Probe emailnator: SEMUA tipe generate + opsi domain yang tersedia.

Kalau ada jalur ke @gmail.com, itu jackpot: otomatis, gratis, dan
xAI pasti menerima gmail.com.
"""
import asyncio
import json


async def main():
    from camoufox.async_api import AsyncCamoufox
    cam = AsyncCamoufox(headless=True, humanize=True, block_webrtc=True,
                        locale="en-US")
    await cam.start()
    try:
        page = await cam.browser.new_page()
        await page.goto("https://www.emailnator.com/", wait_until="domcontentloaded",
                        timeout=60000)
        await asyncio.sleep(5)

        async def api(path, payload, method="POST"):
            return await page.evaluate(
                """async ([p, body, meth]) => {
                    const opt = {method: meth, headers: {'Content-Type': 'application/json'},
                                 credentials: 'include'};
                    if (meth !== 'GET') opt.body = JSON.stringify(body);
                    const r = await fetch('https://www.emailnator.com' + p, opt);
                    return {status: r.status, body: (await r.text()).slice(0, 2000)};
                }""", [path, payload, method])

        print("=== getEmailOption ===")
        for m in ("GET", "POST"):
            r = await api("/api/getEmailOption", {}, m)
            print(f"  {m}: {r['status']} {r['body'][:600]}")

        print("\n=== generate-email per TIPE ===")
        for t in ["domain", "plusGmail", "dotGmail", "googleMail"]:
            r = await api("/api/generate-email", {"email": [t]})
            print(f"  [{t}] -> {r['status']} {r['body'][:300]}")

        print("\n=== generate SEMUA sekaligus ===")
        r = await api("/api/generate-email",
                      {"email": ["domain", "plusGmail", "dotGmail", "googleMail"]})
        print(f"  {r['status']} {r['body'][:400]}")

        print("\n=== DOM: opsi yang terlihat user ===")
        txt = await page.evaluate("document.body ? document.body.innerText.slice(0,1200) : ''")
        print(txt[:1000])
    finally:
        try:
            await cam.stop()
        except Exception:
            pass


asyncio.run(main())