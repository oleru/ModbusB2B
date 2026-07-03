param(
    [string]$InstallDir = "C:\Program Files\ModbusB2B",
    [string]$TaskName = "ModbusB2B",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    throw "Run this script from an elevated PowerShell prompt."
}

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $InstallDir "logs") -Force | Out-Null

Copy-Item -LiteralPath (Join-Path $SourceDir "ModbusB2B.exe") -Destination $InstallDir -Force
Copy-Item -LiteralPath (Join-Path $SourceDir "install-autostart.ps1") -Destination $InstallDir -Force
Copy-Item -LiteralPath (Join-Path $SourceDir "uninstall-autostart.ps1") -Destination $InstallDir -Force

if (-not (Test-Path (Join-Path $InstallDir "config.json"))) {
    Copy-Item -LiteralPath (Join-Path $SourceDir "config.json") -Destination $InstallDir -Force
}
if (-not (Test-Path (Join-Path $InstallDir "registers.json"))) {
    Copy-Item -LiteralPath (Join-Path $SourceDir "registers.json") -Destination $InstallDir -Force
}

$ExePath = Join-Path $InstallDir "ModbusB2B.exe"
$ConfigPath = Join-Path $InstallDir "config.json"
$LogPath = Join-Path $InstallDir "logs\service.log"
$Arguments = "--config `"$ConfigPath`" --log-file `"$LogPath`""

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$Action = New-ScheduledTaskAction -Execute $ExePath -Argument $Arguments -WorkingDirectory $InstallDir
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 0)
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "Modbus B2B bridge with two TCP slave endpoints."
Register-ScheduledTask -TaskName $TaskName -InputObject $Task | Out-Null

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
}

Write-Host "Installed $TaskName"
Write-Host "Install dir: $InstallDir"
Write-Host "Config:      $ConfigPath"
Write-Host "Log:         $LogPath"
Write-Host "Debug UI:    http://127.0.0.1:8080"
