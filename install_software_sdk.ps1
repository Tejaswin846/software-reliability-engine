$ErrorActionPreference = "Stop"

Write-Host "Software SDK Windows Installer"
Write-Host "=============================="
Write-Host ""

try {
    $pythonVersion = python --version
    Write-Host "Found $pythonVersion"
} catch {
    Write-Error "Python was not found. Install Python 3.10 or newer, then run this installer again."
    exit 1
}

Write-Host "Installing Software SDK from GitHub..."
python -m pip install --upgrade pip
python -m pip install --upgrade "git+https://github.com/Tejaswin846/software-reliability-engine.git"

$apiUrl = Read-Host "Software API URL [https://software-platform.onrender.com]"
if ([string]::IsNullOrWhiteSpace($apiUrl)) {
    $apiUrl = "https://software-platform.onrender.com"
}

$secureKey = Read-Host "Software API key" -AsSecureString
$apiKey = [System.Net.NetworkCredential]::new("", $secureKey).Password
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    Write-Error "API key is required."
    exit 1
}

$projectName = Read-Host "Project name [my-agent]"
if ([string]::IsNullOrWhiteSpace($projectName)) {
    $projectName = "my-agent"
}

function Invoke-SoftwareCli {
    param([string[]]$CliArgs)
    try {
        & software @CliArgs
    } catch {
        & python -m software_sdk @CliArgs
    }
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "Connecting SDK..."
Invoke-SoftwareCli @("login", "--api-url", $apiUrl, "--api-key", $apiKey, "--project-name", $projectName)
Invoke-SoftwareCli @("init", "--project-name", $projectName, "--api-url", $apiUrl, "--force")
Invoke-SoftwareCli @("test")
Invoke-SoftwareCli @("status")

Write-Host ""
Write-Host "Success. Open the dashboard:"
Write-Host "$apiUrl/dashboard"
