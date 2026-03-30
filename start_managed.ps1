$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

$venvDir = ".venv"
$pythonExe = "python"

if (-not (Get-Command $pythonExe -ErrorAction SilentlyContinue)) {
    $pythonExe = "py"
}

if (-not (Get-Command $pythonExe -ErrorAction SilentlyContinue)) {
    Write-Host "Python was not found. Install Python 3.10+ and add it to PATH." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $venvDir)) {
    Write-Host "Creating virtual environment..."
    & $pythonExe -m venv $venvDir
    Write-Host "Virtual environment ready."
}

$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "The virtual environment looks broken. Delete .venv and try again." -ForegroundColor Red
    exit 1
}

$marker = Join-Path $venvDir ".deps_installed"
$requirements = "requirements.txt"
$needInstall = $true

if ((Test-Path $marker) -and (Test-Path $requirements)) {
    $needInstall = (Get-Item $requirements).LastWriteTime -gt (Get-Item $marker).LastWriteTime
}

if ($needInstall) {
    Write-Host "Installing dependencies..."
    & $venvPython -m pip install -q -r $requirements
    New-Item -ItemType File -Path $marker -Force | Out-Null
    Write-Host "Dependencies ready."
}

Write-Host ""
Write-Host "========================================="
Write-Host "  OCR Reader (managed window mode)"
Write-Host "  Closing the dedicated browser window stops the app"
Write-Host "========================================="
Write-Host ""

& $venvPython "managed_launcher.py" `
    --server-python $venvPython `
    --url "http://localhost:8080" `
    --cwd $PSScriptRoot
