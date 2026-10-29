$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    & '.venv/Scripts/python.exe' -m pip install -r requirements-lock.txt
}
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Write-Host 'Paper Trail Agent: http://127.0.0.1:8765'
& '.venv/Scripts/python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8765
