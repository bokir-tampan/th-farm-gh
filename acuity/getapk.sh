#!/usr/bin/env bash
# Unduh APK com.acuityai (Acuity Studios) dari Google Play via apkeep.
# apkeep --app com.acuityai google-play  (butuh akun google opsional; versi ini
# pakai endpoint play yang bisa diakses anon untuk sebagian app).
set -e
mkdir -p apk && cd apk
[ -x apkeep ] || {
  curl -sL -o apkeep "https://github.com/EFForg/apkeep/releases/download/1.1.0/apkeep-x86_64-unknown-linux-gnu"
  chmod +x apkeep
}
./apkeep --version || true
echo "=== via apkpure ==="
./apkeep -a com.acuityai -d apkpure . 2>&1 | tail -5 || true
echo "=== via google-play (anon) ==="
./apkeep -a com.acuityai -d google-play . 2>&1 | tail -5 || true
ls -la
