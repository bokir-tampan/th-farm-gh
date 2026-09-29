#!/usr/bin/env python3
"""Debug: apa yang sebenarnya terjadi di /oauth2/authorize dengan cookie SSO."""
import glob, json, re, secrets, base64, hashlib, urllib.parse
import requests

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
REDIRECT = "http://127.0.0.1:56121/callback"
SCOPES = "openid profile email offline_access grok-cli:access api:access"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

acc = None
for f in sorted(glob.glob("sso_art/*.txt")):
    acc = json.loads(open(f).read().splitlines()[0])
    break
email, sso = acc["email"], acc["sso"]
print("akun:", email, "| sso len:", len(sso))

v = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
q = {"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT,
     "scope": SCOPES, "state": secrets.token_urlsafe(24), "code_challenge": c,
     "code_challenge_method": "S256", "nonce": secrets.token_hex(16),
     "referrer": "cli-proxy-api", "plan": "generic", "email": "true"}
url = "https://accounts.x.ai/oauth2/authorize?" + urllib.parse.urlencode(q)

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "text/html,application/json"})

# 1) cookie kepakai? tes session endpoint dulu
s.cookies.set("sso", sso, domain=".x.ai", path="/")
s.cookies.set("sso-rw", sso, domain=".x.ai", path="/")
r0 = s.get("https://grok.com/api/auth/session", timeout=30)
print("\n[1] grok.com/api/auth/session ->", r0.status_code, r0.text[:160])

# 2) authorize, lihat header mentah
r = s.get(url, allow_redirects=False, timeout=40)
print("\n[2] authorize ->", r.status_code)
for k, vv in r.headers.items():
    if k.lower() in ("location", "set-cookie", "cf-mitigated", "server", "cf-ray"):
        print(f"    {k}: {str(vv)[:200]}")
print("    body:", re.sub(r"\s+", " ", r.text[:300]))

# 3) tanpa sso-rw, hanya sso
s2 = requests.Session(); s2.headers.update({"User-Agent": UA})
s2.cookies.set("sso", sso, domain=".x.ai", path="/")
r2 = s2.get(url, allow_redirects=False, timeout=40)
print("\n[3] authorize (hanya sso) ->", r2.status_code,
      "| Location:", r2.headers.get("Location", "")[:160])

# 4) endpoint authorize alternatif
for alt in ["https://auth.x.ai/oauth2/authorize",
            "https://accounts.x.ai/oauth2/authorize/consent",
            "https://accounts.x.ai/api/oauth2/authorize"]:
    try:
        rr = s.get(alt + "?" + urllib.parse.urlencode(q), allow_redirects=False, timeout=25)
        print(f"\n[4] {alt} -> {rr.status_code} Location={rr.headers.get('Location','')[:120]}")
    except Exception as e:
        print(f"\n[4] {alt} -> ERR {type(e).__name__}: {str(e)[:80]}")