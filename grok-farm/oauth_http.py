#!/usr/bin/env python3
"""Konversi akun Grok -> OAuth token via cookie SSO, TANPA browser.

Semua data yang dibutuhkan sudah ada di sso.txt: cookie `sso` (+ cf_clearance
untuk lolos Cloudflare). Alurnya cuma ikut redirect:

    GET /oauth2/authorize?...  (bawa cookie sso)
      -> 302/303 ke <redirect_uri>?code=...   (gagal konek 127.0.0.1, tak perlu)
      -> kita cukup baca Location header untuk mengambil `code`.

Lalu tukar code -> token di /oauth2/token.

Jauh lebih cepat daripada browser: ~2 detik/akun vs ~50 detik.
"""
from __future__ import annotations

import base64
import glob
import hashlib
import json
import re
import secrets
import sys
import urllib.parse

import requests

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
REDIRECT = "http://127.0.0.1:56121/callback"
SCOPES = "openid profile email offline_access grok-cli:access api:access"
AUTHORIZE = "https://accounts.x.ai/oauth2/authorize"
TOKEN_URLS = [
    "https://accounts.x.ai/oauth2/token",
    "https://auth.x.ai/oauth2/token",
    "https://accounts.x.ai/api/oauth2/token",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def pkce():
    v = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    return v, c


def to_cookiejar(cookie_list, fallback_sso=None):
    jar = requests.cookies.RequestsCookieJar()
    for c in cookie_list or []:
        try:
            jar.set(c["name"], c["value"], domain=c.get("domain", ".x.ai"),
                    path=c.get("path", "/"))
        except Exception:
            pass
    if fallback_sso and not any(k.name == "sso" for k in jar):
        jar.set("sso", fallback_sso, domain=".x.ai", path="/")
        jar.set("sso-rw", fallback_sso, domain=".x.ai", path="/")
    return jar


def authorize(sess, verifier, challenge):
    q = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "scope": SCOPES,
        "state": secrets.token_urlsafe(24),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "nonce": secrets.token_hex(16),
        "referrer": "cli-proxy-api",
        "plan": "generic",
        "email": "true",
    }
    url = AUTHORIZE + "?" + urllib.parse.urlencode(q)
    # allow_redirects=False: kita mau Location header, bukan ikut ke 127.0.0.1
    r = sess.get(url, allow_redirects=False, timeout=40)
    loc = r.headers.get("Location", "") or ""
    if not loc:
        # mungkin lewat halaman consent dulu
        return None, f"HTTP {r.status_code} tanpa Location; body={r.text[:160]!r}"
    m = re_search_code(loc)
    if m:
        return m, "ok"
    # ikut satu langkah lagi (consent -> redirect)
    follow = urllib.parse.urljoin(AUTHORIZE, loc)
    r2 = sess.get(follow, allow_redirects=False, timeout=40)
    loc2 = r2.headers.get("Location", "") or ""
    m2 = re_search_code(loc2)
    if m2:
        return m2, "ok (consent)"
    return None, f"lokasi tanpa code: {loc[:120]} -> {loc2[:120]}"


def re_search_code(u):
    m = re.search(r'[?&]code=([^&]+)', u or '')
    return urllib.parse.unquote(m.group(1)) if m else None


def exchange(sess, code, verifier):
    last = None
    for url in TOKEN_URLS:
        try:
            r = sess.post(url, data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT,
                "code_verifier": verifier,
            }, headers={"User-Agent": "grok-cli/0.1",
                        "Accept": "application/json"}, timeout=40)
            if r.status_code == 200:
                return 200, r.json()
            last = (r.status_code, r.text[:250])
        except Exception as e:
            last = (0, f"{type(e).__name__}: {str(e)[:120]}")
    return last


def main():
    accounts = []
    for pat in ("sso_art/*.txt", "*/sso.txt"):
        for f in sorted(glob.glob(pat)):
            for line in open(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                accounts.append(j)
    if len(sys.argv) > 2:
        accounts = [{"email": sys.argv[1], "password": sys.argv[2],
                     "cookies": [], "sso": ""}]
    seen, uniq = set(), []
    for a in accounts:
        if a.get("email") and a["email"] not in seen:
            seen.add(a["email"])
            uniq.append(a)
    if not uniq:
        print("tidak ada akun", flush=True)
        return
    print(f"menguji {len(uniq)} akun (HTTP murni, tanpa browser)\n", flush=True)

    out = []
    for a in uniq:
        email = a["email"]
        sess = requests.Session()
        sess.headers.update({"User-Agent": UA, "Accept": "text/html,application/json"})
        sess.cookies = to_cookiejar(a.get("cookies"), a.get("sso"))
        verifier, challenge = pkce()
        try:
            code, note = authorize(sess, verifier, challenge)
        except Exception as e:
            code, note = None, f"ERR {type(e).__name__}: {str(e)[:120]}"
        if not code:
            print(f"  ✗ {email:26} {note}", flush=True)
            continue
        st, tok = exchange(sess, code, verifier)
        if st == 200 and isinstance(tok, dict) and tok.get("access_token"):
            print(f"  ✓ {email:26} TOKEN OK scope={tok.get('scope','')} "
                  f"expires_in={tok.get('expires_in')}", flush=True)
            out.append({"email": email, "password": a.get("password"),
                        "token": tok})
        else:
            print(f"  ~ {email:26} code OK, tukar gagal: {st} {str(tok)[:150]}",
                  flush=True)
    if out:
        with open("grok_oauth.json", "w") as fh:
            json.dump(out, fh, indent=2)
        print(f"\n>>> {len(out)} token disimpan ke grok_oauth.json", flush=True)
    else:
        print("\n>>> tidak ada token", flush=True)


main()