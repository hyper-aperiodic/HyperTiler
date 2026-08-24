@echo off
rem Creates .venv (Python 3.14) and installs pinned dependencies.
cd /d "%~dp0"
py -3.14 -m venv .venv || python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
echo Done. Run run.bat to launch HyperTiler.
