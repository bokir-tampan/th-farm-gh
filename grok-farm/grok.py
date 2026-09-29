#!/usr/bin/env python3
"""grok_signup.py — Hybrid mass auto-register Grok (accounts.x.ai).

Browser only collects what cannot be forged (Castle.io token + Turnstile).
Everything after that is pure HTTP, so a dead page or a slow redirect chain
never blocks the account.

Flow:
  1. Inbox @arxpays.my.id (diteruskan ke Gmail)
  2. Camoufox + BrightData, one preflight
  3. Open sign-up, dismiss cookies, click email signup
  4. Fill email. OTP polling starts BEFORE the click.
  5. Sniff castleRequestToken off the send-verification-code request
  6. Fill OTP in the page (server verifies it), keep the code
  7. Fill name + password
  8. Turnstile: native solve, else click the checkbox widget, else skip
  9. POST /api/auth/sign-up/create-account from inside the page (cookies,
     castle token, turnstile token). No click, no reload.
 10. Replay the set-cookie redirect chain over HTTP
 11. Confirm grok.com/api/auth/session == authenticated
 12. Append sso.txt under a file lock
 13. Install into 9Router (device flow, HTTP only)
"""
import sys
import os
import re
import json
import time
import random
import base64
import asyncio
import platform
import threading
import warnings
from pathlib import Path

# Windows + Playwright/Camoufox: pipe subprocess sudah ditutup, lalu GC masih
# manggil __repr__ transport dan melempar "I/O operation on closed pipe".
# Bukan kegagalan signup. Redam supaya tidak menimpa ringkasan.
warnings.filterwarnings('ignore', category=ResourceWarning)
if platform.system() == 'Windows':
    _orig_unraisable = getattr(sys, 'unraisablehook', None)

    def _quiet_unraisable(hookargs):
        err = hookargs.exc_value
        if isinstance(err, ValueError) and 'closed pipe' in str(err):
            return
        if _orig_unraisable:
            _orig_unraisable(hookargs)

    sys.unraisablehook = _quiet_unraisable

# ── config (dulu di .env, sekarang di sini) ─────────────────
# Proxy opsional. BrightData/zone lain mati = jalan kosong (PROXY='').
# Override: env GROK_PROXY="http://user:pw@host:port" atau --proxy "..."."
PROXY        = ''
TEMPIK_API   = ''  # tidak dipakai: inbox = *@arxpays.my.id, OTP lewat Gmail IMAP
TEMPIK_DOM   = ''  # domain di tempik_client.py (DOMAIN)
# Backend inbox: 'mailtm' (gratis via API, tanpa domain/Gmail) atau 'tempik'
MAIL_BACKEND = 'emailnator'
PASSWORD     = ''          # kosong = password unik per akun
HEADLESS     = True         # jendela tidak muncul, proses tetap jalan di belakang
# Satu browser per proses. Dua browser di satu IP saling bunuh Turnstile.
# Concurrency = jalankan beberapa proses, bukan beberapa tab.
MAX_PARALLEL = 1
OTP_TIMEOUT  = 90
TURNSTILE_WAIT = 12        # native solve biasanya 2-5 dtk
INSTALL_9R   = True
R9_URL       = 'http://localhost:20128'
R9_PASS      = '123456'

OUT        = Path(__file__).parent / 'sso.txt'
SIGNUP     = 'https://accounts.x.ai/sign-up?redirect=grok-com'
CREATE_URL = 'https://accounts.x.ai/api/auth/sign-up/create-account'

FIRST_NAMES = ['James','Alex','Mia','Noah','Emma','Liam','Olivia','Ethan','Ava','Lucas',
               'Sophia','Mason','Isabella','Logan','Charlotte','Daniel','Amelia','Henry',
               'Harper','Jack','Ella','Owen','Grace','Leo','Chloe','Nathan','Lily','Ryan',
               'Zoe','Max','Hannah','Felix','Ruby','Aaron','Nora','Dylan','Stella','Ian']
LAST_NAMES  = ['Smith','Johnson','Lee','Brown','Garcia','Novak','Kovacs','Kim',
               'Nguyen','Patel','Rossi','Silva','Santos','Dubois','Martin','Lopez','Harris',
               'Walker','Young','King','Wright','Bennett','Hayes','Coleman','Rivera','Foster',
               'Reyes','Owens','Ellis','Fischer','Weber','Klein','Schmidt','Beck','Hart']

GRN, RED, YEL, CYN, DIM, RST = '\033[32m', '\033[31m', '\033[33m', '\033[36m', '\033[2m', '\033[0m'
if platform.system() == 'Windows':
    try:
        import colorama
        colorama.just_fix_windows_console()
    except Exception:
        pass

def ok(msg):   print(f"  {GRN}✓{RST} {msg}", flush=True)
def no(msg):   print(f"  {RED}✗{RST} {msg}", flush=True)
def wt(msg):   print(f"  {YEL}→{RST} {msg}", flush=True)
def step(n, m): print(f"\n  {CYN}[{n:02d}]{RST} {m}", flush=True)


