[CmdletBinding()]
param(
    [string]$OutputPath = '.\data\oui-registry.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

Write-Host "Building OUI registry at $OutputPath"
$result = & $pythonPath .\db\db_tool.py build-oui-registry --output-path $OutputPath
if ($LASTEXITCODE -ne 0) {
    throw "OUI registry update failed: $result"
}

$result | ConvertFrom-Json
