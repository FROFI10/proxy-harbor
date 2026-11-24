@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" goto install
py -3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv .venv
    goto checkenv
)
python -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
if errorlevel 1 (
    echo Python 3.11+ was not found. Install 64-bit Python and enable Add Python to PATH.
    popd
    exit /b 1
)
python -m venv .venv
:checkenv
if not exist ".venv\Scripts\python.exe" (
    echo Could not create the virtual environment.
    popd
    exit /b 1
)
:install
.venv\Scripts\python.exe -m ensurepip --upgrade
if errorlevel 1 goto failed
if exist requirements-lock.txt (
    .venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-lock.txt
) else (
    .venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
)
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip check
if errorlevel 1 goto failed
echo Installation complete. Run start.bat to open Proxy Harbor.
popd
exit /b 0
:failed
echo Installation failed. Check the error above and your Internet connection.
popd
exit /b 1
