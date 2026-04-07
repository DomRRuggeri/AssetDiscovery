[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$InputPath,

    [string]$DatabasePath = '.\data\assets.db',

    [string]$SourceType = 'network-discovery',

    [string]$Notes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

Write-Host "Importing discovery file $InputPath into $DatabasePath"
$arguments = @(
    '.\db\db_tool.py'
    'import-discovery'
    '--db-path'
    $DatabasePath
    '--input-path'
    $InputPath
    '--source-type'
    $SourceType
)

if ($Notes) {
    $arguments += @('--notes', $Notes)
}

$result = & $pythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Discovery import failed: $result"
}

$result | ConvertFrom-Json
