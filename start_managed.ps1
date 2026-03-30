$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

$venvDir = ".venv"
$pythonExe = "python"

if (-not (Get-Command $pythonExe -ErrorAction SilentlyContinue)) {
    $pythonExe = "py"
}

if (-not (Get-Command $pythonExe -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 Python。请先安装 Python 3.10+ 并加入 PATH。" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $venvDir)) {
    Write-Host "正在创建虚拟环境..."
    & $pythonExe -m venv $venvDir
    Write-Host "虚拟环境创建完成。"
}

$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "虚拟环境损坏，请删除 .venv 后重试。" -ForegroundColor Red
    exit 1
}

$marker = Join-Path $venvDir ".deps_installed"
$requirements = "requirements.txt"
$needInstall = $true

if ((Test-Path $marker) -and (Test-Path $requirements)) {
    $needInstall = (Get-Item $requirements).LastWriteTime -gt (Get-Item $marker).LastWriteTime
}

if ($needInstall) {
    Write-Host "正在安装依赖..."
    & $venvPython -m pip install -q -r $requirements
    New-Item -ItemType File -Path $marker -Force | Out-Null
    Write-Host "依赖安装完成。"
}

Write-Host ""
Write-Host "========================================="
Write-Host "  外文文献阅读器（受控窗口模式）"
Write-Host "  关闭专用浏览器窗口后将自动结束应用"
Write-Host "========================================="
Write-Host ""

& $venvPython "managed_launcher.py" `
    --server-python $venvPython `
    --url "http://localhost:8080" `
    --cwd $PSScriptRoot
