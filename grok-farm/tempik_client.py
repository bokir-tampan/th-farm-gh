import time
import random
import string
import imaplib
import email as emailmod
import re

_OTP_RE = re.compile(r'code[^0-9]{0,25}(\d{3}[-\s]?\d{3})', re.I)

DOMAIN = 'arxpays.my.id'  # catch-all Cloudflare Email Routing -> GMAIL


def extract_otp(subject, body):
    """xAkun: 'SpaceXAI confirmation code: 699-696'. Regex 6-angka polos
    tertipu oleh hex color CSS '#333333' di body email — karenanya subject
    lebih dulu, dan body menolak angka yang didahului '#'."""
    match = _OTP_RE.search(subject or '')
    if not match:
        match = re.search(r'(?<![#\w])(\d{3}[-\s]?\d{3})(?![\w])',
                          f"{subject or ''}\n{body or ''}")
    return re.sub(r'\D', '', match.group(1)) if match else ''


class Tempik:
    """Domain sendiri + Cloudflare Email Routing. Nama class dipertahankan.

    Catch-all meneruskan semua *@DOMAIN ke satu Gmail. Alamatnya acak, jadi
    tiap akun beda di mata xAI, tapi semuanya mendarat di inbox yang sama.
    OTP dicocokkan ke alamat persis, biar tidak ketuker antar akun.
    """

    GMAIL = 'arxdubai496@gmail.com'
    _PW = 'umxlkmcozmqrbpzw'  # app password, bukan password login

    def __init__(self, api_url, domain):
        self.api_url = api_url
        self.domain = DOMAIN or domain

    def create_inbox(self):
        """Alamat acak. Catch-all yang menangkap, tidak ada yang didaftarkan."""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)) \
            + '@' + self.domain

    def wait_otp(self, addr, timeout=90, since=None):
        """Poll IMAP, ambil OTP dari email yang To-nya persis alamat ini."""
        start = time.time()
        while time.time() - start < timeout:
            M = None
            try:
                M = imaplib.IMAP4_SSL('imap.gmail.com', 993)
                M.login(self.GMAIL, self._PW)
                M.select('INBOX')
                _, data = M.search(None, 'UNSEEN')
                for num in reversed((data[0] or b'').split()):
                    _, msg = M.fetch(num, '(RFC822)')
                    m = emailmod.message_from_bytes(msg[0][1])
                    to = (m.get('To') or '') + (m.get('Delivered-To') or '') \
                        + (m.get('X-Forwarded-To') or '')
                    if addr.lower() not in to.lower():
                        continue
                    body = ''
                    for part in m.walk():
                        if part.get_content_type() in ('text/plain', 'text/html'):
                            body += part.get_payload(decode=True).decode('utf-8', 'replace')
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
            time.sleep(6)  # ponytail: Gmail throttle IMAP kalau lebih rapat
        return None

    def delete_inbox(self, addr):
        """Catch-all tidak menyimpan inbox, tidak ada yang dihapus."""
        return None


if __name__ == '__main__':
    assert extract_otp('code: 699-696', '') == '699696'
    assert extract_otp('', 'color:#333333') == ''
    m = Tempik('', '')
    a = m.create_inbox()
    assert a.endswith('@' + DOMAIN)
    M = imaplib.IMAP4_SSL('imap.gmail.com', 993)
    M.login(m.GMAIL, m._PW)
    M.logout()
    print('self-check ok', a)
