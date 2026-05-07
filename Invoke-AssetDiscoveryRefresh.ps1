[CmdletBinding()]
param(
    [string]$DatabasePath = '.\data\assets.db',

    [string]$NinjaExportPath = '.\NinjaExport.csv',

    [string]$GraphCredentialPath = '.\data\graph-app-credentials.json',

    [string]$OuiRegistryPath = '.\data\oui-registry.json',

    [string]$OutputDirectory = '.\output'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$startedAt = Get-Date
$transcriptPath = Join-Path $OutputDirectory ("asset-refresh-{0}.log" -f $startedAt.ToString('yyyyMMdd-HHmmss'))

if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}

Start-Transcript -Path $transcriptPath -Force | Out-Null

try {
    Set-Location -LiteralPath $PSScriptRoot

    Write-Host "Starting asset refresh at $($startedAt.ToString('o'))."

    .\Init-AssetDatabase.ps1 -DatabasePath $DatabasePath

    if (Test-Path -LiteralPath $NinjaExportPath) {
        .\Compare-NinjaExport.ps1 `
            -InputPath $NinjaExportPath `
            -DatabasePath $DatabasePath `
            -OutputPath (Join-Path $OutputDirectory 'ninja-compare-report.json')

        .\Import-NinjaExportToDatabase.ps1 `
            -InputPath $NinjaExportPath `
            -DatabasePath $DatabasePath `
            -ReportPath (Join-Path $OutputDirectory 'ninja-import-report.json')
    }
    else {
        Write-Warning "Ninja export not found: $NinjaExportPath. Skipping Ninja import."
    }

    if (Test-Path -LiteralPath $OuiRegistryPath) {
        .\Update-AssetVendors.ps1 -DatabasePath $DatabasePath -RegistryPath $OuiRegistryPath
    }
    else {
        Write-Warning "OUI registry not found: $OuiRegistryPath. Skipping vendor enrichment."
    }

    if (Test-Path -LiteralPath $GraphCredentialPath) {
        .\Verify-AzureAssets.ps1 `
            -DatabasePath $DatabasePath `
            -OutputPath (Join-Path $OutputDirectory 'azure-verification.json') `
            -CredentialPath $GraphCredentialPath
    }
    else {
        Write-Warning "Graph credential file not found: $GraphCredentialPath. Skipping Azure verification."
    }

    .\Export-AssetSnapshot.ps1 `
        -DatabasePath $DatabasePath `
        -OutputPath (Join-Path $OutputDirectory 'asset-snapshot.json')

    $completedAt = Get-Date
    Write-Host "Asset refresh completed at $($completedAt.ToString('o')). Duration: $($completedAt - $startedAt)."
}
finally {
    Stop-Transcript | Out-Null
}
