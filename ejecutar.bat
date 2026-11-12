@echo off
rem VLC Zoom Player - lanzador. Acepta un archivo como argumento ("Abrir con...").
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Primero ejecuta instalar.bat
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m vlc_zoom_player %*
