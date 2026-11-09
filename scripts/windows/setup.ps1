# Installs the local demo in whichever drive/folder contains this repository.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $root
try {
    if (-not (Test-Path (Join-Path $root '.venv/Scripts/python.exe'))) {
        $py = Get-Command py -ErrorAction SilentlyContinue
        if ($py) { & py -3.12 -m venv .venv; if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 was not found. Install Python 3.12, then run setup.bat.' } }
        else { & python -m venv .venv; if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ must be installed and on PATH.' } }
    }
    $python = Join-Path $root '.venv/Scripts/python.exe'
    & $python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $python -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }
    if (-not $env:DATABASE_URL) { $env:DATABASE_URL = 'sqlite:///./aadharshila.db' }
    if (-not $env:APP_ENV) { $env:APP_ENV = 'development' }
    if (-not $env:SEED_DEMO) { $env:SEED_DEMO = 'true' }
    if (-not $env:UPLOAD_DIR) { $env:UPLOAD_DIR = (Join-Path $root 'var/documents') }
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    Write-Host 'Aadharshila setup complete.' -ForegroundColor Green
    Write-Host ('Location: ' + $root)
    Write-Host 'Run run.bat to start the application.'
}
finally { Pop-Location }