# ── spinner ──────────────────────────────────────────────────────
SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
SPIN_COLORS = ['\033[36m', '\033[34m', '\033[35m', '\033[91m',
               '\033[33m', '\033[32m', '\033[92m', '\033[94m']
_spin_lock = threading.Lock()
_spin_state = {'i': 0, 'c': 0}


def spin_frame():
    with _spin_lock:
        _spin_state['i'] = (_spin_state['i'] + 1) % len(SPIN)
        _spin_state['c'] = (_spin_state['c'] + 1) % len(SPIN_COLORS)
        return f"{SPIN_COLORS[_spin_state['c']]}{SPIN[_spin_state['i']]}{RST}"


def spin_clear(width=70):
    print('\r' + ' ' * width + '\r', end='', flush=True)


class FlowAbort(Exception):
    """Raised inside a probe. spin_wait re-raises this immediately."""


async def spin_wait(label, coro_fn, timeout, interval=0.4):
    """Repeat coro_fn until it returns truthy, or timeout.

    FlowAbort escapes at once — a rejected account must not sit here for the
    rest of the timeout. Other exceptions are treated as 'not yet'.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            res = await coro_fn()
            if res:
                spin_clear()
                return res
        except FlowAbort:
            spin_clear()
            raise
        except Exception:
            pass
        print(f"\r  {spin_frame()} {DIM}{label}{RST}", end='', flush=True)
        await asyncio.sleep(interval)
    spin_clear()
    return None


def rand_name():
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


def _rx(words):
    return re.compile('|'.join(re.escape(w) for w in words), re.I)


COOKIE_OK = ['Accept All Cookies', 'Accept all', 'Allow all', 'Alle akzeptieren',
             'Tout accepter', 'Aceptar todo', 'Accetta tutti', 'Aceitar tudo',
             'Принять все', 'Tümünü kabul et', 'Akceptuj wszystkie',
             'Alles accepteren', '全部接受', 'すべて許可']
EMAIL_SIGNUP = ['sign up with email', 'continue with email', 'use email',
                'mit E-Mail registrieren', "s'inscrire avec un e-mail",
                'regístrate con el correo', "registrati con l'email",
                'cadastrar com e-mail', 'зарегистрироваться с почтой',
                'e-posta ile kaydol', 'zarejestruj się przez e-mail',
                'aanmelden met e-mail', '使用邮箱注册', 'メールで登録']
EMAIL_SUBMIT = ['sign up', 'continue', 'next', 'submit', 'weiter', 'siguiente',
                'continua', 'continuar', 'suivant', 'продолжить', 'далее',
                'devam', 'dalej', 'volgende', '继续', '次へ']
OTP_HINTS = ['enter the code', 'verification code', 'check your email',
             'we sent', 'we emailed', 'code sent', 'bestätigungscode',
             'code de vérification', 'código de verificación',
             'codice di verifica', 'código de verificação', 'код подтверждения',
             'doğrulama kodu', 'kod weryfikacyjny', 'verificatiecode',
             '验证码', '確認コード']


def rand_password():
    if PASSWORD:
        return PASSWORD
    alphabet = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    body = ''.join(random.choices(alphabet, k=16))
    return f'Gk{body}!9'


def _parse_proxy(proxy):
    """'' -> (None, None). Scheme stripped BEFORE the '@' split. Otherwise
    username becomes 'http' and BrightData refuses every connection."""
    if not proxy or not proxy.strip():
        return None, None
    proxy_url = proxy
    if '://' in proxy_url:
        proxy_url = proxy_url.split('://', 1)[1]
    if '@' in proxy_url:
        auth, hostport = proxy_url.rsplit('@', 1)
        user, pw = auth.split(':', 1)
        host, port = hostport.rsplit(':', 1)
        return ({'server': f'http://{host}:{port}', 'username': user, 'password': pw},
                f'http://{user}:{pw}@{host}:{port}')
    return {'server': f'http://{proxy_url}'}, f'http://{proxy_url}'


# ── Browser ─────────────────────────────────────────────────────
_cam = None


async def start_browser(max_tries=4):
    """Launch Camoufox. BrightData hands out a dead exit about 1 in 3 times,
    so preflight through ipify and relaunch until the node answers."""
    global _cam
    from camoufox.async_api import AsyncCamoufox

    proxy_arg, _ = _parse_proxy(PROXY)
    # Direct connection: if the network is down there is nothing to retry for.
    hard_tries = 1 if not proxy_arg else max_tries
    last_err = None
    for attempt in range(hard_tries):
        cam = None
        try:
            cam = AsyncCamoufox(headless=HEADLESS, humanize=True,
                                block_images=False, block_webrtc=True,
                                locale='en-US', proxy=proxy_arg)
            await cam.start()
            browser = cam.browser
            context = await browser.new_context()
            page = await context.new_page()
            r = await page.goto('https://api.ipify.org?format=json',
                                wait_until='domcontentloaded', timeout=30000)
            ip = (await r.json()).get('ip', '?')
            ok(f"proxy IP: {ip}")
            _cam = cam
            return browser, context, page
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:140]}"
            wt(f"proxy dead (attempt {attempt+1}/{max_tries}) — {last_err}")
            if cam:
                try:
                    await cam.stop()
                except Exception:
                    pass
            await asyncio.sleep(2 + attempt * 2 + random.uniform(0, 1.5))
    raise RuntimeError(f"start_browser: no live proxy node ({last_err})")


async def stop_browser():
    global _cam
    if _cam:
        try:
            await _cam.stop()
        except Exception:
            pass
        _cam = None


async def js_click(page, el):
    try:
        await el.click(timeout=2500)
        return True
    except Exception:
        pass
    try:
        await el.evaluate("el => el.click()")
        return True
    except Exception:
        pass
    return False


# ── Turnstile ───────────────────────────────────────────────────
_TURNSTILE_JS = """
() => {
    try { var r = window.turnstile.getResponse(); if (r && r.length > 10) return r; } catch(e) {}
    var inputs = document.querySelectorAll(
        'input[name="cf-turnstile-response"], input[name*="turnstile"], input[name*="cf-"]');
    for (var i of inputs) { if (i.value && i.value.length > 20) return i.value; }
    return '';
}
"""

# Click the checkbox inside the Turnstile iframe. A widget that stays on
# "managed" never yields a token until something actually checks the box.
_CLICK_TURNSTILE_JS = """
() => {
    const fire = (el) => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const x = r.left + Math.max(8, r.width / 2);
        const y = r.top + Math.max(8, r.height / 2);
        for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
            el.dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true,
                                                clientX: x, clientY: y, button: 0}));
        }
        return true;
    };
    let n = 0;
    for (const f of document.querySelectorAll('iframe')) {
        const s = (f.src || '') + (f.title || '') + (f.id || '');
        if (!/turnstile|challenge|cloudflare/i.test(s)) continue;
        fire(f);
        n++;
        try {
            const d = f.contentDocument;
            if (!d) continue;
            const box = d.querySelector(
                'input[type="checkbox"], .ctp-checkbox-label, label, #challenge-stage');
            if (fire(box)) n++;
        } catch (e) {}
    }
    const host = document.querySelector('.cf-turnstile, [data-sitekey]');
    if (host && fire(host)) n++;
    return n;
}
"""


async def get_turnstile_token(page, timeout=TURNSTILE_WAIT):
    """Native solve first. If nothing shows up, click the checkbox and poll
    a bit longer. Returns '' when neither produced a token."""
    async def _probe():
        return await page.evaluate(_TURNSTILE_JS)

    tok = await spin_wait('Menunggu Turnstile (native)...', _probe, timeout, 0.4)
    if tok:
        return tok

    wt("Turnstile belum solve — klik checkbox")
    try:
        clicked = await page.evaluate(_CLICK_TURNSTILE_JS)
    except Exception:
        clicked = 0
    if not clicked:
        # iframe bbox from Playwright, then a real mouse click on it
        try:
            for fr in page.frames:
                if not re.search(r'turnstile|challenge|cloudflare', fr.url or '', re.I):
                    continue
                el = await fr.frame_element()
                box = await el.bounding_box()
                if box:
                    await page.mouse.click(box['x'] + 30, box['y'] + box['height'] / 2)
                    clicked = 1
                    break
        except Exception:
            pass
    if clicked:
        ok(f"checkbox Turnstile diklik ({clicked})")
    tok = await spin_wait('Menunggu token setelah klik checkbox...', _probe, 15, 0.4)
    return tok or ''


# ── 9Router (pure HTTP) ─────────────────────────────────────────
R9_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_r9 = None


def _r9_session():
    """Login sekali, simpan auth_token. Cookie 9Router di-set untuk domain
    'localhost.local' jadi jar tidak menempel ke 'localhost'; kirim manual."""
    global _r9
    if _r9:
        return _r9
    import urllib.request
    req = urllib.request.Request(
        f'{R9_URL}/api/auth/login',
        data=json.dumps({'password': R9_PASS}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.headers.get('Set-Cookie') or ''
    token = raw.split(';', 1)[0].split('=', 1)[1] if 'auth_token=' in raw else ''
    if not token:
        raise RuntimeError('9Router login tanpa auth_token')
    _r9 = token
    return token


def _r9_get(token, url):
    import urllib.request
    req = urllib.request.Request(url, headers={'Cookie': 'auth_token=' + token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


def _r9_post(token, url, payload=None):
    import urllib.request
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        'Content-Type': 'application/json', 'Cookie': 'auth_token=' + token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


def _approve_9r(sso_jwt, user_code):
    """curl_cffi saja. fetch() dari halaman kena CORS; urllib kena CF 403.
    Sidik jari browser + Referer/Origin accounts.x.ai -> approve 200."""
    from curl_cffi import requests as cr
    s = cr.Session(impersonate='chrome131')
    s.cookies.set('sso', sso_jwt, domain='.x.ai')
    s.headers.update({'Referer': 'https://accounts.x.ai/oauth2/device/consent',
                      'Origin': 'https://accounts.x.ai'})
    v = s.post('https://auth.x.ai/oauth2/device/verify',
               data={'user_code': user_code}, timeout=30)
    m = re.search(r'name="consent_token"\s+value="([^"]+)"', v.text or '')
    if not m:
        raise RuntimeError(f'verify tanpa token ({v.status_code})')
    a = s.post('https://auth.x.ai/oauth2/device/approve', data={
        'user_code': user_code, 'action': 'allow', 'principal_type': 'User',
        'principal_id': '', 'consent_token': m.group(1)}, timeout=30)
    if a.status_code != 200:
        raise RuntimeError(f'approve HTTP {a.status_code}')
    return True



# ── HTTP session + redirect chain ───────────────────────────────
def _jwt_payload(token):
    try:
        part = token.split('.')[1]
        part += '=' * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def _cookie_header(cookies, url):
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ''
    bits = []
    for c in cookies:
        dom = (c.get('domain') or '').lstrip('.')
        if dom and (host == dom or host.endswith('.' + dom)):
            bits.append(f"{c['name']}={c['value']}")
    return '; '.join(bits)


def replay_set_cookie_chain(redirect_url, cookies, proxy_url):
    """Follow create-account's redirectUrl with a cookie jar.

    Each hop is auth.<domain>/set-cookie?q=<jwt> and plants the session cookie
    for that domain. Missing a hop leaves the account logged in nowhere useful.
    Returns (cookies, sso_jwt, session_id).
    """
    import http.cookiejar
    import urllib.request

    jar = http.cookiejar.CookieJar()
    handlers = [urllib.request.HTTPCookieProcessor(jar)]
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url}))
    op = urllib.request.build_opener(*handlers)

    req = urllib.request.Request(redirect_url, headers={
        'User-Agent': R9_UA,
        'Cookie': _cookie_header(cookies, redirect_url),
    })
    try:
        with op.open(req, timeout=40) as r:
            final = r.geturl()
            r.read()
    except Exception as e:
        wt(f"redirect chain: {type(e).__name__}: {str(e)[:100]}")
        final = ''

    merged = list(cookies)
    seen = {(c.get('name'), c.get('domain')) for c in merged}
    for c in jar:
        key = (c.name, c.domain)
        if key in seen:
            continue
        seen.add(key)
        merged.append({
            'name': c.name, 'value': c.value, 'domain': c.domain,
            'path': c.path or '/', 'secure': bool(c.secure),
            'httpOnly': bool(getattr(c, '_rest', {}).get('HttpOnly')),
        })

    sso_jwt = ''
    for c in merged:
        if c.get('name') == 'sso' and '.grok.com' in (c.get('domain') or ''):
            sso_jwt = c['value']
            break
    if not sso_jwt:
        for c in merged:
            if c.get('name') == 'sso':
                sso_jwt = c['value']
                break
    session_id = (_jwt_payload(sso_jwt).get('session_id') or '') if sso_jwt else ''
    return merged, sso_jwt, session_id, final


def confirm_session(cookies, proxy_url):
    """GET grok.com/api/auth/session. Returns the JSON dict, or {}."""
    import urllib.request
    handlers = []
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url}))
    op = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(
        'https://grok.com/api/auth/session',
        headers={'User-Agent': R9_UA, 'Cookie': _cookie_header(cookies, 'https://grok.com/')})
    try:
        with op.open(req, timeout=25) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception:
        return {}


_file_lock = threading.Lock()


def append_record(rec):
    """One process, one write. A second grok.py takes the same lock via the
    file, so neither rewrites the other's line."""
    line = json.dumps(rec, ensure_ascii=False)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock:
        with open(OUT, 'a', encoding='utf-8') as f:
            if platform.system() == 'Windows':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line + '\n')
                f.flush()
            finally:
                if platform.system() == 'Windows':
                    import msvcrt
                    try:
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def update_record(email, rec):
    """Rewrite only this email's last line. Lock covers the read-modify-write."""
    line = json.dumps(rec, ensure_ascii=False)
    with _file_lock:
        fd = os.open(str(OUT), os.O_RDWR)
        try:
            if platform.system() == 'Windows':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            with os.fdopen(os.dup(fd), 'r+', encoding='utf-8') as f:
                raw = f.read()
                lines = raw.splitlines()
                for i in range(len(lines) - 1, -1, -1):
                    try:
                        row = json.loads(lines[i])
                    except Exception:
                        continue
                    if row.get('email') == email:
                        lines[i] = line
                        f.seek(0)
                        f.write('\n'.join(lines) + '\n')
                        f.truncate()
                        break
        finally:
            if platform.system() == 'Windows':
                import msvcrt
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            os.close(fd)


