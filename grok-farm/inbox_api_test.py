#!/usr/bin/env python3
"""Tes inbox API untuk domain yang DITERIMA xAI.

Target: temukan backend inbox yang (a) domain-nya lolos blocklist xAI,
(b) email bisa dibaca otomatis via HTTP dari IP datacenter.

Kandidat: emailnator (generator @gmail.com), mail.gw (mail.tm clone),
mailmine.com, mailbox.org / disroot.org (provider real, butuh signup).
"""
import json
import random
import string
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def http(url, method="GET", data=None, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:
        return 0, f"{type(e).__name__}: {str(e)[:150]}"


def rnd(n=12):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


print("=" * 70)
print("1) emailnator.com — generator @gmail.com")
print("=" * 70)
for ep, payload in [
    ("/api/generate-email", {"email": ["domain", "plusGmail", "dotGmail", "googleMail"]}),
    ("/api/generate-email", {"email": ["domain"]}),
]:
    s, t = http("https://www.emailnator.com" + ep, "POST", payload,
                {"Origin": "https://www.emailnator.com",
                 "Referer": "https://www.emailnator.com/"})
    print(f"  POST {ep} {payload} -> {s} {t[:200]}")
    if s == 200 and "email" in t:
        break

print()
print("=" * 70)
print("2) mail.gw — mail.tm-compatible")
print("=" * 70)
for base in ["https://api.mail.gw", "https://mail.gw"]:
    s, t = http(base + "/domains")
    print(f"  GET {base}/domains -> {s} {t[:200]}")

addr = rnd() + "@mail.gw"
pw = "Tg!" + rnd(14)
s, t = http("https://api.mail.gw/accounts", "POST", {"address": addr, "password": pw})
print(f"  POST /accounts ({addr}) -> {s} {t[:250]}")

print()
print("=" * 70)
print("3) mailmine.com")
print("=" * 70)
for u in ["https://mailmine.com/api/domains", "https://api.mailmine.com/domains",
          "https://mailmine.com/api/v1/domains"]:
    s, t = http(u)
    print(f"  GET {u} -> {s} {t[:180]}")

print()
print("=" * 70)
print("4) temp-mail.io (punya API, tapi domain diblok)")
print("=" * 70)
s, t = http("https://api.internal.temp-mail.io/api/v3/email/new", "POST", {})
print(f"  POST /email/new -> {s} {t[:200]}")
if s == 200:
    try:
        j = json.loads(t)
        tok = j.get("token")
        em = j.get("email")
        s2, t2 = http(f"https://api.internal.temp-mail.io/api/v3/email/{em}/messages",
                      headers={"Application-Token": tok})
        print(f"  GET messages ({em}) -> {s2} {t2[:200]}")
    except Exception as e:
        print("  err", e)

print()
print("=" * 70)
print("5) 1secmail API (domain dns4u.fun diblok, tapi cek fungsional)")
print("=" * 70)
for u in ["https://www.1secmail.com/api/v1/?action=getDomainList",
          "https://api.1secmail.com/api/v1/?action=getDomainList"]:
    s, t = http(u)
    print(f"  GET {u.split('?')[0]} -> {s} {t[:200]}")