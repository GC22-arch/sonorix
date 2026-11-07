@echo off
rem Sonorix - dictado por voz. Doble clic para iniciar.
setlocal
cd /d "%~dp0"
set "VENV=%USERPROFILE%\.sonorix\venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo Preparando Sonorix por primera vez, espera un minuto...
  py -3 -m venv "%VENV%" 2>nul || python -m venv "%VENV%"
  if errorlevel 1 ( echo No encontre Python 3. Instalalo desde python.org & pause & exit /b 1 )
)
fc /b requirements.txt "%VENV%\requirements.ok" >nul 2>&1
if errorlevel 1 (
  "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || ( pause & exit /b 1 )
  copy /y requirements.txt "%VENV%\requirements.ok" >nul
)
if "%~1"=="--setup-only" exit /b 0
start "" "%VENV%\Scripts\pythonw.exe" -m sonorix %*
