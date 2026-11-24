@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" (
    call setup.bat
    if errorlevel 1 goto failed
)
.venv\Scripts\python.exe run.py --open-browser %*
if errorlevel 1 goto failed
popd
exit /b 0
:failed
echo Proxy Harbor did not start. Read the error above or logs\proxyharbor.log.
pause
popd
exit /b 1
