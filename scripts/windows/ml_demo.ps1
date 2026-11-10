# Local synthetic model laboratory. Never serves real lending decisions.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path $python)) { throw 'Virtual environment missing. Run setup.bat first.' }
Push-Location $root
try {
    Write-Host 'Installing offline ML research dependencies...' -ForegroundColor Cyan
    & $python -m pip install -r requirements-ml.txt
    if ($LASTEXITCODE -ne 0) { throw 'Research dependency installation failed.' }
    Write-Host 'Training against invented synthetic outcomes (seed 42)...' -ForegroundColor Cyan
    & $python -m aadharshila.synthetic_risk_benchmark --output-dir .risk-ci --rows 640 --seed 42
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic ML research training failed.' }
    $artifact = (Resolve-Path '.risk-ci/research_model.json').Path
    $env:AADHARSHILA_RESEARCH_MODEL_PATH = $artifact
    $env:AADHARSHILA_RESEARCH_MODEL_SHA256 = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
    $env:APP_ENV = 'development'
    $env:SEED_DEMO = 'true'
    Write-Host 'Research model digest pinned for this server process.' -ForegroundColor Green
    Write-Host 'Open http://127.0.0.1:8000, then Risk model laboratory.' -ForegroundColor Green
    & (Join-Path $PSScriptRoot 'run.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Local API exited with error.' }
}
finally { Pop-Location }
