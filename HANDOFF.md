# Handoff Notes

## Current State

- Canonical project root: `C:\users\druggeri\Documents\Scripts\Codex\AssetDiscovery`
- Canonical asset database: `data\assets.db`
- Canonical viewer snapshot: `output\asset-snapshot.json`
- Preferred viewer launcher: `.\Start-Viewer.ps1`

## Workflow

1. Run discovery with `Discover-Network.ps1`
2. Import discovery JSON into SQLite with `Import-DiscoveryToDatabase.ps1`
3. Maintain/enrich assets with `Edit-AssetRecord.ps1` or `Update-AssetRecord.ps1`
4. Export current asset view with `Export-AssetSnapshot.ps1`
5. Launch viewer with `Start-Viewer.ps1`

## Viewer

- Main page: `viewer\index.html`
- Detail page: `viewer\detail.html`
- The viewer auto-loads `../output/asset-snapshot.json` when served over localhost
- Clicking a row on the main page navigates to the asset detail page
- Table headers are sortable
- Viewer now shows `MacVendor` on the main table and detail page

## Database Model

- `assets`: current best-known asset record
- `discovery_runs`: one row per import
- `asset_observations`: historical sightings

## Identity Matching

Discovery import matching in `db\db_tool.py` currently uses:

1. exact `AssetId`
2. exact `MacAddress`
3. exact `Hostname` only if unique
4. `IpAddress` only for recent unresolved assets with no hostname or MAC

## Vendor Enrichment

- Separate from discovery and import
- Uses official IEEE OUI registry downloads cached in `data\oui-registry.json`
- Update commands:
  - `.\Update-OuiRegistry.ps1`
  - `.\Update-AssetVendors.ps1`
- No hostname-based inference is used for vendor classification

## Recent Discovery Imports

- Imported 100-host batch `output\discovery-batch100-dns-mac.json`
- Imported 100-host batch `output\discovery-batch100-b-dns-mac.json`
- Imported full `/22` batch `output\discovery-full-10.4.20.0-22.json`

## Current Counts At Last Check

- `assets = 208`
- `discovery_runs = 5`
- `asset_observations = 358`
- `assets with MacVendor = 174`
- `assets with MAC but unresolved vendor = 33`

## Important Notes

- Browser auto-load fails on direct `file://` open; use `Start-Viewer.ps1`
- Some placeholder enrichment was used earlier on `UTILITY-BOX.inplace.com`
- Folder was renamed from `Asset Discovery` to `AssetDiscovery`
- `README.md` contains the operational workflow, but this file is the quickest resume point
