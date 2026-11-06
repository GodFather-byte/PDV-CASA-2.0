@echo off
cd /d "%~dp0"
python -m src.app --edicao willadega
if errorlevel 1 pause
