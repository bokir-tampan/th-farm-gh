@echo off
REM ============================================================
REM  ARX GITHUB - Launcher Web Console
REM  Klik 2x -> buka panel kontrol di browser (http://127.0.0.1:8093)
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


REM cek frontend sudah di-build (dist/assets ada)?
if not exist "frontend\dist\assets" (
    echo [i] Frontend belum di-build, build dulu...
    call npm run build --prefix frontend 2>&1
)

echo.
echo  ARX GITHUB - Web Console
echo  Buka browser: http://127.0.0.1:8093
echo  (Tekan Ctrl+C di jendela ini untuk stop server)
echo.
start http://127.0.0.1:8093
"%PY%" -m web.server
pause
