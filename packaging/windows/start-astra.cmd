@echo off
cd /d "%~dp0\..\.."
if exist ".venv\Scripts\python.exe" (
  start "" /min ".venv\Scripts\python.exe" -m astra_pc daemon
) else (
  start "" /min python -m astra_pc daemon
)
