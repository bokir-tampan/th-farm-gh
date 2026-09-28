"""mail.tm client — inbox gratis via API, tanpa domain & tanpa Gmail.

Interface sama dengan Tempik (tempik_client.py):
    create_inbox() -> (email, order_id)
    wait_otp(addr, timeout, since) -> code | None
    delete_inbox(addr) -> None

xAI terbukti mau kirim OTP ke domain non-populer (arxpays.my.id), jadi
mail.tm (uberip.com dll) adalah jalur termurah: tanpa domain, tanpa Gmail.
"""
from __future__ import annotations

import random
import re
import string
import time

import requests

API = "https://api.mail.tm"

_OTP_RE = re.compile(r'code[^0-9]{0,25}(\d{3}[-\s]?\d{3})', re.I)


def extract_otp(subject, body):
    """xAI: 'SpaceXAI confirmation code: 699-696'. Subject dulu; body menolak
    angka yang didahului '#' (hex color CSS bikin false positive)."""
    match = _OTP_RE.search(subject or '')
    if not match:
        match = re.search(r'(?<![#\w])(\d{3}[-\s]?\d{3})(?![#\w])',
                          f"{subject or ''}\n{body or ''}")
    return re.sub(r'\D', '', match.group(1)) if match else ''


class MailTm:
    def __init__(self, api_url: str = "", domain: str = ""):
        self.s = requests.Session()
        self.s.headers.update({"Accept": "application/json",
                               "User-Agent": "Mozilla/5.0 Chrome/131.0"})
        self.domain = domain
        self._creds: dict[str, str] = {}   # addr -> password
        self._tokens: dict[str, str] = {}

    # ── helpers ────────────────────────────────────────────────
    def _pick_domain(self) -> str:
        if self.domain:
            return self.domain
        try:
            d = self.s.get(f"{API}/domains", timeout=20).json()
            if isinstance(d, dict):
                d = d.get("hydra:member", [])
            active = [x["domain"] for x in d if x.get("isActive")]
            if active:
                return random.choice(active)
        except Exception:
            pass
        return "uberip.com"

    def _login(self, addr: str) -> str:
        """Ambil bearer token untuk addr (cache)."""
        if addr in self._tokens:
            return self._tokens[addr]
        pw = self._creds.get(addr)
        if not pw:
            return ""
        r = self.s.post(f"{API}/token", json={"address": addr, "password": pw}, timeout=20)
        tok = (r.json() or {}).get("token", "") if r.status_code == 200 else ""
        if tok:
            self._tokens[addr] = tok
        return tok

    # ── interface ──────────────────────────────────────────────
    def create_inbox(self):
        local = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
        addr = f"{local}@{self._pick_domain()}"
        pw = "Tm!" + ''.join(random.choices(string.ascii_letters + string.digits, k=14))
        r = self.s.post(f"{API}/accounts", json={"address": addr, "password": pw}, timeout=25)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"mail.tm create failed {r.status_code}: {r.text[:150]}")
        self._creds[addr] = pw
        self._login(addr)
        return addr, addr

    def wait_otp(self, addr, timeout=90, since=None):
        start = time.time()
        while time.time() - start < timeout:
            tok = self._login(addr)
            if not tok:
                time.sleep(5)
                continue
            try:
                r = self.s.get(f"{API}/messages",
                               headers={"Authorization": f"Bearer {tok}"}, timeout=25)
                msgs = r.json() if r.status_code == 200 else []
                if isinstance(msgs, dict):
                    msgs = msgs.get("hydra:member", []) or msgs.get("messages", [])
            except Exception:
                msgs = []
            for m in msgs or []:
                subj = m.get("subject", "") or ""
                frm = (m.get("from") or {}).get("address", "")
                body = ""
                try:
                    d = self.s.get(f"{API}/messages/{m['id']}",
                                   headers={"Authorization": f"Bearer {tok}"},
                                   timeout=20).json()
                    body = (d.get("text") or "") + "\n" + (d.get("html") or "")
                except Exception:
                    pass
                code = extract_otp(subj, body)
                if code:
                    return code
            time.sleep(5)
        return None

    def delete_inbox(self, addr):
        return None


if __name__ == '__main__':
    assert extract_otp('SpaceXAI confirmation code: 699-696', '') == '699696'
    assert extract_otp('', 'color:#333333') == ''
    m = MailTm()
    a, _ = m.create_inbox()
    print('self-check ok', a)
    assert a.split('@')[1]
