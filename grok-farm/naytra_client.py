"""NayTra Mail client — panel tempmail sendiri (mail.naytra.net).

Akun ini PREMIUM: alamat unlimited, email tidak kadaluarsa. Semua lewat
HTTP biasa (requests) — tidak butuh browser, jalan di VPS 1 GB.

API (dari JS inline /app, bukan tebakan):
    POST /login            username, password           -> cookie session
    GET  /api/generate[?domain=<d>]                     -> {status, address}
    POST /api/saved        {address}                    -> aktifkan/pertahankan
    GET  /api/inbox/<addr>                              -> {status, emails:[...]}
    GET  /api/email/<id>                                -> {status, from, subject, body_html, ...}

Interface sama dengan Tempik (dipakai grok.py):
    create_inbox() -> email
    wait_otp(addr, timeout, since) -> code | None
    delete_inbox(addr) -> None
"""
from __future__ import annotations

import os
import re
import time

import requests

BASE = "https://mail.naytra.net"
_OTP_RE = re.compile(r'code[^0-9]{0,25}(\d{3}[-\s]?\d{3})', re.I)


def extract_otp(subject, body):
    m = _OTP_RE.search(subject or '')
    if not m:
        m = re.search(r'(?<![#\w])(\d{3}[-\s]?\d{3})(?![#\w])',
                      f"{subject or ''}\n{body or ''}")
    return re.sub(r'\D', '', m.group(1)) if m else ''


class Naytra:
    def __init__(self, api_url: str = "", domain: str = ""):
        self.user = os.environ.get('NAYTRA_USER', 'asu22')
        self.pw = os.environ.get('NAYTRA_PW', 'Germand26')
        self.domain = domain
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/html",
        })
        self._logged = False

    def _login(self):
        if self._logged:
            return
        self.s.get(f"{BASE}/login", timeout=30)
        r = self.s.post(f"{BASE}/login",
                        data={"username": self.user, "password": self.pw},
                        timeout=30, allow_redirects=True)
        if "salah" in r.text.lower():
            raise RuntimeError("NayTra: login gagal (username/password)")
        self._logged = True

    def _get(self, path):
        self._login()
        r = self.s.get(BASE + path, timeout=40)
        try:
            return r.json()
        except Exception:
            return {"status": False, "raw": r.text[:200]}

    # ── interface ──────────────────────────────────────────────
    def create_inbox(self):
        self._login()
        param = f"?domain={self.domain}" if self.domain else ""
        d = self._get(f"/api/generate{param}")
        addr = d.get("address") or d.get("email") or ""
        if not addr:
            raise RuntimeError(f"NayTra generate gagal: {str(d)[:160]}")
        # simpan supaya alamat tetap hidup (premium: unlimited & permanen)
        try:
            self.s.post(f"{BASE}/api/saved", json={"address": addr}, timeout=25)
        except Exception:
            pass
        self.email = addr
        return addr

    def wait_otp(self, addr, timeout=90, since=None):
        start = time.time()
        while time.time() - start < timeout:
            d = self._get(f"/api/inbox/{addr}")
            emails = d.get("emails") or []
            for e in emails:
                if not isinstance(e, dict):
                    continue
                subj = e.get("subject", "") or ""
                code = extract_otp(subj, "")
                if code:
                    return code
                eid = e.get("id")
                if eid is not None:
                    ed = self._get(f"/api/email/{eid}")
                    body = f"{ed.get('subject','')}\n{ed.get('body','')}\n{ed.get('body_html','')}"
                    code = extract_otp(subj, body)
                    if code:
                        return code
            time.sleep(5)
        return None

    def delete_inbox(self, addr):
        try:
            self._login()
            self.s.delete(f"{BASE}/api/saved/{addr}", timeout=20)
        except Exception:
            pass
        return None

    def domains(self):
        """Domain yang ditawarkan panel (dropdown 'Pilih Domain')."""
        self._login()
        r = self.s.get(f"{BASE}/app", timeout=30)
        return sorted(set(re.findall(r'[a-z0-9][a-z0-9.\-]{2,40}\.[a-z]{2,10}',
                                     r.text)))[:60]


if __name__ == '__main__':
    assert extract_otp('SpaceXAI confirmation code: 699-696', '') == '699696'
    assert extract_otp('', 'color:#333333') == ''
    n = Naytra()
    a = n.create_inbox()
    print("inbox:", a, flush=True)
    assert "@" in a
    print("cek inbox:", n._get(f"/api/inbox/{a}"))