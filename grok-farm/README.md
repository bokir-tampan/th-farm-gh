# 🚀 Grok Farm — Mass Auto-Register Grok (accounts.x.ai)

Auto-register akun Grok/xAI massal. Browser (Camoufox) dipakai cuma buat
ngumpulin token yang gak bisa dipalsukan (Castle.io + Turnstile). Sisanya
pure HTTP — jadi halaman mati/redirect lambat gak ngeblock proses.

Hasil: **sso.txt** berisi email, password, sessionId, cookie sso (JWT), + otomatis
install ke **9Router** (device flow) kalau 9Router jalan di localhost:20128.

---

## 📋 Persyaratan

- **Windows** + **Python 3.11+** udah keinstall & masuk PATH
  (Cek: buka cmd/terminal, ketik `python --version`)
- Koneksi internet langsung (tanpa proxy) sudah cukup. Proxy opsional.
- **9Router** (opsional): kalau mau akun langsung masuk ke 9Router, pastikan
  9Router jalan (default `http://localhost:20128`, password `123456`).
  Kalau gak dipake: jalankan `run.bat --no-install`.

## 📦 Install (cukup sekali)

1. Extract folder ini ke mana aja
2. Klik dua kali **`setup.bat`**
   - Install python packages (~beberapa MB)
   - Download browser Camoufox (~500MB, hanya sekali)
3. Tunggu sampai muncul "SETUP SELESAI"

## ▶️ Pakai

Klik dua kali **`run.bat`**, atau lewat cmd/terminal:

```bat
run.bat              :: 1 akun
run.bat 5            :: 5 akun
run.bat 10 --no-install   :: 10 akun tanpa 9Router
run.bat 3 --proxy http://user:pass@host:port
```

Hasil tiap akun sukses nambah satu baris JSON di **`sso.txt`**:

```json
{"email":"...@meowx.web.id","password":"Gk...","sso_token":"...","sso":"eyJ...","cookies":[...],"installed":true,"conn_id":"..."}
```

- `sso_token` = sessionId (bisa kepake buat login/token)
- `sso` = cookie JWT domain .grok.com
- `cookies` = full cookie jar (siap di-import ke browser/klien)

## ⚙️ Konfigurasi (edit di bagian atas `grok.py`)

| Variabel | Default | Fungsi |
|---|---|---|
| `PROXY` | `''` | Proxy HTTP. Kosong = direct. Bisa juga via `--proxy` atau env `GROK_PROXY` |
| `TEMPIK_API` / `TEMPIK_DOM` | kosong | Inbox `*@arxpays.my.id`, OTP dibaca dari Gmail lewat IMAP |
| `PASSWORD` | `''` | Kosong = password random unik per akun |
| `HEADLESS` | `True` | `False` = browser muncul (buat debug) |
| `INSTALL_9R` | `True` | Install ke 9Router otomatis |
| `R9_URL` / `R9_PASS` | `localhost:20128` / `123456` | Endpoint 9Router |

## ⚠️ Catatan

- **1 browser per IP**: jangan jalankan 2 proses sekaligus di proxy/IP sama,
  Turnstile-nya saling bunuh. Buat scale: beri tiap proses proxy beda.
- Catch-all Cloudflare meneruskan semua `*@arxpays.my.id` ke satu Gmail. OTP dicocokkan ke alamat persis.
- Kalau Turnstile gak ke-solve dalam ~12 detik, akun di-skip (bukan gagal).
- OTP xAI formatnya `699-696` (strip); regex udah handle itu + anti false-positive
  dari warna CSS email (`#333333`).

## 🔧 Troubleshoot

| Masalah | Solusi |
|---|---|
| `No module named 'camoufox'` | Jalanin `setup.bat` lagi (pip install) |
| `proxy dead` / IP gak muncul | Proxy mati/banned. Ganti `PROXY` atau kosongkan (direct) |
| `Turnstile FAILED` | Rate-limit IP. Tunggu / ganti IP. Set `TURNSTILE_WAIT` lebih tinggi |
| `OTP` `333333`-style palsu | Update `tempik_client.py` (regex OTP terbaru) |
| Akun jadi tapi gak muncul di 9Router | Cek 9Router section **grok-cli** (bukan xai), atau jalankan `--no-install` |

> Untuk scale massive: jalanin beberapa `run.bat N --proxy <proxy-beda>` di
> beberapa terminal — tiap proses punya proxy beda = turnstile aman.