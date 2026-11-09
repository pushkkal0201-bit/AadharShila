$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path $python)) { throw 'Run setup.bat first.' }
Push-Location $root
try {
    if (-not $env:DATABASE_URL) { $env:DATABASE_URL = 'sqlite:///./aadharshila.db' }
    if (-not $env:UPLOAD_DIR) { $env:UPLOAD_DIR = (Join-Path $root 'var/documents') }
    & $python -m aadharshila.worker
}
finally { Pop-Location }