# ── in-page helpers ─────────────────────────────────────────────
async def _body_text(page):
    try:
        return (await page.evaluate("document.body ? (document.body.innerText || '') : ''")) or ''
    except Exception:
        return ''


async def click_labelled(page, words, timeout=12):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            b = page.get_by_role('button', name=_rx(words)).first
            if await b.count() > 0:
                if await js_click(page, b):
                    return True
        except Exception:
            pass
        try:
            el = page.get_by_text(_rx(words)).first
            if await el.count() > 0:
                if await js_click(page, el):
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.6)
    return False


async def fill_first(page, selectors, value, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for sel in selectors:
            try:
                inp = page.locator(sel).first
                if await inp.count() > 0 and await inp.is_visible():
                    await inp.fill(value)
                    return True
            except Exception:
                pass
        await asyncio.sleep(0.4)
    return False


_CREATE_JS = """
async (body) => {
    const r = await fetch(%r, {
        method: 'POST',
        credentials: 'include',
        headers: {'content-type': 'application/json', 'accept': 'application/json'},
        body: JSON.stringify(body),
    });
    let data = null;
    try { data = await r.json(); } catch (e) { data = {'raw': await r.text()}; }
    return {status: r.status, data: data};
}
""" % CREATE_URL


# ── one account ─────────────────────────────────────────────────
async def signup_one(mail):
    t0 = time.time()
    browser = context = page = None
    addr = None
    password = rand_password()
    _, proxy_url = _parse_proxy(PROXY)
    try:
        step(1, "Create arxpays.my.id inbox")
        addr = mail.create_inbox()
        ok(f"inbox: {addr}")
        signup_one.last_email = addr

        step(2, "Launch Camoufox + fresh proxy IP")
        browser, context, page = await start_browser()

        # Castle.io puts this on the send-verification-code body. Grab it
        # while the page sends it; create-account wants the same token.
        sniffed = {}

        def _on_request(req):
            if 'send-verification-code' not in req.url or req.method != 'POST':
                return
            try:
                data = json.loads(req.post_data or '{}')
            except Exception:
                return
            tok = data.get('castleRequestToken') or ''
            if tok:
                sniffed['castle'] = tok

        page.on('request', _on_request)

        step(3, "Open accounts.x.ai/sign-up")
        await page.goto(SIGNUP, wait_until='domcontentloaded', timeout=45000)
        ok("page loaded")

        step(4, "Dismiss cookie banner")
        if await click_labelled(page, COOKIE_OK, timeout=4):
            ok("cookie banner dismissed")

        step(5, "Click 'Sign up with email'")
        if not await click_labelled(page, EMAIL_SIGNUP, timeout=15):
            raise RuntimeError("cannot find 'Sign up with email'")
        ok("clicked email signup")

        step(6, f"Fill email {addr}")
        if not await fill_first(page, [
                'input[type="email"]', 'input[name="email"]',
                'input[autocomplete="email"]', 'input[name*="mail"]'], addr, 10):
            raise RuntimeError("email input not found")

        # Poll the inbox BEFORE the click. The mail often lands in 1-2s,
        # faster than a poll loop started afterwards can notice.
        since = time.time()
        otp_task = asyncio.ensure_future(
            asyncio.to_thread(mail.wait_otp, addr, OTP_TIMEOUT, since))

        if not await click_labelled(page, EMAIL_SUBMIT, timeout=8):
            otp_task.cancel()
            raise RuntimeError("email submit button not found")
        ok("submitted email")

        async def _otp_screen():
            body = (await _body_text(page)).lower()
            if any(w.lower() in body for w in OTP_HINTS):
                return True
            try:
                n = await page.locator(
                    'input[name="code"], input[autocomplete="one-time-code"], '
                    'input[inputmode="numeric"], input[maxlength="1"]').count()
                if n:
                    return True
            except Exception:
                pass
            return False

        if not await spin_wait('Menunggu layar OTP...', _otp_screen, 15, 0.4):
            otp_task.cancel()
            _dbg = await _body_text(page)
            print(f"  {DIM}[debug] url={page.url}{RST}", flush=True)
            print(f"  {DIM}[debug] body={_dbg[:500]!r}{RST}", flush=True)
            raise RuntimeError(f"email submit not confirmed (no OTP screen) | {_dbg[:200]!r}")
        ok("verification code requested")
        if sniffed.get('castle'):
            ok(f"castle token sniffed ({len(sniffed['castle'])} chars)")
        else:
            wt("castle token belum ke-sniff — create-account tetap dicoba")

        step(7, "Wait for OTP email")

        async def _otp_ready():
            if otp_task.done():
                return True
            return False

        await spin_wait(f'OTP {addr} menunggu email masuk...', _otp_ready, OTP_TIMEOUT + 5, 0.4)
        if not otp_task.done():
            otp_task.cancel()
            raise TimeoutError("OTP never arrived")
        code = otp_task.result()
        if not code:
            raise TimeoutError("OTP never arrived")
        ok(f"OTP: {code}")

        step(8, "Fill OTP code")
        otp_filled = await fill_first(page, [
            'input[name="code"]', 'input[autocomplete="one-time-code"]',
            'input[inputmode="numeric"]'], code, 8)
        if not otp_filled:
            boxes = page.locator('input[maxlength="1"]')
            n = await boxes.count()
            if n >= 6 and len(code) >= 6:
                for i in range(6):
                    await boxes.nth(i).fill(code[i])
                    await asyncio.sleep(0.05)
                otp_filled = True
        if not otp_filled:
            raise RuntimeError("OTP input not found")
        await asyncio.sleep(0.8)

        step(9, "Fill name + password")
        given, family = rand_name()
        missing = []
        for sel, val, label in (
                ('input[name="givenName"]', given, 'givenName'),
                ('input[name="familyName"]', family, 'familyName'),
                ('input[type="password"]', password, 'password')):
            if not await fill_first(page, [sel], val, 6):
                missing.append(label)
        if missing:
            # Form nama/password sering tidak dirender di flow baru; kita
            # submit lewat _CREATE_JS dengan nilai yang sama, jadi ini bukan
            # blocker — hanya dicatat, lalu lanjut.
            no(f"field tidak dirender: {', '.join(missing)} (lanjut via API)")
            try:
                dbg = await _body_text(page)
                print(f"  {DIM}[debug] body={dbg[:400]!r}{RST}", flush=True)
            except Exception:
                pass
        else:
            ok(f"identity: {given} {family}")

        step(10, "Solve Turnstile")
        tok = await get_turnstile_token(page)
        if not tok:
            no("Turnstile FAILED — akun ini diskip, tidak disubmit")
            raise RuntimeError("turnstile solve failed")
        ok(f"Turnstile token ({len(tok)} chars)")

        step(11, "Create account (API, dari dalam halaman)")
        try:
            created = await page.evaluate(_CREATE_JS, {
                'email': addr,
                'password': password,
                'givenName': given,
                'familyName': family,
                'emailValidationCode': code,
                'turnstileToken': tok,
                'castleRequestToken': sniffed.get('castle', ''),
            })
        except Exception as e:
            raise RuntimeError(f"create-account request gagal: {type(e).__name__}: {e}")

        status = (created or {}).get('status')
        data = (created or {}).get('data') or {}
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError(f"create-account ditolak: HTTP {status} {str(data)[:180]}")
        redirect = data.get('redirectUrl') or data.get('redirect_url') or ''
        session = data.get('session') or {}
        if not redirect and not session:
            raise RuntimeError(f"create-account tanpa session: {str(data)[:180]}")
        ok(f"account created (HTTP {status})")

        step(12, "Replay set-cookie chain + cek session")
        cookies = await context.cookies()
        sso_jwt = ''
        session_id = session.get('sessionId') or ''
        if redirect:
            cookies, sso_jwt, jwt_sid, final = await asyncio.to_thread(
                replay_set_cookie_chain, redirect, cookies, proxy_url)
            session_id = session_id or jwt_sid
            if final:
                ok(f"chain selesai → {final[:70]}")
            # urllib berhenti di hop pertama. Hop auth.x.ai ternyata tidak
            # menanam cookie sendiri (303 -> auth-error); yang dipakai approve
            # adalah sso .x.ai dari session browser. Langsung pakai itu.

        if not sso_jwt:
            for c in cookies:
                if c.get('name') == 'sso':
                    sso_jwt = c['value']
                    session_id = session_id or (_jwt_payload(sso_jwt).get('session_id') or '')
                    break

        authed = await asyncio.to_thread(confirm_session, cookies, proxy_url)
        if (authed.get('status') == 'authenticated'
                or (authed.get('session') or {}).get('sessionId')):
            session_id = (authed.get('session') or {}).get('sessionId') or session_id
            ok("grok.com session: AUTHENTICATED")
        elif sso_jwt:
            wt("session API tidak konfirmasi, tapi cookie sso ada — disimpan")
        else:
            raise RuntimeError("account creation not confirmed (no session, no sso)")

        rec = {
            'email': addr,
            'password': password,
            'sso_token': session_id or None,     # sessionId, bukan cookie
            'sso': sso_jwt or None,               # cookie JWT .grok.com
            'cookies': cookies,
            'created_at': int(time.time()),
        }
        append_record(rec)
        ok(f"saved → {OUT.name}")

        # Approve device flow. fetch() dari halaman kena CORS; urllib telanjang
        # kena CF 403. curl_cffi dengan sidik jari browser yang lolos.
        dc = None
        if INSTALL_9R:
            step(13, "Install to 9Router")
            try:
                dc = await asyncio.to_thread(
                    _r9_get, _r9_session(), f'{R9_URL}/api/oauth/grok-cli/device-code')
                uc = dc.get('user_code')
                if not uc:
                    raise RuntimeError(f"device-code failed: {dc.get('error', dc)}")
                await asyncio.to_thread(_approve_9r, sso_jwt, uc)
                ok("consent approved")
            except Exception as e:
                dc = None
                no(f"9Router: {type(e).__name__}: {e}")

        await stop_browser()
        browser = context = page = None
        ok("Camoufox tab ditutup (akun sudah tersimpan)")

        if dc:
            try:
                installed, info = False, 'poll timeout'
                for _ in range(12):
                    res = await asyncio.to_thread(
                        _r9_post, _r9_session(), f'{R9_URL}/api/oauth/grok-cli/poll', {
                            'deviceCode': dc['device_code'],
                            'codeVerifier': dc.get('codeVerifier', ''),
                        })
                    if res.get('success'):
                        installed, info = True, res.get('connection', {}).get('id', '?')
                        break
                    if not res.get('pending'):
                        installed, info = False, f'poll: {res}'
                        break
                    await asyncio.sleep(2)
            except Exception as e:
                installed, info = False, f'{type(e).__name__}: {e}'
            rec['installed'] = bool(installed)
            if installed:
                rec['conn_id'] = info
                ok(f"9Router: connection {info}")
            else:
                no(f"9Router: {info}")
            try:
                update_record(addr, rec)
            except Exception as e:
                wt(f"update sso.txt gagal: {e}")

        return {**rec, 'elapsed': round(time.time() - t0, 1)}

    finally:
        if addr:
            try:
                mail.delete_inbox(addr)
            except Exception:
                pass
        await stop_browser()


# ── Main ────────────────────────────────────────────────────────
BOLD = '\033[1m'
MAG  = '\033[95m'
BOX_W = 62


def _box_line(text):
    visible = re.sub(r'\033\[[0-9;]*m', '', text)
    pad = max(0, BOX_W - len(visible))
    return f"{MAG}║{RST}{text}{' ' * pad}{MAG}║{RST}"


def banner():
    bar = '═' * BOX_W
    print(f"\n{MAG}╔{bar}╗{RST}")
    print(_box_line(f"{BOLD}  G R O K   M A S S   R E G{RST}"))
    print(_box_line(f"{DIM}  hybrid · Camoufox token + HTTP signup · 9Router{RST}"))
    print(f"{MAG}╚{bar}╝{RST}\n")


def ask_count():
    print(f"  {CYN}?{RST} {BOLD}Mau berapa akun ?{RST} {DIM}(enter = 1, q = keluar){RST}")
    while True:
        try:
            raw = input(f"  {MAG}▸{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if raw.lower() in ('q', 'quit', 'exit'):
            return 0
        if not raw:
            return 1
        try:
            n = int(raw)
        except ValueError:
            print(f"  {RED}✗{RST} masukkan angka, atau 'q' untuk keluar")
            continue
        if n < 1:
            print(f"  {RED}✗{RST} minimal 1")
            continue
        if n > 50:
            mins = n * 1.5
            print(f"  {YEL}!{RST} {n} akun ≈ {mins:.0f} menit ({mins/60:.1f} jam). "
                  f"Lanjut? {DIM}(y/n){RST}")
            if input(f"  {MAG}▸{RST} ").strip().lower() not in ('y', 'yes', 'ya'):
                continue
        print(f"  {GRN}✓{RST} target: {BOLD}{n}{RST} akun\n")
        return n


async def run(count=1):
    # Pilih mail backend: mailtm | mailcx | tempik
    if MAIL_BACKEND == 'tempik':
        from tempik_client import Tempik
        mail = Tempik(TEMPIK_API, TEMPIK_DOM)
    elif MAIL_BACKEND == 'emailnator':
        from emailnator_client import Emailnator
        mail = Emailnator(TEMPIK_API, TEMPIK_DOM)
    elif MAIL_BACKEND == 'gmail_dot':
        from gmail_dot_client import GmailDot
        mail = GmailDot(TEMPIK_API, TEMPIK_DOM)
    elif MAIL_BACKEND == 'mailcx':
        from mailcx_client import MailCxClient
        mail = MailCxClient(TEMPIK_DOM)
        _orig_create = mail.create_mailbox
        mail.create_inbox = lambda: _orig_create()[0]   # grok.py mau string
        mail.wait_otp = lambda addr, timeout=90, since=None: mail.wait_for_code(
            addr, timeout=timeout)
    else:
        from mail_tm_client import MailTm
        mail = MailTm(TEMPIK_API, TEMPIK_DOM)

    banner()
    host = PROXY.split('@')[-1] if '@' in (PROXY or '') else (
        PROXY if PROXY else 'DIRECT (no proxy)')
    print(f"  {CYN}proxy{RST}  : {host}")
    print(f"  {CYN}inbox{RST}  : {MAIL_BACKEND}")
    print(f"  {CYN}mode{RST}   : hybrid (browser = token, sisanya HTTP)")
    print(f"  {CYN}install{RST}: {'9Router grok-cli ✓' if INSTALL_9R else 'OFF (--no-install)'}")
    print(f"  {CYN}target{RST} : {BOLD}{count}{RST} account(s)\n", flush=True)

    ok_n = fail_n = skip_n = 0
    fails = []
    t_start = time.time()
    for i in range(count):
        print(f"\n{CYN}┌{'─'*68}{RST}")
        print(f"{CYN}│{RST} {BOLD}ACCOUNT {i+1}/{count}{RST}")
        print(f"{CYN}└{'─'*68}{RST}")
        t_acc = time.time()
        signup_one.last_email = '?'
        email = '?'
        try:
            res = await signup_one(mail)
            email = res['email']
            ok_n += 1
            tail = ''
            if res.get('installed') is True:
                tail = f"  {GRN}✚ 9Router {str(res.get('conn_id',''))[:8]}{RST}"
            elif res.get('installed') is False:
                tail = f"  {RED}✖ 9Router: NOT installed{RST}"
            print(f"\n  {GRN}✔ SUCCESS{RST} {email}  ({res['elapsed']}s){tail}", flush=True)
        except Exception as e:
            email = getattr(signup_one, 'last_email', '?') or '?'
            reason = str(e)
            if 'turnstile' in reason.lower():
                skip_n += 1
                print(f"\n  {YEL}⚑ SKIPPED (TURNSTILE){RST} {email}: {reason}  "
                      f"({time.time()-t_acc:.1f}s) {DIM}— lanjut akun lain{RST}", flush=True)
            else:
                fail_n += 1
                print(f"\n  {RED}✖ FAILED{RST} {email}: {type(e).__name__}: {reason}  "
                      f"({time.time()-t_acc:.1f}s)", flush=True)
            fails.append((email, reason))
        print(f"  {DIM}  [{ok_n}✓ {skip_n}⚑ {fail_n}✖] sisa: {count-i-1} | "
              f"elapsed: {time.time()-t_start:.0f}s{RST}", flush=True)

    total_t = time.time() - t_start
    bar = '═' * BOX_W
    rate = ok_n / max(1, total_t / 60)
    print(f"\n{MAG}╔{bar}╗{RST}")
    print(_box_line(f"{BOLD}  RINGKASAN{RST}"))
    print(f"{MAG}╠{bar}╣{RST}")
    print(_box_line(f"  {GRN}✓ sukses{RST}     : {BOLD}{ok_n}{RST}"))
    if skip_n:
        print(_box_line(f"  {YEL}⚑ turnstile{RST}  : {BOLD}{skip_n}{RST}"))
    print(_box_line(f"  {RED}✖ gagal{RST}      : {BOLD}{fail_n}{RST}"))
    print(_box_line(f"  {CYN}⏱ waktu{RST}     : {total_t:.0f}s ({total_t/60:.1f}m)"))
    print(_box_line(f"  {CYN}⚡ rate{RST}      : {rate:.1f} akun/menit"))
    print(f"{MAG}╚{bar}╝{RST}")
    if fails:
        print(f"\n  {RED}Detail kegagalan:{RST}")
        for em, r in fails[:15]:
            print(f"    {RED}•{RST} {em}: {r[:100]}")
    return ok_n, fail_n


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--no-install' in args:
        INSTALL_9R = False
        args = [a for a in args if a != '--no-install']
    if '--install' in args:
        INSTALL_9R = True
        args = [a for a in args if a != '--install']
    # --proxy "http://user:pw@host:port" / --proxy none
    if '--proxy' in args:
        i = args.index('--proxy')
        val = args[i + 1] if i + 1 < len(args) else ''
        args = [a for j, a in enumerate(args) if j != i and j != i + 1]
        if val and val.lower() not in ('none', 'off', ''):
            PROXY = val
    else:
        PROXY = os.environ.get('GROK_PROXY', PROXY)

    # --mail=mailtm | --mail=tempik
    for a in list(args):
        if a.startswith('--mail='):
            globals()['MAIL_BACKEND'] = a.split('=', 1)[1].strip() or 'mailtm'
            args.remove(a)

    if not args:
        n = ask_count()
        if not n:
            print(f"  {DIM}keluar.{RST}")
            sys.exit(0)
    else:
        try:
            n = int(args[0])
        except ValueError:
            print(f"  {RED}✗{RST} argumen harus angka akun, bukan {args[0]!r}")
            sys.exit(2)
        if n < 1:
            print(f"  {RED}✗{RST} minimal 1")
            sys.exit(2)
    asyncio.run(run(n))
