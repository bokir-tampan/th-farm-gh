#!/usr/bin/env python3
"""
TokenTable farm via Camoufox (GitHub runner: RAM besar + IP fresh).

Alur:
  1. Buka /en/chat
  2. Buka modal auth (klik Sign In / Get Started Free) supaya widget Turnstile VISIBLE
  3. Tunggu Turnstile auto-solve; kalau perlu, klik widget (mode managed)
  4. Register via fetch same-origin di dalam page
  5. Login → generate API key
  6. Tulis  email:password:apikey  ke akun_full.txt

Usage: python3 tt_gh_farm.py [N]
"""
import sys, os, time, json, random, string, re

from camoufox.sync_api import Camoufox

BASE = "https://tokentable.asia"
CHAT = BASE + "/en/chat"
OUT = "akun_full.txt"

SEL_INPUT = "[name=cf-turnstile-response]"


def rnd_email():
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    dom = random.choice(["gmail.com", "outlook.com", "yahoo.com", "hotmail.com"])
    return f"{tag}@{dom}"


def rnd_password():
    return "Tt!" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "#26"


def widget_info(page):
    """Return dict: count, visible, rect."""
    return page.evaluate("""() => {
      const els = [...document.querySelectorAll('*')].filter(e => /cf-turnstile/.test(e.className||''));
      const inp = document.querySelector('[name=cf-turnstile-response]');
      let r = null, vis = false;
      const target = els[0] || (inp ? inp.parentElement : null);
      if (target) {
        const b = target.getBoundingClientRect();
        r = {x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height)};
        vis = !!(target.offsetParent !== null) && b.width > 0 && b.height > 0;
      }
      return {count: els.length, hasInput: !!inp, visible: vis, rect: r};
    }""")


def token_now(page):
    try:
        return page.evaluate(
            f"(document.querySelector('{SEL_INPUT}')||{{}}).value||''")
    except Exception:
        return ""


def open_auth_modal(page):
    """Klik CTA supaya form auth + Turnstile kebuka (visible)."""
    # tutup overlay cookie kalau ada
    try:
        page.evaluate("""() => {
          document.querySelectorAll('div,iframe').forEach(e=>{
            const t=((e.id||'')+' '+(e.className||'')).toLowerCase();
            if(/cookie|consent|gdpr|privacy/.test(t)){try{e.style.display='none';}catch(_){}}
          });
        }""")
    except Exception:
        pass

    clickables = page.evaluate("""() => {
      const out=[];
      document.querySelectorAll('button,a,[role=button]').forEach(e=>{
        const t=(e.innerText||'').trim().replace(/\\s+/g,' ');
        if(t && t.length<40){
          const b=e.getBoundingClientRect();
          out.push({t, x:Math.round(b.x+b.width/2), y:Math.round(b.y+b.height/2)});
        }
      });
      return out;
    }""")

    wanted = [c for c in clickables
              if re.search(r"get started free|sign in|start free|get started|sign up|signup",
                           c["t"], re.I)]
    print(f"    kandidat CTA: {[c['t'] for c in wanted][:8]}", flush=True)

    for c in wanted:
        try:
            page.mouse.move(c["x"], c["y"], steps=random.randint(8, 20))
            time.sleep(random.uniform(0.3, 0.9))
            page.mouse.click(c["x"], c["y"])
            time.sleep(4)
            info = widget_info(page)
            if info["visible"] or info["hasInput"]:
                print(f"    klik '{c['t']}' -> widget visible={info['visible']}", flush=True)
                return True
        except Exception as e:
            print(f"    klik err: {str(e)[:80]}", flush=True)
    return False


def solve_turnstile(page, timeout=180):
    """Tunggu token; kalau mandek, klik widget (managed mode)."""
    start = time.time()
    clicked = False
    while time.time() - start < timeout:
        tok = token_now(page)
        if len(tok) > 40:
            return tok
        info = widget_info(page)
        elapsed = time.time() - start
        print(f"    t={elapsed:.0f}s vis={info['visible']} rect={info['rect']} len={len(tok)}", flush=True)

        # klik widget sekali setelah 20s (mode managed butuh interaksi)
        if not clicked and elapsed > 20 and info["rect"]:
            r = info["rect"]
            try:
                cx, cy = r["x"] + 30, r["y"] + r["h"] // 2
                print(f"    coba klik widget di ({cx},{cy})", flush=True)
                page.mouse.move(cx - 80, cy - 40, steps=25)
                time.sleep(random.uniform(0.4, 1.0))
                page.mouse.move(cx, cy, steps=18)
                time.sleep(random.uniform(0.2, 0.6))
                page.mouse.click(cx, cy)
                clicked = True
            except Exception as e:
                print(f"    klik widget err: {str(e)[:80]}", flush=True)
        time.sleep(3)
    return ""


