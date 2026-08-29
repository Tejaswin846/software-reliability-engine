@echo off
setlocal

echo Matrixs Zero-Code Connector
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is required.
  exit /b 1
)

echo Installing Matrixs from GitHub...
python -m pip install --upgrade git+https://github.com/Tejaswin846/software-reliability-engine.git
if errorlevel 1 exit /b 1

echo.
echo Starting Matrixs project discovery...
matrixs connect
if errorlevel 1 python -m matrixs connect

endlocal
