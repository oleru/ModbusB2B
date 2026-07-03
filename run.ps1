$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Config = Join-Path $Root "config.example.json"

if (-not (Test-Path $VenvPython)) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python not found. Install Python 3.11+ or create .venv manually."
    }
    & $python.Source -m venv (Join-Path $Root ".venv")
    & $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")
}

& $VenvPython (Join-Path $Root "modbus_b2b_service.py") --config $Config
