#!/usr/bin/env python3
"""Probe halaman device consent: dump SEMUA tombol/input/link + teks.

Jangan menebak nama tombol — ambil struktur aslinya dari halaman, termasuk
shadow DOM bila ada (xAI memakai web component pada beberapa form).
"""
import asyncio, glob, json, re, sys

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = ("openid profile email offline_access grok-cli:access api:access "
         "conversations:read conversations:write")
import requests

acct = None
for f in sorted(glob.glob("sso_art/*.txt")):
    acct = json.loads(open(f).read().splitlines()[0]); break
print("akun:", acct["email"])

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/131.0"})
for dom in (".x.ai", "accounts.x.ai", "auth.x.ai", "grok.com"):
    s.cookies.set("sso", acct["sso"], domain=dom, path="/")
r = s.post("https://auth.x.ai/oauth2/device/code",
           data={"client_id": CLIENT_ID, "scope": SCOPE}, timeout=40)
dc = r.json()
print("user_code:", dc.get("user_code"), "url:", dc.get("verification_uri_complete"))

DUMP_JS = """
() => {
  const out = {url: location.href, text: (document.body?document.body.innerText:'').slice(0,900),
               buttons: [], inputs: [], links: []};
  const walk = (root) => {
    root.querySelectorAll('button,[role=button],a[href]').forEach(e => {
      const t = (e.innerText||e.value||e.getAttribute('aria-label')||'').trim().slice(0,60);
      const st = getComputedStyle(e);
      if (t) out.buttons.push({tag:e.tagName, text:t,
        disabled: e.disabled===true,
        vis: st.display!=='none' && st.visibility!=='hidden',
        cls: (e.className||'').toString().slice(0,50),
        type: e.getAttribute('type')||''});
    });
    root.querySelectorAll('input').forEach(e => {
      out.inputs.push({name:e.name||'', type:e.type||'', ph:e.placeholder||'',
                       val:(e.value||'').slice(0,20), vis: getComputedStyle(e).display!=='none'});
    });
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) walk(e.shadowRoot); });
  };
  walk(document);
  return out;
}
"""


async def main():
    from camoufox.async_api import AsyncCamoufox
    cam = AsyncCamoufox(headless=True, humanize=True, block_webrtc=True, locale="en-US")
    await cam.start()
    try:
        ctx = await cam.browser.new_context()
        ck = [{"name": c["name"], "value": c["value"], "domain": c.get("domain"), "path": c.get("path", "/")}
              for c in (acct.get("cookies") or []) if c.get("domain")]
        if ck:
            await ctx.add_cookies(ck)
        page = await ctx.new_page()
        await page.goto(dc["verification_uri_complete"], wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(6)

        for step in range(4):
            d = await page.evaluate(DUMP_JS)
            print(f"\n===== STEP {step} | {d['url'][:80]}")
            print("TEXT:", re.sub(r"\s+", " ", d["text"])[:400])
            print("BUTTONS:")
            for b in d["buttons"]:
                print(f"   [{b['tag']}] {b['text']!r} vis={b['vis']} disabled={b['disabled']} type={b['type']}")
            if d["inputs"]:
                print("INPUTS:", d["inputs"])
            # klik tombol pertama yang terlihat & bukan sign-out
            done = False
            for b in d["buttons"]:
                if b["vis"] and not b["disabled"] and b["text"].lower() not in (
                        "sign out", "cancel", "back", "deny"):
                    try:
                        await page.get_by_role("button", name=re.compile(rf"^{re.escape(b['text'])}$", re.I)).first.click(timeout=5000)
                        print(f"   -> klik {b['text']!r}")
                        done = True
                        break
                    except Exception as e:
                        print(f"   -> gagal klik {b['text']!r}: {type(e).__name__}")
            if not done:
                print("   -> tidak ada tombol yang bisa diklik")
            await asyncio.sleep(5)
        # akhir: cek token
        r = s.post("https://auth.x.ai/oauth2/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": dc["device_code"], "client_id": CLIENT_ID}, timeout=40)
        print("\nTOKEN:", r.status_code, r.text[:200])
    finally:
        try:
            await cam.stop()
        except Exception:
            pass


asyncio.run(main())