@echo off
rem Inicia o sistema e abre o navegador. Feche esta janela para encerrar o sistema.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente virtual nao encontrado. Rode: python -m venv .venv  e  pip install -r requirements.txt
  pause
  exit /b 1
)
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:5000"
".venv\Scripts\python.exe" app.py
pause