def js_fetch(page, path, payload, method="POST"):
    expr = """
    async ([path, method, payload]) => {
      try {
        const r = await fetch(path, {
          method: method,
          headers: {'Content-Type': 'application/json'},
          body: payload ? JSON.stringify(payload) : undefined,
          credentials: 'include'
        });
        const text = await r.text();
        return {status: r.status, text: text.slice(0, 1200)};
      } catch (e) {
        return {status: -1, text: String(e).slice(0, 300)};
      }
    }"""
    return page.evaluate(expr, [path, method, payload])


def farm_one(headless=True, keep_open=False):
    email = rnd_email()
    password = rnd_password()
    print(f"[*] target: {email}", flush=True)

    with Camoufox(headless=headless, humanize=True) as browser:
        page = browser.new_page()
        print("[1] buka /en/chat ...", flush=True)
        page.goto(CHAT, wait_until="domcontentloaded", timeout=120000)
        time.sleep(6)

        print("[2] buka modal auth ...", flush=True)
        open_auth_modal(page)
        time.sleep(3)
        info = widget_info(page)
        print(f"    widget: {info}", flush=True)
        if not info["hasInput"]:
            print("    [!] input turnstile tidak ada", flush=True)
            if keep_open:
                time.sleep(600)
            return None

        print("[3] tunggu Turnstile ...", flush=True)
        token = solve_turnstile(page)
        if not token:
            print("    [!] token kosong", flush=True)
            try:
                open("/tmp/tt_debug.html", "w").write(page.content())
            except Exception:
                pass
            if keep_open:
                time.sleep(600)
            return None
        print(f"    TOKEN OK ({len(token)}) {token[:40]}...", flush=True)

        print("[4] register ...", flush=True)
        r = js_fetch(page, "/auth/register", {
            "email": email, "password": password,
            "name": email.split("@")[0], "turnstileToken": token,
        })
        print(f"    -> {r['status']}: {r['text'][:300]}", flush=True)

        if r["status"] not in (200, 201):
            r2 = js_fetch(page, "/auth/register", {
                "email": email, "password": password, "name": email.split("@")[0],
                "turnstileToken": token, "captchaToken": token,
            })
            print(f"    retry -> {r2['status']}: {r2['text'][:300]}", flush=True)
            if r2["status"] not in (200, 201):
                return None

        print("[5] login ...", flush=True)
        rl = js_fetch(page, "/auth/login", {"email": email, "password": password})
        print(f"    -> {rl['status']}: {rl['text'][:250]}", flush=True)

        print("[6] api key ...", flush=True)
        key = None
        for ep, body in [("/api/account/apikey", {"name": "farm"}),
                         ("/api/account/api-key", {"name": "farm"}),
                         ("/api/keys", {"name": "farm"})]:
            rk = js_fetch(page, ep, body)
            print(f"    {ep} -> {rk['status']}: {rk['text'][:220]}", flush=True)
            if rk["status"] in (200, 201):
                try:
                    d = json.loads(rk["text"])
                    key = (d.get("key") or d.get("apiKey") or d.get("api_key")
                           or (d.get("data") or {}).get("key"))
                except Exception:
                    m = re.search(r'(tt[-_][A-Za-z0-9]{16,}|sk[-_][A-Za-z0-9]{16,})', rk["text"])
                    if m:
                        key = m.group(1)
                if key:
                    break

        line = f"{email}:{password}:{key or ''}"
        with open(OUT, "a") as f:
            f.write(line + "\n")
        print(f"[✓] {line}", flush=True)
        return line


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    headless = os.environ.get("HEADLESS", "1") == "1"
    keep = os.environ.get("KEEP_OPEN", "0") == "1"
    ok = 0
    for i in range(N):
        print(f"\n===== akun {i+1}/{N} =====", flush=True)
        try:
            if farm_one(headless=headless, keep_open=keep):
                ok += 1
        except Exception as e:
            print(f"[!] error: {str(e)[:250]}", flush=True)
        if i < N - 1:
            time.sleep(random.randint(5, 12))
    print(f"\n=== HASIL: {ok}/{N} sukses ===", flush=True)


if __name__ == "__main__":
    main()