#!/usr/bin/env python3
"""proxy_test.py — tes apakah proxy bisa dapetin token Turnstile.

Loop beberapa proxy per runner, stop di sukses pertama.
usage: proxy_test.py URL SHARD
env  : PROXY_LIST (newline-separated host:port)
"""
import sys, os, json, time

URL = sys.argv[1]
SHARD = sys.argv[2] if len(sys.argv) > 2 else "0"
PLIST = [p.strip() for p in os.getenv("PROXY_LIST", "").splitlines() if p.strip()]
OUT = f"px_{SHARD}.jsonl"

# bagi list ke 20 shard
CHUNKS = 20
per = max(1, len(PLIST) // CHUNKS)
chunk = PLIST[int(SHARD) * per: (int(SHARD) + 1) * per] if PLIST else []
print(f"shard={SHARD} proxies={len(chunk)}", flush=True)


def get_token(page, timeout_s=45):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            tok = page.evaluate("""() => {
                const el = document.querySelector('input[name="cf-turnstile-response"]');
                if (el && el.value && el.value.length > 20) return el.value;
                try { if (window.turnstile && window.turnstile.getResponse) {
                        const t = window.turnstile.getResponse(); if (t) return t; } } catch(e){}
                return '';
            }""")
            if tok and len(tok) > 20:
                return tok
        except Exception:
            pass
        time.sleep(1.5)
    return ""


def main():
    from camoufox.sync_api import Camoufox
    for px in chunk:
        pstr = px if px.startswith("http") else "http://" + px
        try:
            with Camoufox(headless=True, humanize=True, proxy={"server": pstr}) as browser:
                page = browser.new_page()
                try:
                    page.goto(URL, wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    print(f"  {px} NAV_FAIL {str(e)[:40]}", flush=True)
                    continue
                time.sleep(4)
                tok = get_token(page, timeout_s=40)
                if tok:
                    print(f"  {px} TOKEN_OK {tok[:24]}", flush=True)
                    open(OUT, "a").write(json.dumps({"proxy": px, "token": tok[:64], "url": URL}) + "\n")
                    return
                print(f"  {px} no_token", flush=True)
        except Exception as e:
            print(f"  {px} ERR {str(e)[:50]}", flush=True)
    print(f"DONE shard={SHARD}", flush=True)


if __name__ == "__main__":
    main()
