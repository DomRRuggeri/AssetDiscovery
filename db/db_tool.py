import argparse
import csv
import json
import sqlite3
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "db" / "schema.sql"
IP_ONLY_MATCH_MAX_AGE_DAYS = 14
OUI_URLS = [
    ("oui", "https://standards-oui.ieee.org/oui/oui.csv", 24),
    ("mam", "https://standards-oui.ieee.org/oui28/mam.csv", 28),
    ("oui36", "https://standards-oui.ieee.org/oui36/oui36.csv", 36),
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_mac(value):
    if not value:
        return None
    cleaned = "".join(ch for ch in str(value) if ch.isalnum()).upper()
    if len(cleaned) != 12:
        return str(value).strip() or None
    return ":".join(cleaned[index:index + 2] for index in range(0, 12, 2))


def normalize_record(record):
    def first_value(*keys):
        for key in keys:
            value = record.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    last_seen = first_value("LastSeen") or utc_now()
    asset_id = first_value("AssetId")

    return {
        "AssetId": asset_id or str(uuid.uuid4()),
        "Hostname": first_value("Hostname", "Name", "DeviceName", "ComputerName"),
        "IpAddress": first_value("IpAddress", "IPAddress", "PrivateIpAddress", "Address"),
        "MacAddress": normalize_mac(first_value("MacAddress", "MACAddress", "Mac")),
        "AssetType": first_value("AssetType", "Type", "Category", "DeviceType"),
        "OperatingSystem": first_value("OperatingSystem"),
        "Owner": first_value("Owner"),
        "Environment": first_value("Environment"),
        "Source": first_value("Source", "InventorySource") or "manual-import",
        "LastSeen": last_seen,
        "Notes": first_value("Notes"),
    }


def load_records(path: Path):
    extension = path.suffix.lower()
    if extension == ".json":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            raw = [raw]
    elif extension == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw = list(csv.DictReader(handle))
    else:
        raise ValueError(f"Unsupported input format: {extension}")

    return [normalize_record(record) for record in raw]


def connect(db_path: Path):
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    ensure_schema(connection)
    return connection


def ensure_schema(connection):
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema)

    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(assets)").fetchall()
    }
    if "mac_vendor" not in columns:
        connection.execute("ALTER TABLE assets ADD COLUMN mac_vendor TEXT")
    if "asset_type" not in columns:
        connection.execute("ALTER TABLE assets ADD COLUMN asset_type TEXT")
    if "azure_verified" not in columns:
        connection.execute("ALTER TABLE assets ADD COLUMN azure_verified INTEGER NOT NULL DEFAULT 0")

    connection.commit()


def is_hostname_candidate(value):
    if not value:
        return False

    text = str(value).strip()
    if not text:
        return False

    parts = text.split(".")
    if all(part.isdigit() for part in parts):
        return False

    return any(character.isalpha() for character in text)


