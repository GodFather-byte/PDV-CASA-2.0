@echo off
cd /d "%~dp0"
python -m src.app
if errorlevel 1 pause
