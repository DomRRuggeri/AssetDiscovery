PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    hostname TEXT,
    ip_address TEXT,
    mac_address TEXT,
    asset_type TEXT,
    mac_vendor TEXT,
    operating_system TEXT,
    owner TEXT,
    environment TEXT,
    source TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    azure_verified INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    run_id TEXT PRIMARY KEY,
    source_file TEXT,
    source_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    asset_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS asset_observations (
    observation_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    hostname TEXT,
    ip_address TEXT,
    mac_address TEXT,
    source TEXT,
    raw_payload TEXT,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id),
    FOREIGN KEY (run_id) REFERENCES discovery_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_assets_hostname ON assets(hostname);
CREATE INDEX IF NOT EXISTS idx_assets_ip_address ON assets(ip_address);
CREATE INDEX IF NOT EXISTS idx_assets_mac_address ON assets(mac_address);
CREATE INDEX IF NOT EXISTS idx_observations_asset_id ON asset_observations(asset_id);
CREATE INDEX IF NOT EXISTS idx_observations_run_id ON asset_observations(run_id);