def initialize_database(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(db_path)
    try:
        ensure_schema(connection)
    finally:
        connection.close()


def find_existing_asset(connection, record):
    if record["AssetId"]:
        row = connection.execute(
            "SELECT * FROM assets WHERE asset_id = ? LIMIT 1",
            (record["AssetId"],),
        ).fetchone()
        if row is not None:
            return row, "asset-id"

    if record["MacAddress"]:
        row = connection.execute(
            "SELECT * FROM assets WHERE LOWER(mac_address) = LOWER(?) ORDER BY last_seen DESC LIMIT 1",
            (record["MacAddress"],),
        ).fetchone()
        if row is not None:
            return row, "mac-address"

    if is_hostname_candidate(record["Hostname"]):
        rows = connection.execute(
            "SELECT * FROM assets WHERE LOWER(hostname) = LOWER(?) ORDER BY last_seen DESC",
            (record["Hostname"],),
        ).fetchall()
        if len(rows) == 1:
            return rows[0], "hostname"

        # If a hostname maps to multiple assets, refuse to guess.
        if len(rows) > 1:
            return None, None

    # IP is weak evidence. Only reuse it for recent unresolved assets that also
    # lack stronger identifiers, which limits accidental merges after readdressing.
    if record["IpAddress"] and not record["MacAddress"] and not record["Hostname"]:
        row = connection.execute(
            """
            SELECT *
            FROM assets
            WHERE ip_address = ?
              AND COALESCE(hostname, '') = ''
              AND COALESCE(mac_address, '') = ''
              AND julianday('now') - julianday(last_seen) <= ?
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            (record["IpAddress"], IP_ONLY_MATCH_MAX_AGE_DAYS),
        ).fetchone()
        if row is not None:
            return row, "recent-ip-only"

    return None, None


def upsert_asset(connection, record):
    existing, match_reason = find_existing_asset(connection, record)

    if existing is None:
        asset_id = record["AssetId"]
        first_seen = record["LastSeen"]
        connection.execute(
            """
            INSERT INTO assets (
                asset_id, hostname, ip_address, mac_address, asset_type, operating_system,
                mac_vendor, owner, environment, source, first_seen, last_seen, azure_verified, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                record["Hostname"],
                record["IpAddress"],
                record["MacAddress"],
                record["AssetType"],
                record["OperatingSystem"],
                None,
                record["Owner"],
                record["Environment"],
                record["Source"],
                first_seen,
                record["LastSeen"],
                0,
                "active",
                record["Notes"],
            ),
        )
        return asset_id, "inserted", None

    asset_id = existing["asset_id"]
    connection.execute(
        """
        UPDATE assets
        SET hostname = COALESCE(?, hostname),
            ip_address = COALESCE(?, ip_address),
            mac_address = COALESCE(?, mac_address),
            asset_type = COALESCE(?, asset_type),
            operating_system = COALESCE(?, operating_system),
            owner = COALESCE(?, owner),
            environment = COALESCE(?, environment),
            source = COALESCE(?, source),
            last_seen = ?,
            status = 'active',
            notes = COALESCE(?, notes)
        WHERE asset_id = ?
        """,
        (
            record["Hostname"],
            record["IpAddress"],
            record["MacAddress"],
            record["AssetType"],
            record["OperatingSystem"],
            record["Owner"],
            record["Environment"],
            record["Source"],
            record["LastSeen"],
            record["Notes"],
            asset_id,
        ),
    )
    return asset_id, "updated", match_reason


def import_discovery(db_path: Path, input_path: Path, source_type: str, notes: str | None):
    records = load_records(input_path)
    connection = connect(db_path)
    inserted = 0
    updated = 0
    observations = 0
    match_reasons = {}
    run_id = str(uuid.uuid4())
    started_at = utc_now()

    try:
        connection.execute(
            """
            INSERT INTO discovery_runs (run_id, source_file, source_type, started_at, completed_at, asset_count, notes)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (run_id, str(input_path), source_type, started_at, started_at, notes),
        )

        for record in records:
            asset_id, action, match_reason = upsert_asset(connection, record)
            if action == "inserted":
                inserted += 1
            else:
                updated += 1
                if match_reason:
                    match_reasons[match_reason] = match_reasons.get(match_reason, 0) + 1

            observation_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO asset_observations (
                    observation_id, asset_id, run_id, observed_at, hostname, ip_address, mac_address, source, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    asset_id,
                    run_id,
                    record["LastSeen"],
                    record["Hostname"],
                    record["IpAddress"],
                    record["MacAddress"],
                    record["Source"],
                    json.dumps(record, separators=(",", ":")),
                ),
            )
            observations += 1

        completed_at = utc_now()
        connection.execute(
            """
            UPDATE discovery_runs
            SET completed_at = ?, asset_count = ?
            WHERE run_id = ?
            """,
            (completed_at, observations, run_id),
        )
        connection.commit()
    finally:
        connection.close()

    return {
        "RunId": run_id,
        "SourceFile": str(input_path),
        "SourceType": source_type,
        "Processed": len(records),
        "InsertedAssets": inserted,
        "UpdatedAssets": updated,
        "ObservationsAdded": observations,
        "MatchReasons": match_reasons,
    }


def export_assets(db_path: Path, output_path: Path):
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT
                asset_id AS AssetId,
                hostname AS Hostname,
                ip_address AS IpAddress,
                mac_address AS MacAddress,
                asset_type AS AssetType,
                mac_vendor AS MacVendor,
                operating_system AS OperatingSystem,
                owner AS Owner,
                environment AS Environment,
                source AS Source,
                first_seen AS FirstSeen,
                last_seen AS LastSeen,
                azure_verified AS AzureVerified,
                status AS Status,
                notes AS Notes
            FROM assets
            ORDER BY COALESCE(hostname, ip_address, asset_id)
            """
        ).fetchall()
    finally:
        connection.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [dict(row) for row in rows]
    output_path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    return {"OutputPath": str(output_path), "AssetCount": len(payload)}


def export_runs(db_path: Path, output_path: Path):
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT run_id AS RunId,
                   source_file AS SourceFile,
                   source_type AS SourceType,
                   started_at AS StartedAt,
                   completed_at AS CompletedAt,
                   asset_count AS AssetCount,
                   notes AS Notes
            FROM discovery_runs
            ORDER BY started_at DESC
            """
        ).fetchall()
    finally:
        connection.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [dict(row) for row in rows]
    output_path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    return {"OutputPath": str(output_path), "RunCount": len(payload)}


def list_assets(db_path: Path, search: str | None, status: str | None):
    connection = connect(db_path)
    try:
        query = """
            SELECT
                asset_id AS AssetId,
                hostname AS Hostname,
                ip_address AS IpAddress,
                mac_address AS MacAddress,
                asset_type AS AssetType,
                mac_vendor AS MacVendor,
                owner AS Owner,
                environment AS Environment,
                azure_verified AS AzureVerified,
                status AS Status,
                last_seen AS LastSeen
            FROM assets
            WHERE 1 = 1
        """
        parameters = []

        if status:
            query += " AND LOWER(status) = LOWER(?)"
            parameters.append(status)

        if search:
            query += """
                AND (
                    LOWER(COALESCE(asset_id, '')) LIKE LOWER(?)
                    OR LOWER(COALESCE(hostname, '')) LIKE LOWER(?)
                    OR LOWER(COALESCE(ip_address, '')) LIKE LOWER(?)
                    OR LOWER(COALESCE(mac_address, '')) LIKE LOWER(?)
                    OR LOWER(COALESCE(asset_type, '')) LIKE LOWER(?)
                    OR LOWER(COALESCE(owner, '')) LIKE LOWER(?)
                    OR LOWER(COALESCE(environment, '')) LIKE LOWER(?)
                )
            """
            pattern = f"%{search}%"
            parameters.extend([pattern] * 7)

        query += " ORDER BY COALESCE(hostname, ip_address, asset_id)"
        rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def update_asset(
    db_path: Path,
    asset_id: str,
    hostname: str | None,
    ip_address: str | None,
    mac_address: str | None,
    asset_type: str | None,
    operating_system: str | None,
    owner: str | None,
    environment: str | None,
    azure_verified: int | None,
    status: str | None,
    notes: str | None,
):
    connection = connect(db_path)
    try:
        existing = connection.execute("SELECT asset_id FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        if existing is None:
            raise ValueError(f"Asset not found: {asset_id}")

        assignments = []
        parameters = []

        field_map = {
            "hostname": hostname,
            "ip_address": ip_address,
            "mac_address": normalize_mac(mac_address) if mac_address else mac_address,
            "asset_type": asset_type,
            "operating_system": operating_system,
            "owner": owner,
            "environment": environment,
            "azure_verified": azure_verified,
            "status": status,
            "notes": notes,
        }

        for column, value in field_map.items():
            if value is not None:
                assignments.append(f"{column} = ?")
                parameters.append(value)

        if not assignments:
            row = connection.execute(
                """
                SELECT asset_id AS AssetId, hostname AS Hostname, ip_address AS IpAddress, mac_address AS MacAddress,
                       asset_type AS AssetType, mac_vendor AS MacVendor, operating_system AS OperatingSystem, owner AS Owner, environment AS Environment,
                       azure_verified AS AzureVerified,
                       status AS Status, notes AS Notes, first_seen AS FirstSeen, last_seen AS LastSeen
                FROM assets
                WHERE asset_id = ?
                """,
                (asset_id,),
            ).fetchone()
            return dict(row)

        assignments.append("last_seen = last_seen")
        parameters.append(asset_id)
        connection.execute(
            f"UPDATE assets SET {', '.join(assignments)} WHERE asset_id = ?",
            parameters,
        )
        connection.commit()

        row = connection.execute(
            """
            SELECT asset_id AS AssetId, hostname AS Hostname, ip_address AS IpAddress, mac_address AS MacAddress,
                   asset_type AS AssetType, mac_vendor AS MacVendor, operating_system AS OperatingSystem, owner AS Owner, environment AS Environment,
                   azure_verified AS AzureVerified,
                   status AS Status, notes AS Notes, first_seen AS FirstSeen, last_seen AS LastSeen
            FROM assets
            WHERE asset_id = ?
            """,
            (asset_id,),
        ).fetchone()
        return dict(row)
    finally:
        connection.close()


def set_azure_verified(db_path: Path, asset_ids: list[str]):
    connection = connect(db_path)
    try:
        connection.execute("UPDATE assets SET azure_verified = 0")
        normalized_ids = [asset_id for asset_id in asset_ids if asset_id]
        if normalized_ids:
            placeholders = ",".join("?" for _ in normalized_ids)
            connection.execute(
                f"UPDATE assets SET azure_verified = 1 WHERE asset_id IN ({placeholders})",
                normalized_ids,
            )
        connection.commit()
        verified_count = connection.execute(
            "SELECT COUNT(*) FROM assets WHERE azure_verified = 1"
        ).fetchone()[0]
        return {"VerifiedAssets": verified_count}
    finally:
        connection.close()


def normalize_prefix(assignment_value, bit_length):
    cleaned = "".join(ch for ch in assignment_value if ch.isalnum()).upper()
    hex_length = bit_length // 4
    return cleaned[:hex_length]


def build_oui_registry(output_path: Path):
    registry = {}

    for registry_name, url, bit_length in OUI_URLS:
        with urllib.request.urlopen(url) as response:
            raw = response.read().decode("utf-8-sig")

        reader = csv.DictReader(raw.splitlines())
        for row in reader:
            assignment = row.get("Assignment")
            organization = row.get("Organization Name")
            if not assignment or not organization:
                continue

            prefix = normalize_prefix(assignment, bit_length)
            if prefix:
                registry[prefix] = {
                    "vendor": organization.strip(),
                    "bits": bit_length,
                    "source": registry_name,
                }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": utc_now(),
        "entries": registry,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"OutputPath": str(output_path), "EntryCount": len(registry)}


def lookup_vendor(registry_entries, mac_address):
    if not mac_address:
        return None, None

    cleaned = "".join(ch for ch in str(mac_address) if ch.isalnum()).upper()
    for hex_length in (9, 7, 6):
        prefix = cleaned[:hex_length]
        if prefix in registry_entries:
            entry = registry_entries[prefix]
            return entry["vendor"], entry["source"]

    return None, None


def update_asset_vendors(db_path: Path, registry_path: Path):
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = payload.get("entries", {})

    connection = connect(db_path)
    updated = 0
    unresolved = 0
    try:
        rows = connection.execute(
            "SELECT asset_id, mac_address, mac_vendor FROM assets WHERE COALESCE(mac_address, '') <> ''"
        ).fetchall()

        for row in rows:
            vendor, _source = lookup_vendor(entries, row["mac_address"])
            if vendor:
                connection.execute(
                    "UPDATE assets SET mac_vendor = ? WHERE asset_id = ?",
                    (vendor, row["asset_id"]),
                )
                updated += 1
            else:
                unresolved += 1

        connection.commit()
    finally:
        connection.close()

    return {
        "RegistryPath": str(registry_path),
        "UpdatedAssets": updated,
        "UnresolvedAssets": unresolved,
    }


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--db-path", required=True)

    import_parser = subparsers.add_parser("import-discovery")
    import_parser.add_argument("--db-path", required=True)
    import_parser.add_argument("--input-path", required=True)
    import_parser.add_argument("--source-type", default="network-discovery")
    import_parser.add_argument("--notes")

    export_assets_parser = subparsers.add_parser("export-assets")
    export_assets_parser.add_argument("--db-path", required=True)
    export_assets_parser.add_argument("--output-path", required=True)

    export_runs_parser = subparsers.add_parser("export-runs")
    export_runs_parser.add_argument("--db-path", required=True)
    export_runs_parser.add_argument("--output-path", required=True)

    registry_parser = subparsers.add_parser("build-oui-registry")
    registry_parser.add_argument("--output-path", required=True)

    vendor_update_parser = subparsers.add_parser("update-asset-vendors")
    vendor_update_parser.add_argument("--db-path", required=True)
    vendor_update_parser.add_argument("--registry-path", required=True)

    list_assets_parser = subparsers.add_parser("list-assets")
    list_assets_parser.add_argument("--db-path", required=True)
    list_assets_parser.add_argument("--search")
    list_assets_parser.add_argument("--status")

    update_asset_parser = subparsers.add_parser("update-asset")
    update_asset_parser.add_argument("--db-path", required=True)
    update_asset_parser.add_argument("--asset-id", required=True)
    update_asset_parser.add_argument("--hostname")
    update_asset_parser.add_argument("--ip-address")
    update_asset_parser.add_argument("--mac-address")
    update_asset_parser.add_argument("--asset-type")
    update_asset_parser.add_argument("--operating-system")
    update_asset_parser.add_argument("--owner")
    update_asset_parser.add_argument("--environment")
    update_asset_parser.add_argument("--azure-verified", type=int, choices=[0, 1])
    update_asset_parser.add_argument("--status")
    update_asset_parser.add_argument("--notes")

    azure_verified_parser = subparsers.add_parser("set-azure-verified")
    azure_verified_parser.add_argument("--db-path", required=True)
    azure_verified_parser.add_argument("--asset-id", action="append", default=[])

    args = parser.parse_args()

    try:
        if args.command == "init":
            initialize_database(Path(args.db_path))
            result = {"DatabasePath": args.db_path, "Status": "Initialized"}
        elif args.command == "import-discovery":
            result = import_discovery(Path(args.db_path), Path(args.input_path), args.source_type, args.notes)
        elif args.command == "export-assets":
            result = export_assets(Path(args.db_path), Path(args.output_path))
        elif args.command == "build-oui-registry":
            result = build_oui_registry(Path(args.output_path))
        elif args.command == "update-asset-vendors":
            result = update_asset_vendors(Path(args.db_path), Path(args.registry_path))
        elif args.command == "list-assets":
            result = list_assets(Path(args.db_path), args.search, args.status)
        elif args.command == "update-asset":
            result = update_asset(
                Path(args.db_path),
                args.asset_id,
                args.hostname,
                args.ip_address,
                args.mac_address,
                args.asset_type,
                args.operating_system,
                args.owner,
                args.environment,
                args.azure_verified,
                args.status,
                args.notes,
            )
        elif args.command == "set-azure-verified":
            result = set_azure_verified(Path(args.db_path), args.asset_id)
        else:
            result = export_runs(Path(args.db_path), Path(args.output_path))
    except Exception as error:
        print(json.dumps({"Error": str(error)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
