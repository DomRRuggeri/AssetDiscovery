[CmdletBinding()]
param(
    [string]$DatabasePath = '.\data\assets.db',

    [string]$OutputPath = '.\output\asset-snapshot.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

Write-Host "Exporting asset snapshot from $DatabasePath to $OutputPath"
$result = & $pythonPath .\db\db_tool.py export-assets --db-path $DatabasePath --output-path $OutputPath
if ($LASTEXITCODE -ne 0) {
    throw "Asset export failed: $result"
}

$result | ConvertFrom-Json
