$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path $python)) { throw 'Environment missing. Run setup.bat first.' }
Push-Location $root
try {
    if (-not $env:DATABASE_URL) { $env:DATABASE_URL = 'sqlite:///./aadharshila.db' }
    if (-not $env:APP_ENV) { $env:APP_ENV = 'development' }
    if (-not $env:SEED_DEMO) { $env:SEED_DEMO = 'true' }
    if (-not $env:UPLOAD_DIR) { $env:UPLOAD_DIR = (Join-Path $root 'var/documents') }
    & $python -m uvicorn aadharshila.main:app --host 127.0.0.1 --port 8000
    if ($LASTEXITCODE -ne 0) { throw 'The API process stopped with an error.' }
}
finally { Pop-Location }
