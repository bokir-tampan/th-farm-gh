@echo off
REM ============================================================
REM  ARX GITHUB - Launcher CLI Farm
REM  Klik 2x -> langsung farm akun GitHub
REM ============================================================
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
if exist "C:\Python314\python.exe" (
    set PY=C:\Python314\python.exe
) else (
    set PY=python
)


REM cek config.json sudah diisi Gmail asli?
findstr /C:"CONTOH@gmail.com" config.json >nul 2>&1 && (
    echo [ERROR] config.json masih pakai CONTOH@gmail.com
    echo Edit config.json - isi gmail_address + gmail_app_password asli.
    pause
    exit /b 1
)

echo ============================================
echo   ARX GITHUB - Account Farm
echo   Gmail dot-trick + Camoufox + proxy
echo ============================================
echo.

set /p COUNT="Berapa akun? [5]: "
if "%COUNT%"=="" set COUNT=5

echo.
echo Mulai farming %COUNT% akun...
echo Log: farm.log (biarkan jendela ini terbuka)
echo.

REM log append biar histori farm ke-record
"%PY%" main.py --count %COUNT% >> farm.log 2>&1
set RC=%ERRORLEVEL%

echo.
echo ============================================
if %RC%==0 (
    echo  SELESAI - lihat accounts\github_accounts_*.txt
) else (
    echo  SELESAI (ada kegagalan) - cek farm.log
)
echo  TOTP/recovery: accounts\recovery\
echo ============================================
pause
