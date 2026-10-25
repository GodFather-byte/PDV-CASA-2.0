@echo off
cd /d "%~dp0"
python -m src.app --edicao ea_superacoes
if errorlevel 1 pause
