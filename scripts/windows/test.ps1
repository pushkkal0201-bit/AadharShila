$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path $python)) { throw 'Run setup.bat first.' }
Push-Location $root
try {
    $env:PYTHONPATH = Join-Path $root 'src'
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Automated tests failed.' }
}
finally { Pop-Location }
