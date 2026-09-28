@echo off
REM ============================================================
REM  Grok Farm - Jalankan (Windows)
REM  Simpan hasil account di sso.txt
REM  Opsional: --no-install  = skip instal ke 9Router
REM            --proxy URL   = pake proxy (default direct)
REM  Contoh:
REM    run.bat                -> buat 1 akun
REM    run.bat 5              -> buat 5 akun
REM    run.bat 10 --no-install
REM    run.bat 3 --proxy http://user:pass@host:port
REM ============================================================
title Grok Farm
python grok.py %*
echo.
pause