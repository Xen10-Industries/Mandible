@echo off
rem Developer launcher: runs Mandible from source using .venv in the repo root
rem (falls back to the older %LOCALAPPDATA%\VoiceFX\venv if .venv does not exist).
set SD_ENABLE_ASIO=1
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\VoiceFX\venv\Scripts\pythonw.exe"
start "" /D "%~dp0" "%PY%" -m mandible
