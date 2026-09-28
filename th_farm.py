#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TokenHarbor Farm — VPS-optimized (3 temp-mail fallback, no Captcha, no proxy).
Alur terverifikasi: signup 303 -> send verification -> poll inbox -> verify link
-> enable free models -> create API key -> validate via /v1/models.

Usage:
  python3 th_farm.py            # interactive, tanya jumlah
  python3 th_farm.py N          # langsung N akun
  python3 th_farm.py N --quiet  # headless (tanpa spinner), cocok cron
"""
import requests, re, json, uuid, time, sys, os, random, threading, argparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONUNBUFFERED", "1")

BASE = "https://tokenharbor.ai"
PW_PREFIX = "ThR3c0n!"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "akun.txt")
OUT_FULL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "akun_full.txt")
TZS = ["Asia/Jakarta", "Asia/Singapore", "Asia/Tokyo", "Asia/Bangkok",
       "Europe/London", "Europe/Berlin", "America/New_York", "Asia/Dubai"]

# Rate limit IP: ~5-10 signup/IP, lalu "human check" (needCaptcha) ~30 menit.
# Batch otomatis: setelah setiap akun ke-N, istirahat lalu lanjut.
BATCH_SIZE = 5
BATCH_WAIT = 3600   # 60 menit tunggu antar batch (rate limit gate ~1 jam)

# Slot Capsolver OPSIONAL — isi via env CAPSOLVER_KEY (contoh: CAP-xxx)
CAPSOLVER_KEY = os.environ.get("CAPSOLVER_KEY", "")
TURNSTILE_SITEKEY = "0x4AAAAAADBuC8Knz1EJZx9-"

# ── temp mail providers ─────────────────────────────────────────────────
TMPL = "https://api.tempmail.lol/v2"          # provider 1
NOOP = "https://noopmail.org/api"             # provider 2
AWSM = "https://ypq5oi3ui3.execute-api.us-east-1.amazonaws.com/prod"  # provider 3

def get_temp_email():
    """Coba tempmail.lol -> noopmail -> AWS. Return (email, provider)."""
    try:
        r = requests.get(f"{TMPL}/inbox/create", timeout=18)
        j = r.json()
        if j.get("address"):
            return j["address"], j["token"], "tempmail"
    except Exception:
        pass
    try:
        dm = requests.get(f"{NOOP}/rd", timeout=15).json()["dm"]
        local = "th" + uuid.uuid4().hex[:10]
        return f"{local}@{dm}", f"{local}|{dm}", "noopmail"
    except Exception:
        pass
    try:
        j = requests.get(f"{AWSM}/get-email", params={"premium": "true"},
                         headers={"user-agent": "okhttp/4.12.0"}, timeout=18).json()
        if j.get("email"):
            return j["email"], j.get("reservationId", ""), "aws"
    except Exception:
        pass
    return None, None, None

def poll_verify_link(email, token, provider, timeout=300):
    """Poll inbox sampai nemu link verify-email?token=..."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if provider == "tempmail":
                r = requests.get(f"{TMPL}/inbox", params={"token": token}, timeout=12)
                for m in r.json().get("emails", []):
                    txt = str(m.get("text", "")) + " " + str(m.get("html", ""))
                    m2 = re.search(r"verify-email\?token=([A-Za-z0-9_\-]+)", txt)
                    if m2:
                        return f"{BASE}/verify-email?token={m2.group(1)}"
            elif provider == "noopmail":
                local, dm = token.split("|")
                msgs = requests.post(f"{NOOP}/c", json={"e": local, "d": dm}, timeout=12).json()
                for m in (msgs if isinstance(msgs, list) else []):
                    txt = str(m.get("body", "")) + str(m.get("html", ""))
                    m2 = re.search(r"verify-email\?token=([A-Za-z0-9_\-]+)", txt)
                    if m2:
                        return f"{BASE}/verify-email?token={m2.group(1)}"
            else:  # aws
                r = requests.get(f"{AWSM}/get-emails-by-address",
                                 params={"email": email, "premium": "true",
                                         "timestamp": int(time.time() * 1000)},
                                 headers={"user-agent": "okhttp/4.12.0"}, timeout=12)
                for m in r.json().get("emails", []):
                    raw = str(m.get("content", "")) + " " + str(m.get("subject", ""))
                    m2 = re.search(r"verify-email\?token=([A-Za-z0-9_\-]+)", raw)
                    if m2:
                        return f"{BASE}/verify-email?token={m2.group(1)}"
        except Exception:
            pass
        time.sleep(2.5)
    return None

