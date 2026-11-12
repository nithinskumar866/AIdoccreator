@echo off
setlocal
cd /d "%~dp0"
if "%DOCUMENTOR_VENV%"=="" set "DOCUMENTOR_VENV=.venv"
if not exist "%DOCUMENTOR_VENV%\Scripts\python.exe" (
  echo Setting up DocuMentor. This only happens once...
  python -m venv "%DOCUMENTOR_VENV%" || goto :failed
  "%DOCUMENTOR_VENV%\Scripts\python" -m pip install -q -r requirements.txt || goto :failed
)
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo Created .env. Add your GEMINI_API_KEY to it, then run this again for the AI tools.
)
"%DOCUMENTOR_VENV%\Scripts\python" app.py
goto :eof
:failed
echo Setup failed. If the error mentions a missing file in site-packages, move this folder to a shorter path.
pause
