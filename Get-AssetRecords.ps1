[CmdletBinding()]
param(
    [string]$DatabasePath = '.\data\assets.db',

    [string]$Search,

    [string]$Status
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

$arguments = @(
    '.\db\db_tool.py'
    'list-assets'
    '--db-path'
    $DatabasePath
)

if ($Search) {
    $arguments += @('--search', $Search)
}

if ($Status) {
    $arguments += @('--status', $Status)
}

$result = & $pythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Asset query failed: $result"
}

$result | ConvertFrom-Json
