#!/usr/bin/env python3
"""OAuth v2: authorize lewat auth.x.ai, ikuti redirect manual sampai `code`.

Temuan debug:
  - accounts.x.ai/oauth2/authorize  -> 307 /account (tidak menerima cookie)
  - auth.x.ai/oauth2/authorize      -> 303 /oauth2/consent?<params>  <-- jalur benar
Jadi: mulai dari auth.x.ai, lalu IKUTI setiap Location secara manual
(allow_redirects=False) sampai salah satunya membawa ?code=.
Redirect terakhir menuju 127.0.0.1 (server callback tidak ada) — cukup
diambil URL-nya, tidak perlu benar-benar terhubung.
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
AUTHORIZE_HOSTS = [
    "https://auth.x.ai/oauth2/authorize",
    "https://accounts.x.ai/oauth2/authorize",
]
TOKEN_URLS = [
    "https://auth.x.ai/oauth2/token",
    "https://accounts.x.ai/oauth2/token",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def pkce():
    v = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    return v, c


def params(challenge):
    return {
        "response_type": "code", "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT, "scope": SCOPES,
        "state": secrets.token_urlsafe(24), "code_challenge": challenge,
        "code_challenge_method": "S256", "nonce": secrets.token_hex(16),
        "referrer": "cli-proxy-api", "plan": "generic", "email": "true",
    }


def grab_code(u):
    m = re.search(r'[?&]code=([^&]+)', u or '')
    return urllib.parse.unquote(m.group(1)) if m else None


def follow(sess, start, max_hops=12, log=None):
    """Ikuti redirect manual; kembalikan (code, jejak)."""
    url = start
    trail = []
    for _ in range(max_hops):
        try:
            r = sess.get(url, allow_redirects=False, timeout=40,
                         headers={"Referer": "https://accounts.x.ai/"})
        except Exception as e:
            trail.append(f"ERR {type(e).__name__} @ {url[:60]}")
            return None, trail
        code = grab_code(r.headers.get("Location", "")) or grab_code(url)
        if code:
            trail.append(f"{r.status_code} CODE")
            return code, trail
        loc = r.headers.get("Location")
        trail.append(f"{r.status_code} {url.split('?')[0].split('//')[-1][:40]}"
                     + (f" -> {loc[:45]}" if loc else ""))
        if not loc:
            # mungkin /account -> perlu login; simpan body sebagai petunjuk
            trail.append(f"body={re.sub(r'\\s+', ' ', r.text[:80])!r}")
            return None, trail
        # Location relatif -> absolut
        url = urllib.parse.urljoin(url, loc)
        if "127.0.0.1" in url:
            c = grab_code(url)
            return c, trail
    return None, trail


def exchange(sess, code, verifier):
    last = None
    for url in TOKEN_URLS:
        try:
            r = sess.post(url, data={
                "grant_type": "authorization_code", "code": code,
                "client_id": CLIENT_ID, "redirect_uri": REDIRECT,
                "code_verifier": verifier,
            }, headers={"User-Agent": "grok-cli/0.1", "Accept": "application/json"},
                timeout=40)
            if r.status_code == 200:
                return 200, r.json()
            last = (r.status_code, r.text[:220])
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
                    accounts.append(json.loads(line))
                except Exception:
                    pass
    if len(sys.argv) > 2:
        accounts = [{"email": sys.argv[1], "password": sys.argv[2],
                     "sso": "", "cookies": []}]
    seen, uniq = set(), []
    for a in accounts:
        if a.get("email") and a["email"] not in seen:
            seen.add(a["email"]); uniq.append(a)
    if not uniq:
        print("tidak ada akun", flush=True); return

    print(f"menguji {len(uniq)} akun\n", flush=True)
    out = []
    for a in uniq:
        email = a["email"]
        s = requests.Session()
        s.headers.update({"User-Agent": UA,
                          "Accept": "text/html,application/json"})
        # sso pada .x.ai + grok.com + accounts.x.ai (cakupan penuh)
        sso = a.get("sso") or ""
        for dom in (".x.ai", "accounts.x.ai", "grok.com", ".accounts.x.ai"):
            if sso:
                s.cookies.set("sso", sso, domain=dom, path="/")
                s.cookies.set("sso-rw", sso, domain=dom, path="/")
        for c in (a.get("cookies") or []):
            try:
                s.cookies.set(c["name"], c["value"],
                              domain=c.get("domain", ".x.ai"),
                              path=c.get("path", "/"))
            except Exception:
                pass

        # bukti sesi hidup (cookie harus terkirim ke grok.com)
        try:
            rs = s.get("https://grok.com/api/auth/session", timeout=25)
            ses = rs.text[:80]
        except Exception as e:
            ses = f"ERR {type(e).__name__}"

        verifier, challenge = pkce()
        code, trail = None, []
        for host in AUTHORIZE_HOSTS:
            url = host + "?" + urllib.parse.urlencode(params(challenge))
            code, trail = follow(s, url)
            if code:
                break

        if not code:
            print(f"  ✗ {email:26} session={ses} trail={' | '.join(trail)[:150]}",
                  flush=True)
            continue
        st, tok = exchange(s, code, verifier)
        if st == 200 and isinstance(tok, dict) and tok.get("access_token"):
            print(f"  ✓ {email:26} TOKEN OK scope={tok.get('scope','')} "
                  f"exp={tok.get('expires_in')}", flush=True)
            out.append({"email": email, "password": a.get("password"),
                        "token": tok})
        else:
            print(f"  ~ {email:26} code OK, tukar gagal {st}: {str(tok)[:130]}",
                  flush=True)
    if out:
        json.dump(out, open("grok_oauth.json", "w"), indent=2)
        print(f"\n>>> {len(out)} token -> grok_oauth.json", flush=True)
    else:
        print("\n>>> tidak ada token", flush=True)


main()