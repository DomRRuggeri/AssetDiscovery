[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$InputPath,

    [string]$DatabasePath = '.\data\assets.db',

    [string]$ReportPath = '.\output\ninja-import-report.json',

    [string]$Notes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

$arguments = @(
    '.\db\db_tool.py'
    'import-ninja-export'
    '--db-path'
    $DatabasePath
    '--input-path'
    $InputPath
    '--report-path'
    $ReportPath
)

if ($Notes) {
    $arguments += @('--notes', $Notes)
}

Write-Host "Importing Ninja export $InputPath into $DatabasePath"
$result = & $pythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Ninja import failed: $result"
}

$result | ConvertFrom-Json
