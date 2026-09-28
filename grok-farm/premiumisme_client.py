"""Premiumisme Mail client — tempmail Laravel + Livewire.

Situs: https://premiumisme.info (Livewire 3, domain: premiumisme.info,
motionisme.com, yahookuu.id, gmaiilku.id, outlooku.id).

Kenapa Livewire: tidak ada REST API publik. Semua aksi (create, random,
refresh) adalah Livewire action yang dikirim sebagai POST ke /livewire/update
dengan payload {_token, components:[{snapshot, updates, calls}]}.

Alur:
  1. GET / -> ambil csrf _token + snapshot komponen (punya 'email'/'emails')
  2. POST /livewire/update  calls:[{path:'', method:'create', params:[mailbox]}]
  3. Baca emails[] dari snapshot baru; OTP ada di field body/subject.

Interface sama dengan Tempik:
    create_inbox() -> email
    wait_otp(addr, timeout, since) -> code | None
"""
from __future__ import annotations

import html as htmllib
import json
import re
import time

import requests

BASE = "https://premiumisme.info"
_OTP_RE = re.compile(r'code[^0-9]{0,25}(\d{3}[-\s]?\d{3})', re.I)


def extract_otp(subject, body):
    m = _OTP_RE.search(subject or '')
    if not m:
        m = re.search(r'(?<![#\w])(\d{3}[-\s]?\d{3})(?![#\w])',
                      f"{subject or ''}\n{body or ''}")
    return re.sub(r'\D', '', m.group(1)) if m else ''


def _unq(s):
    """Livewire meng-html-escape snapshot-nya dua kali."""
    return htmllib.unescape((s or "").replace("&quot;", '"'))


class Premiumisme:
    def __init__(self, api_url: str = "", domain: str = ""):
        self.domain = domain
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Referer": BASE + "/",
        })
        self._snap = None
        self._token = None
        self.email = ""

    # ── halaman + komponen ─────────────────────────────────────
    def _load(self):
        r = self.s.get(BASE + "/", timeout=40)
        html = r.text
        self._token = (re.search(r'name="csrf-token" content="([^"]+)"', html)
                       or re.search(r'name="_token" value="([^"]+)"', html))
        self._token = self._token.group(1) if self._token else None

        # komponen yang punya data email (bukan menu)
        best = None
        for m in re.findall(r'wire:snapshot="([^"]+)"', html):
            snap = json.loads(_unq(m))
            data = snap.get("data", {})
            if "emails" in data or "email" in data:
                best = snap
                if isinstance(data.get("emails"), list):
                    break
        if not best:
            raise RuntimeError("komponen email tidak ditemukan di halaman")
        self._snap = best
        self._domains = best.get("data", {}).get("domains") or []
        return best

    def _update(self, method, params=None):
        payload = {"_token": self._token,
                   "components": [{"snapshot": json.dumps(self._snap),
                                   "updates": {},
                                   "calls": [{"path": "", "method": method,
                                              "params": params or []}]}]}
        r = self.s.post(BASE + "/livewire/update", json=payload, timeout=50)
        try:
            j = r.json()
            comps = j.get("components") or []
            if comps and comps[0].get("snapshot"):
                self._snap = json.loads(_unq(comps[0]["snapshot"]))
            return self._snap
        except Exception:
            return None

    # ── interface ──────────────────────────────────────────────
    def create_inbox(self):
        self._load()
        data = self._snap.get("data", {})
        # domain default = yang pertama
        pool = data.get("domains") or []
        dom = self.domain or (pool[0] if pool else "premiumisme.info")
        if isinstance(dom, list):        # Livewire ["a","b"] bisa jadi nested
            dom = dom[0]
        mailbox = ''.join(__import__('random').choices(
            __import__('string').ascii_lowercase + __import__('string').digits, k=10))
        self._update("create", [f"{mailbox}@{dom}"])
        data = self._snap.get("data", {})
        self.email = data.get("email") or f"{mailbox}@{dom}"
        if isinstance(self.email, dict):
            self.email = self.email.get("email", "")
        return self.email

    def _read(self):
        data = self._snap.get("data", {}) if self._snap else {}
        emails = data.get("emails") or []
        if isinstance(emails, dict):
            emails = emails.get("values", []) or []
        out = []
        for e in emails:
            if isinstance(e, dict):
                out.append((e.get("subject", ""), e.get("body", "") or
                            e.get("content", "") or e.get("text", "")))
            elif isinstance(e, str):
                out.append(("", e))
        return out

    def wait_otp(self, addr, timeout=90, since=None):
        start = time.time()
        while time.time() - start < timeout:
            try:
                self._update("refresh")
            except Exception:
                pass
            for subj, body in self._read():
                code = extract_otp(subj, body)
                if code:
                    return code
            time.sleep(6)
        return None

    def delete_inbox(self, addr):
        return None


if __name__ == '__main__':
    assert extract_otp('SpaceXAI confirmation code: 699-696', '') == '699696'
    p = Premiumisme()
    addr = p.create_inbox()
    print("inbox:", addr, flush=True)
    assert "@" in addr