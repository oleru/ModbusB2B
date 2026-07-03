param(
    [string]$TaskName = "ModbusB2B",
    [switch]$RemoveFiles,
    [string]$InstallDir = "C:\Program Files\ModbusB2B"
)

$ErrorActionPreference = "Stop"

if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    throw "Run this script from an elevated PowerShell prompt."
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task $TaskName"
} else {
    Write-Host "Scheduled task $TaskName was not installed"
}

if ($RemoveFiles -and (Test-Path $InstallDir)) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
    Write-Host "Removed $InstallDir"
}
