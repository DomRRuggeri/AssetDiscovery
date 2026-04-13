[CmdletBinding()]
param(
    [int]$Port = 8765,

    [string]$BindAddress = '0.0.0.0'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
    Write-Host "Starting local web server on $BindAddress`:$Port"
    Start-Process -FilePath $pythonPath -ArgumentList '-m', 'http.server', $Port, '--bind', $BindAddress -WorkingDirectory $PSScriptRoot | Out-Null
    Start-Sleep -Seconds 1
}
else {
    Write-Host "Using existing listener on port $Port"
}

$url = "http://localhost:$Port/viewer/"
Write-Host "Opening $url"
Start-Process $url
