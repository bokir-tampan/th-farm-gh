"""Gmail dot-trick client untuk grok-farm.

Satu Gmail = N alias. Gmail mengabaikan titik di local part
(c.ahyo@gmail.com == cahyo@gmail.com), tapi header To: menyimpan
alamat persisnya — xAI melihat N alamat berbeda, semuanya mendarat
di satu inbox. Tidak perlu domain, tidak perlu Cloudflare.

Interface sama dengan Tempik:
    create_inbox() -> email
    wait_otp(addr, timeout, since) -> code | None
    delete_inbox(addr) -> None

Butuh Gmail App Password (Google Account -> Security -> App passwords).
Password login biasa TIDAK bekerja untuk IMAP.
"""
from __future__ import annotations

import email as emailmod
import imaplib
import random
import re
import time

_OTP_RE = re.compile(r'code[^0-9]{0,25}(\d{3}[-\s]?\d{3})', re.I)

# Scan INBOX dan Spam — Gmail sering menaruh OTP xAI di Spam.
BOXES = ['INBOX', '"[Gmail]/Spam"']


def extract_otp(subject, body):
    """xAI: 'SpaceXAI confirmation code: 699-696'. Subject dulu; body menolak
    angka yang didahului '#' (hex color CSS bikin false positive)."""
    match = _OTP_RE.search(subject or '')
    if not match:
        match = re.search(r'(?<![#\w])(\d{3}[-\s]?\d{3})(?![#\w])',
                          f"{subject or ''}\n{body or ''}")
    return re.sub(r'\D', '', match.group(1)) if match else ''


class GmailDot:
    GMAIL = ''          # diisi dari config / env GROK_GMAIL
    _PW = ''            # App Password 16 char

    def __init__(self, api_url: str = "", domain: str = ""):
        import os
        self.GMAIL = self.GMAIL or os.environ.get('GROK_GMAIL', '')
        self._PW = self._PW or os.environ.get('GROK_GMAIL_PW', '')
        if not self.GMAIL or not self._PW:
            raise RuntimeError("GROK_GMAIL / GROK_GMAIL_PW belum diisi")
        self.base_local = self.GMAIL.split('@')[0]
        self.domain = self.GMAIL.split('@')[1]
        self._used: set[str] = set()

    def _dotted(self) -> str:
        """Sisipkan titik acak; hindari leading/trailing/consecutive."""
        n = len(self.base_local)
        if n < 4:
            # terlalu pendek untuk dot-trick — pakai + alias
            return f"{self.base_local}{random.randint(100, 999)}"
        for _ in range(300):
            positions = sorted(random.sample(range(1, n), k=random.randint(1, max(1, n - 2))))
            parts, prev = [], 0
            for p in positions:
                parts.append(self.base_local[prev:p]); prev = p
            parts.append(self.base_local[prev:])
            cand = ".".join(parts)
            if cand not in self._used and cand != self.base_local:
                self._used.add(cand)
                return cand
        cand = f"{self.base_local}{random.randint(1000, 9999)}"
        self._used.add(cand)
        return cand

    def create_inbox(self):
        return f"{self._dotted()}@{self.domain}"

    def wait_otp(self, addr, timeout=90, since=None):
        start = time.time()
        while time.time() - start < timeout:
            M = None
            try:
                M = imaplib.IMAP4_SSL('imap.gmail.com', 993)
                M.login(self.GMAIL, self._PW)
                for box in BOXES:
                    try:
                        typ, _ = M.select(box, readonly=False)
                        if typ != 'OK':
                            continue
                    except Exception:
                        continue
                    _, data = M.search(None, 'UNSEEN')
                    for num in reversed((data[0] or b'').split()):
                        _, msg = M.fetch(num, '(RFC822)')
                        m = emailmod.message_from_bytes(msg[0][1])
                        to = ((m.get('To') or '') + (m.get('Delivered-To') or '')
                              + (m.get('X-Forwarded-To') or ''))
                        if addr.lower() not in to.lower():
                            continue
                        body = ''
                        for part in m.walk():
                            if part.get_content_type() in ('text/plain', 'text/html'):
                                p = part.get_payload(decode=True)
                                if p:
                                    body += p.decode('utf-8', 'replace')
                        code = extract_otp(m.get('Subject'), body)
                        if code:
                            M.store(num, '+FLAGS', '\\Seen')
                            return code
            except Exception:
                pass
            finally:
                if M:
                    try:
                        M.logout()
                    except Exception:
                        pass
            time.sleep(6)   # Gmail throttle IMAP kalau lebih rapat
        return None

    def delete_inbox(self, addr):
        return None


if __name__ == '__main__':
    assert extract_otp('SpaceXAI confirmation code: 699-696', '') == '699696'
    assert extract_otp('', 'color:#333333') == ''
    import os
    if os.environ.get('GROK_GMAIL'):
        g = GmailDot()
        for _ in range(3):
            print('alias:', g.create_inbox())
    else:
        print('set GROK_GMAIL + GROK_GMAIL_PW untuk tes penuh')
