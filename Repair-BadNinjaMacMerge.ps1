[CmdletBinding()]
param(
    [string]$DatabasePath = '.\data\assets.db',

    [Parameter(Mandatory)]
    [string]$BadMacAddress
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

$arguments = @(
    '.\db\db_tool.py'
    'repair-bad-ninja-mac-merge'
    '--db-path'
    $DatabasePath
    '--bad-mac-address'
    $BadMacAddress
)

Write-Host "Repairing Ninja merge issues for MAC $BadMacAddress in $DatabasePath"
$result = & $pythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Bad Ninja MAC repair failed: $result"
}

$result | ConvertFrom-Json
