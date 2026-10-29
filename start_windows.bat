@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First follow README_BN.md to create .venv and install requirements.
  exit /b 1
)
".venv\Scripts\python.exe" app.py
pause
