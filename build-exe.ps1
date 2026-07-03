$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$ReleaseDir = Join-Path $Root "release\ModbusB2B"
$DistExe = Join-Path $Root "dist\ModbusB2B.exe"
$ZipPath = Join-Path $Root "release\ModbusB2B.zip"

if (-not (Test-Path $VenvPython)) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python not found. Install Python 3.11+ or create .venv manually."
    }
    & $python.Source -m venv (Join-Path $Root ".venv")
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")
& $VenvPython -m pip install pyinstaller

& $VenvPython -m PyInstaller `
    --clean `
    --onefile `
    --name ModbusB2B `
    --collect-all pymodbus `
    (Join-Path $Root "modbus_b2b_service.py")

if (Test-Path $ReleaseDir) {
    Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

Copy-Item -LiteralPath $DistExe -Destination (Join-Path $ReleaseDir "ModbusB2B.exe")
Copy-Item -LiteralPath (Join-Path $Root "config.example.json") -Destination (Join-Path $ReleaseDir "config.json")
Copy-Item -LiteralPath (Join-Path $Root "config.mixed.example.json") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $Root "config.external.example.json") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $Root "config.localhost.example.json") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $Root "registers.example.json") -Destination (Join-Path $ReleaseDir "registers.json")
Copy-Item -LiteralPath (Join-Path $Root "install-autostart.ps1") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $Root "uninstall-autostart.ps1") -Destination $ReleaseDir
Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination $ReleaseDir

$configPath = Join-Path $ReleaseDir "config.json"
$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
$config.registers.definitions_file = "registers.json"
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configPath -Encoding UTF8

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $ReleaseDir "*") -DestinationPath $ZipPath -Force

Write-Host "Built: $ReleaseDir"
Write-Host "Zip:   $ZipPath"
