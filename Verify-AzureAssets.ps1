[CmdletBinding()]
param(
    [string]$DatabasePath = '.\data\assets.db',

    [string]$InventoryPath,

    [string]$OutputPath = '.\output\azure-verification.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force

if ($InventoryPath) {
    Write-ToolkitLog -Message "Loading inventory from $InventoryPath."
    $inventoryAssets = @(Import-ToolkitAssetFile -Path $InventoryPath)
}
else {
    if (-not (Test-Path -LiteralPath $DatabasePath)) {
        throw "Database file not found: $DatabasePath"
    }

    $pythonPath = Get-ToolkitPythonPath
    $arguments = @(
        '.\db\db_tool.py'
        'list-assets'
        '--db-path'
        $DatabasePath
    )

    Write-ToolkitLog -Message "Loading canonical assets from database $DatabasePath."
    $result = & $pythonPath @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Asset query failed: $result"
    }

    $parsedAssets = @($result | ConvertFrom-Json)
    if ($parsedAssets.Count -eq 1 -and $parsedAssets[0] -is [System.Array]) {
        $inventoryAssets = @($parsedAssets[0])
    }
    else {
        $inventoryAssets = $parsedAssets
    }
}

Write-ToolkitLog -Message 'Collecting Azure asset snapshot.'
$azureAssets = @(Get-ToolkitAzureAssetSnapshot)

Write-ToolkitLog -Message "Comparing $($inventoryAssets.Count) inventory assets against $($azureAssets.Count) Azure assets."
$comparison = @(Compare-ToolkitAssetsToAzure -InventoryAssets $inventoryAssets -AzureAssets $azureAssets)

$matchedAssetIds = @(
    $comparison |
        Where-Object MatchStatus -eq 'Matched' |
        ForEach-Object { $_.AssetId } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)

if (-not $InventoryPath) {
    $updateArguments = @(
        '.\db\db_tool.py'
        'set-azure-verified'
        '--db-path'
        $DatabasePath
    )

    foreach ($assetId in $matchedAssetIds) {
        $updateArguments += @('--asset-id', $assetId)
    }

    Write-ToolkitLog -Message "Updating AzureVerified flags in $DatabasePath."
    $updateResult = & $pythonPath @updateArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Azure verification flag update failed: $updateResult"
    }
}

Export-ToolkitAssetFile -Assets $comparison -Path $OutputPath

$matched = @($comparison | Where-Object MatchStatus -eq 'Matched').Count
$unmatched = @($comparison | Where-Object MatchStatus -ne 'Matched').Count

Write-ToolkitLog -Message "Azure verification complete. Matched: $matched. Not found: $unmatched. Output: $OutputPath"
$comparison
