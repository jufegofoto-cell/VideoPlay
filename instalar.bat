@echo off
rem VLC Zoom Player - instalacion (crea .venv e instala dependencias)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if errorlevel 1 (
  echo No se pudo crear el entorno virtual. Instala Python 3.10+ de 64 bits desde python.org
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo.
echo Listo. Ejecuta ejecutar.bat (requiere VLC de 64 bits instalado).
pause
