$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path $python)) { throw 'Run setup.bat first.' }
Push-Location $root
try {
    $env:PYTHONPATH = Join-Path $root 'src'
    & $python -c 'import pandas, numpy, sklearn'
    if ($LASTEXITCODE -ne 0) { throw 'ML dependencies are missing. Run setup.bat to install requirements-ml.txt before test.bat.' }
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Automated tests failed.' }
}
finally { Pop-Location }
