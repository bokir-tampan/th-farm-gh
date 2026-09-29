#!/usr/bin/env python3
"""Grok OAuth via DEVICE CODE flow (jalur 9router grok-cli).

Beda dari PKCE loopback yang gagal (307 /account):
  POST https://auth.x.ai/oauth2/device/code  -> {device_code, user_code,
                                                  verification_uri}
  user membuka verification_uri + klik Allow (bisa otomatis dgn sso cookie)
  POST https://auth.x.ai/oauth2/token  grant_type=urn:ietf:params:oauth:grant-type:device_code
"""
import glob, json, sys, time
import requests

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = ("openid profile email offline_access grok-cli:access api:access "
         "conversations:read conversations:write")
DEVICE_CODE = "https://auth.x.ai/oauth2/device/code"
TOKEN = "https://auth.x.ai/oauth2/token"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

acct = None
for f in sorted(glob.glob("sso_art/*.txt")):
    acct = json.loads(open(f).read().splitlines()[0])
    break
if len(sys.argv) > 2:
    acct = {"email": sys.argv[1], "password": sys.argv[2], "sso": "", "cookies": []}

email, sso = acct["email"], acct.get("sso") or ""
print("akun:", email, "| sso len:", len(sso))

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "application/json"})
for dom in (".x.ai", "accounts.x.ai", "auth.x.ai", "grok.com"):
    if sso:
        s.cookies.set("sso", sso, domain=dom, path="/")
        s.cookies.set("sso-rw", sso, domain=dom, path="/")
for c in (acct.get("cookies") or []):
    try:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", ".x.ai"),
                      path=c.get("path", "/"))
    except Exception:
        pass

# 0) bukti sesi hidup
try:
    r0 = s.get("https://grok.com/api/auth/session", timeout=25)
    print("session:", r0.status_code, r0.text[:100])
except Exception as e:
    print("session ERR:", type(e).__name__, str(e)[:80])

# 1) minta device code
body = {"client_id": CLIENT_ID, "scope": SCOPE}
try:
    r = s.post(DEVICE_CODE, data=body, timeout=40)
    print("\n[1] device/code ->", r.status_code)
    print("    ", r.text[:400])
    if r.status_code != 200:
        # coba JSON body
        r = s.post(DEVICE_CODE, json=body, timeout=40)
        print("[1b] json ->", r.status_code, r.text[:400])
    dc = r.json() if r.status_code == 200 else None
except Exception as e:
    dc = None
    print("\n[1] ERR:", type(e).__name__, str(e)[:150])

if dc and dc.get("device_code"):
    print("\n  device_code:", dc["device_code"][:40], "...")
    print("  user_code  :", dc.get("user_code"))
    print("  verify_uri :", dc.get("verification_uri") or dc.get("verification_uri_complete"))
    print("  interval   :", dc.get("interval", 5), "expires:", dc.get("expires_in"))
    # simpan untuk langkah browser
    json.dump({"email": email, "device": dc}, open(f"device_{email.split('@')[0]}.json", "w"), indent=2)

    # 2) coba langsung tukar (belum di-approve -> harus 'authorization_pending')
    for attempt in range(3):
        time.sleep(dc.get("interval", 5))
        tr = s.post(TOKEN, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": dc["device_code"], "client_id": CLIENT_ID},
            timeout=40)
        print(f"\n[2] token attempt {attempt+1} -> {tr.status_code} {tr.text[:200]}")
        if tr.status_code == 200:
            json.dump(tr.json(), open(f"token_{email.split('@')[0]}.json", "w"), indent=2)
            print("  ✓ TOKEN DAPAT")
            break
        if "slow_down" in tr.text:
            time.sleep(5)
else:
    print("\ndevice/code gagal")