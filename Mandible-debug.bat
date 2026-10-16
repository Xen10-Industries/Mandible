@echo off
rem Developer launcher with console output (see Mandible.bat for venv lookup).
set SD_ENABLE_ASIO=1
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\VoiceFX\venv\Scripts\python.exe"
cd /d "%~dp0"
"%PY%" -m mandible
if errorlevel 1 pause
