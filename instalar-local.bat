@echo off
rem Motor local gratis y offline (faster-whisper). Respaldo cuando no hay internet o cupo de Groq.
cd /d "%~dp0"
set "VENV=%USERPROFILE%\.sonorix\venv"
if not exist "%VENV%\Scripts\python.exe" ( echo Ejecuta primero Sonorix.bat & pause & exit /b 1 )
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-local.txt
echo.
echo Listo. El modelo se descarga solo la primera vez que se usa. Reinicia Sonorix.
pause
