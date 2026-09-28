#!/usr/bin/env python3
"""
TokenTable farm via Camoufox (jalan di GitHub runner: RAM besar + IP fresh).

Alur:
  1. Buka /en/chat → tunggu widget Cloudflare Turnstile auto-solve
  2. Ambil token dari input[name=cf-turnstile-response]
  3. Register via fetch SAME-ORIGIN di dalam page (cookie + header natural)
  4. Login → generate API key
  5. Print  email:password:apikey  ke akun_full.txt

Usage: python3 tt_gh_farm.py [N]     (N = jumlah akun, default 1)
"""
import sys, os, time, json, random, string, re

from camoufox.sync_api import Camoufox

BASE = "https://tokentable.asia"
CHAT = BASE + "/en/chat"
OUT = "akun_full.txt"


def rnd_email():
    """Email acak — pakai domain yang tidak diblokir (gmail/outlook)."""
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    dom = random.choice(["gmail.com", "outlook.com", "yahoo.com", "hotmail.com"])
    return f"{tag}@{dom}"


def rnd_password():
    return "Tt!" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "#26"


def solve_turnstile(page, timeout=150):
    """Tunggu token Turnstile terisi otomatis. Return token atau None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            tok = page.evaluate(
                "(document.querySelector('[name=cf-turnstile-response]')||{}).value||''")
            if tok and len(tok) > 40:
                return tok
        except Exception as e:
            print(f"   [warn] eval: {str(e)[:80]}", flush=True)
        time.sleep(3)
    return None


def js_fetch(page, path, payload, method="POST"):
    """fetch same-origin di dalam page — pakai cookie + header browser asli."""
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
    }
    """
    return page.evaluate(expr, [path, method, payload])


def farm_one(headless=True):
    email = rnd_email()
    password = rnd_password()
    print(f"[*] akun target: {email}", flush=True)

    with Camoufox(headless=headless, humanize=True) as browser:
        page = browser.new_page()
        print("[1] buka /en/chat ...", flush=True)
        page.goto(CHAT, wait_until="domcontentloaded", timeout=120000)
        time.sleep(6)

        # cek widget turnstile ada
        n = page.evaluate("document.querySelectorAll('[name=cf-turnstile-response]').length")
        print(f"    widget turnstile: {n}", flush=True)
        if not n:
            # coba klik tombol untuk munculin form
            for lbl in ["Get Started Free", "Sign In", "Start Free", "Get Started"]:
                try:
                    page.get_by_text(lbl, exact=False).first.click(timeout=4000)
                    time.sleep(4)
                    if page.evaluate("document.querySelectorAll('[name=cf-turnstile-response]').length"):
                        break
                except Exception:
                    pass
            n = page.evaluate("document.querySelectorAll('[name=cf-turnstile-response]').length")
            print(f"    widget turnstile (setelah klik): {n}", flush=True)

        print("[2] tunggu Turnstile auto-solve (max 150s) ...", flush=True)
        token = solve_turnstile(page)
        if not token:
            print("    [!] token kosong — Turnstile tidak auto-solve", flush=True)
            return None
        print(f"    token OK ({len(token)} chars): {token[:40]}...", flush=True)

        print("[3] register ...", flush=True)
        r = js_fetch(page, "/auth/register", {
            "email": email, "password": password,
            "name": email.split("@")[0], "turnstileToken": token,
        })
        print(f"    -> {r['status']}: {r['text'][:300]}", flush=True)

        if r["status"] not in (200, 201):
            # coba path alternatif
            r = js_fetch(page, "/api/auth/register", {
                "email": email, "password": password,
                "name": email.split("@")[0], "turnstileToken": token,
            })
            print(f"    alt -> {r['status']}: {r['text'][:300]}", flush=True)
            if r["status"] not in (200, 201):
                return None

        print("[4] login ...", flush=True)
        rl = js_fetch(page, "/auth/login", {"email": email, "password": password})
        print(f"    -> {rl['status']}: {rl['text'][:250]}", flush=True)

        print("[5] generate api key ...", flush=True)
        key = None
        for ep in ["/api/account/apikey", "/api/account/api-key", "/api/keys"]:
            rk = js_fetch(page, ep, {"name": "farm"})
            print(f"    {ep} -> {rk['status']}: {rk['text'][:250]}", flush=True)
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
        if key:
            print(f"    KEY: {key[:20]}...", flush=True)
        else:
            print("    [!] api key tidak didapat", flush=True)

        line = f"{email}:{password}:{key or ''}"
        with open(OUT, "a") as f:
            f.write(line + "\n")
        print(f"[✓] {line}", flush=True)
        return line


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    headless = os.environ.get("HEADLESS", "1") == "1"
    ok = 0
    for i in range(N):
        print(f"\n===== akun {i+1}/{N} =====", flush=True)
        try:
            if farm_one(headless=headless):
                ok += 1
        except Exception as e:
            print(f"[!] error: {str(e)[:200]}", flush=True)
        if i < N - 1:
            time.sleep(random.randint(5, 12))
    print(f"\n=== HASIL: {ok}/{N} sukses ===", flush=True)


if __name__ == "__main__":
    main()