# ── ansi / spinner (dari push.py, dirapikan) ───────────────────────────
R = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
C = "\033[36m"; G = "\033[32m"; Y = "\033[33m"; RD = "\033[31m"; MG = "\033[35m"
SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

class Spin:
    def __init__(self, label):
        self.label = label; self.on = True; self.f = "…"; self._lock = threading.Lock()
    def _run(self):
        i = 0
        while self.on:
            with self._lock:
                sys.stdout.write(f"\r  {C}{SPIN[i % len(SPIN)]}{R} {self.label} {DIM}{self.f}{R}   ")
                sys.stdout.flush()
            i += 1; time.sleep(0.08)
        with self._lock:
            sys.stdout.write("\r" + " " * 100 + "\r"); sys.stdout.flush()
    def start(self):
        sys.stdout.write("\033[?25l"); sys.stdout.flush()
        self.t = threading.Thread(target=self._run, daemon=True); self.t.start()
    def set(self, f="…"):
        with self._lock: self.f = f
    def stop(self, mark, msg, color):
        self.on = False
        if hasattr(self, "t") and self.t: self.t.join(timeout=0.3)
        time.sleep(0.05)
        sys.stdout.write("\033[?25h"); sys.stdout.flush()
        sys.stdout.write(f"\r  {color}{mark}{R} {msg}\n"); sys.stdout.flush()

def get_ua():
    ver = random.randint(122, 131)
    os_ = random.choice(["Windows NT 10.0; Win64; x64", "Windows NT 11.0; Win64; x64",
                         "Macintosh; Intel Mac OS X 10_15_7", "X11; Linux x86_64"])
    return (f"Mozilla/5.0 ({os_}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{ver}.0.0.0 Safari/537.36")

def is_signup_ok(r):
    if r.status_code == 303:
        return True
    txt = (r.text or "")[:4000]
    if re.search(r'"error"\s*:\s*"[^"]{3,}', txt):
        return False
    if "turnstile" in txt.lower() and "failed" in txt.lower():
        return False
    if r.status_code == 200 and ("verify" in txt.lower() or "dashboard" in txt.lower()):
        return True
    return False

def solve_turnstile(page_url=BASE + "/login?mode=signup"):
    """Capsolver: antiTurnstileTaskProxyLess → token. Kembalikan string token atau None."""
    if not CAPSOLVER_KEY or not CAPSOLVER_KEY.startswith("CAP-"):
        return None
    try:
        r = requests.post("https://api.capsolver.com/createTask", json={
            "clientKey": CAPSOLVER_KEY,
            "task": {"type": "AntiTurnstileTaskProxyLess",
                     "websiteURL": page_url, "websiteKey": TURNSTILE_SITEKEY}
        }, timeout=30)
        j = r.json()
        if j.get("errorCode"):
            return None
        tid = j.get("taskId")
        if not tid:
            return None
        for _ in range(60):
            time.sleep(2)
            rr = requests.post("https://api.capsolver.com/getTaskResult",
                               json={"clientKey": CAPSOLVER_KEY, "taskId": tid}, timeout=20)
            res = rr.json()
            if res.get("status") == "ready":
                return res.get("solution", {}).get("token")
            if res.get("status") == "failed":
                return None
    except Exception:
        return None
    return None

