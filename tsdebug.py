#!/usr/bin/env python3
"""tsdebug.py — buka /sign-up satu host, dump info form + turnstile + screenshot."""
import asyncio, sys, json

BASE = sys.argv[1].rstrip("/")


async def main():
    from camoufox.async_api import AsyncCamoufox
    out = {"base": BASE, "steps": []}
    async with AsyncCamoufox(headless=True, humanize=True) as cam:
        page = await cam.new_page()
        await page.goto(BASE + "/sign-up", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)
        out["url"] = page.url
        out["title"] = await page.title()
        # all inputs
        out["inputs"] = await page.eval_on_selector_all(
            "input,select,textarea",
            "els=>els.map(e=>({tag:e.tagName,name:e.name,type:e.type,id:e.id,ph:e.placeholder,vis:e.offsetParent!==null}))")
        # buttons
        out["buttons"] = await page.eval_on_selector_all(
            "button,a[role=button],button[type=submit]",
            "els=>els.map(e=>({txt:(e.innerText||'').slice(0,40),type:e.type,vis:e.offsetParent!==null}))")
        # turnstile
        out["turnstile"] = await page.evaluate(
            """()=>{
              const resp=document.querySelector('[name=cf-turnstile-response]');
              const ifr=[...document.querySelectorAll('iframe')].map(f=>f.src.slice(0,90));
              const ts=[...document.querySelectorAll('*')].filter(e=>e.className&&String(e.className).match(/turnstile/i)).map(e=>String(e.className).slice(0,60));
              return {hasResp:!!resp, respVal:resp?resp.value.slice(0,20):null, frames:ifr, tsNodes:ts.slice(0,5)};
            }""")
        # text
        try:
            out["text"] = (await page.inner_text("body"))[:600]
        except Exception:
            out["text"] = ""
        await page.screenshot(path="/tmp/tsdebug.png", full_page=True)
        print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])

asyncio.run(main())
