$ErrorActionPreference = "Stop"

Write-Host "Matrixs Zero-Code Connector"
Write-Host ""

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.10 or newer is required."
}

Write-Host "Installing Matrixs from GitHub..."
python -m pip install --upgrade "git+https://github.com/Tejaswin846/software-reliability-engine.git"

Write-Host ""
Write-Host "Starting Matrixs project discovery..."
if (Get-Command matrixs -ErrorAction SilentlyContinue) {
    matrixs connect
} else {
    python -m matrixs connect
}
