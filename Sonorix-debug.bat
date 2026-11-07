@echo off
rem Igual que Sonorix.bat pero con consola visible para ver errores.
cd /d "%~dp0"
call "%~dp0Sonorix.bat" --setup-only
"%USERPROFILE%\.sonorix\venv\Scripts\python.exe" -m sonorix --panel
pause
