# Create the venv, install ag-trace editable with dev tools, run the offline tests.
# Usage (from this folder):  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
.\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" --quiet
if ($LASTEXITCODE -ne 0) { throw "install failed" }

.\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "tests failed" }
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ag-trace.exe --version
Write-Host "`nReady. Activate with: .\.venv\Scripts\Activate.ps1"
