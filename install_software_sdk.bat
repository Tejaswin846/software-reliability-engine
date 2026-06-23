@echo off
setlocal

echo Software SDK Windows Installer
echo ==============================
echo.

python --version >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer, then run this installer again.
  exit /b 1
)

echo Installing Software SDK from GitHub...
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1

python -m pip install --upgrade git+https://github.com/Tejaswin846/software-reliability-engine.git
if errorlevel 1 (
  echo SDK installation failed. Confirm Git is installed and GitHub is reachable.
  exit /b 1
)

set /p SOFTWARE_API_URL=Software API URL [https://software-platform.onrender.com]: 
if "%SOFTWARE_API_URL%"=="" set SOFTWARE_API_URL=https://software-platform.onrender.com

set /p SOFTWARE_API_KEY=Software API key: 
if "%SOFTWARE_API_KEY%"=="" (
  echo API key is required.
  exit /b 1
)

set /p SOFTWARE_PROJECT_NAME=Project name [my-agent]: 
if "%SOFTWARE_PROJECT_NAME%"=="" set SOFTWARE_PROJECT_NAME=my-agent

echo.
echo Connecting SDK...
software login --api-url "%SOFTWARE_API_URL%" --api-key "%SOFTWARE_API_KEY%" --project-name "%SOFTWARE_PROJECT_NAME%"
if errorlevel 1 python -m software_sdk login --api-url "%SOFTWARE_API_URL%" --api-key "%SOFTWARE_API_KEY%" --project-name "%SOFTWARE_PROJECT_NAME%"
if errorlevel 1 exit /b 1

software init --project-name "%SOFTWARE_PROJECT_NAME%" --api-url "%SOFTWARE_API_URL%" --force
if errorlevel 1 python -m software_sdk init --project-name "%SOFTWARE_PROJECT_NAME%" --api-url "%SOFTWARE_API_URL%" --force
if errorlevel 1 exit /b 1

software test
if errorlevel 1 python -m software_sdk test
if errorlevel 1 exit /b 1

software status
if errorlevel 1 python -m software_sdk status
if errorlevel 1 exit /b 1

echo.
echo Success. Open the dashboard:
echo %SOFTWARE_API_URL%/dashboard
endlocal
