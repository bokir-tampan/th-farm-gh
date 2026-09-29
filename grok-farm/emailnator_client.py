"""emailnator.com client — alamat @gmail.com sementara, facade SINKRON.

Kenapa lewat browser: API emailnator dilindungi Cloudflare, request HTTP
mentah dari IP datacenter dijawab 503. Semua panggilan dilakukan di dalam
halaman (page.evaluate + fetch) sehingga cookie + fingerprint ikut terbawa.

Kenapa thread: grok.py memanggil create_inbox()/wait_otp() secara sinkron
dari dalam event loop-nya sendiri. Browser Camoufox butuh loop sendiri,
jadi seluruh browser dijalankan di thread terpisah dengan loop privat;
metode publik di sini sinkron dan aman dipanggil dari loop mana pun.

Interface sama dengan Tempik:
    create_inbox() -> email
    wait_otp(addr, timeout, since) -> code | None
    delete_inbox(addr) -> None
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time

_OTP_RE = re.compile(r'code[^0-9]{0,25}(\d{3}[-\s]?\d{3})', re.I)
GOOGLEMAIL = 8      # EMAIL_TYPES["googleMail"] dari chunk JS emailnator


def extract_otp(subject, body):
    m = _OTP_RE.search(subject or '')
    if not m:
        m = re.search(r'(?<![#\w])(\d{3}[-\s]?\d{3})(?![#\w])',
                      f"{subject or ''}\n{body or ''}")
    return re.sub(r'\D', '', m.group(1)) if m else ''


class Emailnator:
    def __init__(self, api_url: str = "", domain: str = ""):
        self.domain = domain
        self.email = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._page = None
        self._cam = None
        self._ready = threading.Event()

    # ── thread + browser ───────────────────────────────────────
    def _start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=180)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._boot())
        except Exception as e:
            print(f"[emailnator] boot gagal: {type(e).__name__}: {str(e)[:150]}",
                  flush=True)
        finally:
            self._ready.set()
        self._loop.run_forever()

    async def _boot(self):
        from camoufox.async_api import AsyncCamoufox
        self._cam = AsyncCamoufox(headless=True, humanize=True,
                                  block_webrtc=True, locale="en-US")
        await self._cam.start()
        self._page = await self._cam.browser.new_page()
        await self._page.goto("https://www.emailnator.com/",
                              wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(4)

    def _call(self, coro, timeout=300):
        self._start()
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    async def _api(self, path, payload=None, method="POST"):
        return await self._page.evaluate(
            """async ([p, body, meth]) => {
                const opt = {method: meth, credentials: 'include',
                             headers: {'Content-Type': 'application/json',
                                       'Accept': 'application/json'}};
                if (meth !== 'GET' && body !== null) opt.body = JSON.stringify(body);
                const r = await fetch('https://www.emailnator.com' + p, opt);
                return {status: r.status, body: (await r.text()).slice(0, 8000)};
            }""", [path, payload, method])

    # ── API ────────────────────────────────────────────────────
    async def _create(self):
        r = await self._api("/api/generate-email", {"ids": [GOOGLEMAIL]})
        addr = ""
        try:
            j = json.loads(r.get("body") or "{}")
            addr = (j.get("email") or j.get("address") or "")
        except Exception:
            pass
        if not addr:
            # fallback: alamat dirender di DOM (API 503 dari IP datacenter)
            try:
                addr = await self._page.evaluate(
                    """() => { const m = document.body.innerText.match(
                        /[\\w.\\-+]+@(googlemail|gmail)\\.com/); return m ? m[0] : ''; }""")
            except Exception:
                pass
        if not addr:
            raise RuntimeError(f"emailnator generate gagal: {str(r)[:180]}")
        self.email = addr
        return addr

    async def _wait(self, addr, timeout):
        start = time.time()
        while time.time() - start < timeout:
            r = await self._api("/api/message-list", {"email": addr, "limit": 20})
            msgs = []
            try:
                j = json.loads(r.get("body") or "{}")
                msgs = (j.get("messageData") or j.get("messages")
                        or j.get("emails") or [])
            except Exception:
                pass
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                subj = m.get("subject", "") or m.get("from", "") or ""
                mid = m.get("messageID") or m.get("id") or m.get("_id")
                code = extract_otp(subj, "")
                if code:
                    return code
                if mid:
                    rc = await self._api(f"/api/message/{mid}", None, "GET")
                    body = rc.get("body", "")
                    code = extract_otp(subj, body)
                    if code:
                        return code
            await asyncio.sleep(6)
        return None

    # ── interface publik (sinkron) ─────────────────────────────
    def create_inbox(self):
        return self._call(self._create(), timeout=240)

    def wait_otp(self, addr, timeout=90, since=None):
        return self._call(self._wait(addr, timeout), timeout=timeout + 60)

    def delete_inbox(self, addr):
        return None

    def close(self):
        try:
            if self._cam and self._loop:
                asyncio.run_coroutine_threadsafe(self._cam.stop(), self._loop)
        except Exception:
            pass


if __name__ == '__main__':
    assert extract_otp('SpaceXAI confirmation code: 699-696', '') == '699696'
    assert extract_otp('', 'color:#333333') == ''
    e = Emailnator()
    addr = e.create_inbox()
    print("inbox:", addr, flush=True)
    assert "@" in addr
    import sys
    if len(sys.argv) > 1:
        print("menunggu OTP 90s...", flush=True)
        print("OTP:", e.wait_otp(addr, timeout=90), flush=True)