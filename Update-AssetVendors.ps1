[CmdletBinding()]
param(
    [string]$DatabasePath = '.\data\assets.db',

    [string]$RegistryPath = '.\data\oui-registry.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

Write-Host "Updating asset vendors in $DatabasePath using $RegistryPath"
$result = & $pythonPath .\db\db_tool.py update-asset-vendors --db-path $DatabasePath --registry-path $RegistryPath
if ($LASTEXITCODE -ne 0) {
    throw "Asset vendor update failed: $result"
}

$result | ConvertFrom-Json