# ── core flow ───────────────────────────────────────────────────────────
def farm_one(di, quiet=False, sp_outer=None):
    sp = Spin("creating account") if not quiet else None
    if sp: sp.start()
    try:
        # 1. temp mail
        if sp: sp.set("get temp mail…")
        mail, tok, prov = get_temp_email()
        if not mail:
            if sp: sp.stop("✖", "gagal dapat temp mail (semua provider)", RD)
            return None

        # 2. signup (VPS direct, tanpa Turnstile — opsional di server)
        if sp: sp.set(f"registering {mail}…")
        UA = get_ua()
        pw = PW_PREFIX + uuid.uuid4().hex[:8] + "X"
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Origin": BASE})
        r = s.get(f"{BASE}/login?mode=signup", timeout=40)
        dpl = (re.findall(r'data-dpl-id="(dpl_[a-zA-Z0-9]+)"', r.text) or ["x"])[0]
        hashes = re.findall(r'[a-f0-9]{40,64}', r.text)
        h = hashes[0] if hashes else ""
        bnd = "----WebKitFormBoundary" + uuid.uuid4().hex[:16]
        def fld(n, v):
            return f'--{bnd}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'
        if "/verify-email" in h or not h:
            # hash action tak selalu muncul di halaman login; fallback dari probe
            hashes2 = re.findall(r'[a-f0-9]{40,64}', r.text)
            h = hashes2[0] if hashes2 else h

        ts_token = ""
        body = (fld("1_device_fingerprint", str(uuid.uuid4())) +
                fld("1_timezone", random.choice(TZS)) + fld("1_next", "") +
                fld("1_email", mail) + fld("1_password", pw) + fld("1_invite_code", "") +
                fld("1_cf-turnstile-response", ts_token) +
                fld("cf-turnstile-response", ts_token) +
                fld("0", '["$undefined","$K1"]') + f"--{bnd}--\r\n")
        r2 = s.post(f"{BASE}/login?mode=signup", headers={
            "Content-Type": f"multipart/form-data; boundary={bnd}", "next-action": h,
            "Accept": "text/x-component", "Referer": f"{BASE}/login?mode=signup",
            "x-deployment-id": dpl, "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin", "User-Agent": UA}, data=body.encode(),
            timeout=50, allow_redirects=False)
        if not is_signup_ok(r2):
            err = re.search(r'"error"\s*:\s*"([^"]{3,120})"', r2.text or "")
            why = err.group(1) if err else f"status {r2.status_code}"
            need_captcha = "human check" in (r2.text or "") or "needCaptcha" in (r2.text or "")
            if need_captcha:
                ts_token = solve_turnstile()
                if ts_token:
                    if sp: sp.set("retry dengan turnstile token…")
                    bnd2 = "----WebKitFormBoundary" + uuid.uuid4().hex[:16]
                    def fld2(n, v):
                        return f'--{bnd2}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'
                    body2 = (fld2("1_device_fingerprint", str(uuid.uuid4())) +
                             fld2("1_timezone", random.choice(TZS)) + fld2("1_next", "") +
                             fld2("1_email", mail) + fld2("1_password", pw) + fld2("1_invite_code", "") +
                             fld2("1_cf-turnstile-response", ts_token) +
                             fld2("cf-turnstile-response", ts_token) +
                             fld2("0", '["$undefined","$K1"]') + f"--{bnd2}--\r\n")
                    r2 = s.post(f"{BASE}/login?mode=signup", headers={
                        "Content-Type": f"multipart/form-data; boundary={bnd2}", "next-action": h,
                        "Accept": "text/x-component", "Referer": f"{BASE}/login?mode=signup",
                        "x-deployment-id": dpl, "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
                        "sec-fetch-site": "same-origin", "User-Agent": UA}, data=body2.encode(),
                        timeout=50, allow_redirects=False)
                else:
                    return "RATE_LIMITED"
            if not is_signup_ok(r2):
                err = re.search(r'"error"\s*:\s*"([^"]{3,120})"', r2.text or "")
                why = err.group(1) if err else f"status {r2.status_code}"
                if sp: sp.stop("✖", f"{mail} — signup rejected ({why[:60]})", RD)
                return None

        # 3. kirim email verifikasi + polling
        try:
            s.post(f"{BASE}/api/me/send-verification-email", timeout=20)
        except Exception:
            pass
        if sp: sp.set("waiting email…")
        link = poll_verify_link(mail, tok, prov)

        # 4. klik link verifikasi
        if link:
            if sp: sp.set("activating…")
            try:
                rv = s.get(link, timeout=40, allow_redirects=True)
                if "verify=success" not in (rv.url or "") and "login" in (rv.url or ""):
                    link = None
            except Exception:
                link = None
        if not link:
            if sp: sp.stop("✖", f"{mail} — email never arrived / verify failed", RD)
            return None

        # 5. enable free models + buat key
        try:
            s.post(f"{BASE}/api/me/privacy", json={"free_models_enabled": True},
                   headers={"Content-Type": "application/json", "User-Agent": UA}, timeout=20)
            rk = s.post(f"{BASE}/api/keys", json={"label": f"auto-{di}"},
                        headers={"Content-Type": "application/json", "User-Agent": UA}, timeout=20)
            k = (rk.json() or {}).get("plaintext")
        except Exception as e:
            if sp: sp.stop("✖", f"{mail} — keygen: {str(e)[:40]}", RD)
            return None
        if not k:
            if sp: sp.stop("✖", f"{mail} — key generation failed", RD)
            return None

        # 6. validasi via /v1/models
        rc = None
        for _ in range(3):
            try:
                rc = requests.get(f"{BASE}/v1/models",
                                  headers={"Authorization": f"Bearer {k}", "User-Agent": UA},
                                  timeout=12)
                if rc.status_code in (200, 401, 403):
                    break
            except Exception:
                pass
            rc = None; time.sleep(1)
        if rc is None or rc.status_code != 200:
            why = "timeout" if rc is None else f"invalid ({rc.status_code})"
            if sp: sp.stop("✖", f"{mail} — key {why}", RD)
            return None

        with open(OUT, "a", encoding="utf-8") as f:
            f.write(f"{k}\n")
        with open(OUT_FULL, "a", encoding="utf-8") as f:
            f.write(f"{mail}:{pw}:{k} [{prov}]\n")
        if sp:
            sp.stop("✔", f"{mail}  {DIM}·{R}  {G}{k[:28]}…{R}  {DIM}({prov}){R}", G)
        else:
            print(f"  ✔ {mail}  ·  {k}  ({prov})")
        return k
    except Exception as e:
        if sp: sp.stop("✖", f"{str(e)[:60]}", RD)
        return None
    finally:
        if sp and sp.on: sp.on = False

