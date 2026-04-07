[CmdletBinding()]
param(
    [string]$DatabasePath = '.\data\assets.db'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

Write-Host "Initializing asset database at $DatabasePath"
$result = & $pythonPath .\db\db_tool.py init --db-path $DatabasePath
if ($LASTEXITCODE -ne 0) {
    throw "Database initialization failed: $result"
}

$result | ConvertFrom-Json
