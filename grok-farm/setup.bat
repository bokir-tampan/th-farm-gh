@echo off
REM ============================================================
REM  Grok Farm - Setup dependencies (Windows)
REM  Jalankan sekali:  setup.bat
REM  Butuh: Python 3.11+ sudah terinstall dan masuk PATH
REM ============================================================
title Grok Farm - Setup
echo.
echo  ============================================
echo   GROK FARM - INSTALL DEPENDENCIES
echo  ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  [X] Python tidak ketemu. Install dulu dari https://www.python.org/downloads/
    echo      (centang "Add Python to PATH" saat install)
    pause
    exit /b 1
)

echo  [1/2] Install python packages (camoufox + deps)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo  [X] Gagal install packages. Cek koneksi internet / proxy.
    pause
    exit /b 1
)

echo  [2/2] Download Camoufox browser (~500MB, sekali doang)...
python -m camoufox fetch
if errorlevel 1 (
    echo  [X] Gagal download browser. Coba jalankan ulang setup.bat.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo   SETUP SELESAI. Sekarang jalankan  run.bat
echo  ============================================
echo.
pause