def countdown(seconds, label="tunggu reset"):
    for i in range(seconds, 0, -1):
        m, s = divmod(i, 60)
        sys.stdout.write(f"\r  {DIM}⏳ {label}: {m:02d}:{s:02d}{R}   ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 50 + "\r"); sys.stdout.flush()

def main():
    ap = argparse.ArgumentParser(description="TokenHarbor Farm VPS — auto batch + cooldown")
    ap.add_argument("n", nargs="?", type=int, default=None, help="Jumlah akun target")
    ap.add_argument("--quiet", action="store_true", help="Headless (tanpa spinner)")
    ap.add_argument("--batch", type=int, default=BATCH_SIZE, help=f"Akun per batch (default {BATCH_SIZE})")
    ap.add_argument("--wait", type=int, default=BATCH_WAIT, help=f"Detik tunggu antar batch (default {BATCH_WAIT})")
    args = ap.parse_args()

    target = args.n
    if target is None:
        try:
            target = int(input(f"  {C}▸{R} Jumlah akun: ").strip())
        except (EOFError, KeyboardInterrupt, ValueError):
            print(); return
    if target < 1:
        print(f"  {RD}minimal 1{R}"); return
    print(f"  {DIM}target: {target} akun | batch: {args.batch} | cooldown: {args.wait}s{R}")
    if CAPSOLVER_KEY:
        print(f"  {G}Capsolver: aktif{R}")
    else:
        print(f"  {DIM}Capsolver: OFF (RATE_LIMITED → tunggu {args.wait}s){R}")
    print()

    ok = 0; t_all = time.time(); total_gated = 0
    i = 0
    while i < target:
        done_in_batch = 0
        while done_in_batch < args.batch and i < target:
            result = farm_one(i, quiet=args.quiet)
            if result == "RATE_LIMITED":
                total_gated += 1
                print(f"\n  {Y}⚡ IP rate-limited (needCaptcha){R}")
                print(f"  {DIM}akun tersisa: {target - i}{R}")
                if CAPSOLVER_KEY:
                    print(f"  {DIM}→ Capsolver aktif, retry 3 detik…{R}")
                    time.sleep(3)
                    continue
                # tanpa Capsolver → break keluar batch, tunggu di cooldown
                break
            if result:
                ok += 1
            i += 1
            done_in_batch += 1

        if i >= target:
            break

        # inter-batch cooldown (atau setelah first gate)
        if CAPSOLVER_KEY:
            print(f"  {DIM}Capsolver ON → lanjut, {total_gated}× gated{R}")
            time.sleep(2); continue
        if total_gated > 2:
            print(f"\n  {RD}⛔ IP masih gated setelah beberapa percobaan. Coba lagi ~1 jam lagi atau pakai CAPSOLVER_KEY.{R}")
            break
        remaining = target - i
        print(f"\n  {C}⏳ Menunggu {args.wait}s sebelum coba lagi ({remaining} akun tersisa){R}")
        countdown(args.wait, "rate limit reset")
        print(f"  {G}→ Lanjut farming…{R}\n")

    print()
    print(f"  {B}DONE{R}  {G}✔ {ok} success{R}  {RD}✖ {target - ok} failed{R}   {DIM}in {time.time() - t_all:.0f}s{R}")
    print(f"  {DIM}keys →{R} {OUT}")
    print(f"  {DIM}full →{R} {OUT_FULL}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {Y}aborted{R}\n"); sys.exit(0)