import argparse
import csv
import json
import ipaddress
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


def short_hostname(value):
    if not value:
        return None
    return str(value).strip().split(".")[0].lower() or None


def normalize_ninja_device_name(value):
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.endswith(")") and " (" in text:
        text = text.rsplit(" (", 1)[0].strip()

    return text or None


def split_delimited_values(value):
    if value is None:
        return []

    return [item.strip() for item in str(value).split(",") if item and item.strip()]


def normalize_ipv4(value):
    if not value:
        return None

    text = str(value).strip()
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        return None

    if parsed.version != 4:
        return None

    return str(parsed)


def parse_ninja_ip_addresses(value):
    ipv4_addresses = []
    ignored_values = []

    for item in split_delimited_values(value):
        normalized = normalize_ipv4(item)
        if normalized:
            ipv4_addresses.append(normalized)
        else:
            ignored_values.append(item)

    return ipv4_addresses, ignored_values


def score_ninja_ip_address(value):
    parsed = ipaddress.ip_address(value)
    score = 0

    if parsed.is_loopback or parsed.is_link_local:
        score -= 100
    if parsed.is_private:
        score += 30
    if value.startswith("10.4."):
        score += 15
    elif value.startswith("10."):
        score += 10
    elif value.startswith("172."):
        score += 5
    elif value.startswith("192.168."):
        score += 2

    return score


VIRTUAL_MAC_PREFIXES = (
    "00155D",  # Hyper-V
    "005056",  # VMware
    "000C29",  # VMware
    "000569",  # VMware
    "0003FF",  # Microsoft legacy virtual
    "080027",  # VirtualBox
)


DISALLOWED_NINJA_MAC_ADDRESSES = {
    "00:09:0F:AA:00:01",
    "00:09:0F:FE:00:01",
}


def is_allowed_ninja_mac(value):
    normalized = normalize_mac(value)
    if not normalized:
        return False

    return normalized.upper() not in DISALLOWED_NINJA_MAC_ADDRESSES


def score_ninja_mac_address(value):
    cleaned = "".join(ch for ch in str(value) if ch.isalnum()).upper()
    score = 0

    if len(cleaned) == 12:
        if cleaned.startswith(VIRTUAL_MAC_PREFIXES):
            score -= 25

        first_octet = int(cleaned[:2], 16)
        if first_octet & 0x02:
            score -= 10
        else:
            score += 5

    return score


def choose_preferred_ninja_ip(ip_addresses):
    if not ip_addresses:
        return None

    return sorted(
        ip_addresses,
        key=lambda value: (-score_ninja_ip_address(value), value),
    )[0]


def choose_preferred_ninja_mac(mac_addresses):
    if not mac_addresses:
        return None

    normalized = [normalize_mac(value) for value in mac_addresses if is_allowed_ninja_mac(value)]
    if not normalized:
        return None

    return sorted(
        normalized,
        key=lambda value: (-score_ninja_mac_address(value), value),
    )[0]


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


def normalize_ninja_record(record):
    hostname = normalize_ninja_device_name(record.get("Device"))
    ip_addresses, ignored_ip_values = parse_ninja_ip_addresses(record.get("IP Addresses"))
    mac_addresses = [normalize_mac(value) for value in split_delimited_values(record.get("MAC Addresses"))]
    mac_addresses = [value for value in mac_addresses if value]

    organization = (record.get("Organization") or "").strip() or None
    location = (record.get("Location") or "").strip() or None
    domain = (record.get("Domain") or "").strip() or None
    last_login = (record.get("Last Login") or "").strip() or None

    note_parts = []
    if organization:
        note_parts.append(f"Organization={organization}")
    if domain:
        note_parts.append(f"Domain={domain}")
    if ignored_ip_values:
        note_parts.append(f"IgnoredIpValues={'|'.join(ignored_ip_values)}")

    return {
        "AssetId": str(uuid.uuid4()),
        "Hostname": hostname,
        "IpAddress": choose_preferred_ninja_ip(ip_addresses),
        "MacAddress": choose_preferred_ninja_mac(mac_addresses),
        "AssetType": None,
        "OperatingSystem": None,
        "Owner": last_login,
        "Environment": location,
        "Source": "ninja-export",
        "LastSeen": (record.get("Last Uptime") or "").strip() or utc_now(),
        "Notes": "; ".join(note_parts) or None,
        "RawDeviceName": (record.get("Device") or "").strip() or None,
        "Domain": domain,
        "Organization": organization,
        "Location": location,
        "LastLogin": last_login,
        "AllIpAddresses": ip_addresses,
        "AllMacAddresses": mac_addresses,
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


def load_ninja_records(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw = list(csv.DictReader(handle))

    return [normalize_ninja_record(record) for record in raw]


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


def find_existing_asset_by_hostname(connection, hostname):
    if not is_hostname_candidate(hostname):
        return None, None

    rows = connection.execute(
        "SELECT * FROM assets WHERE COALESCE(hostname, '') <> '' ORDER BY last_seen DESC"
    ).fetchall()

    exact_matches = [row for row in rows if str(row["hostname"]).strip().lower() == str(hostname).strip().lower()]
    if len(exact_matches) == 1:
        return exact_matches[0], "hostname"

    if len(exact_matches) > 1:
        return None, None

    normalized = short_hostname(hostname)
    if not normalized:
        return None, None

    short_matches = [row for row in rows if short_hostname(row["hostname"]) == normalized]
    if len(short_matches) == 1:
        return short_matches[0], "short-hostname"

    return None, None


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

    hostname_row, hostname_match_reason = find_existing_asset_by_hostname(connection, record["Hostname"])
    if hostname_row is not None:
        return hostname_row, hostname_match_reason

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


def find_existing_asset_by_short_hostname(connection, hostname):
    row, _match_reason = find_existing_asset_by_hostname(connection, hostname)
    return row


def compare_ninja_record(connection, record):
    matches_by_mac = []
    for mac_address in record["AllMacAddresses"]:
        if not is_allowed_ninja_mac(mac_address):
            continue

        row = connection.execute(
            "SELECT * FROM assets WHERE LOWER(mac_address) = LOWER(?) ORDER BY last_seen DESC LIMIT 1",
            (mac_address,),
        ).fetchone()
        if row is not None:
            matches_by_mac.append(row)

    unique_mac_matches = {row["asset_id"]: row for row in matches_by_mac}
    mac_match = None
    if len(unique_mac_matches) == 1:
        mac_match = next(iter(unique_mac_matches.values()))

    hostname_match = find_existing_asset_by_short_hostname(connection, record["Hostname"])

    ip_matches = []
    for ip_address in record["AllIpAddresses"]:
        row = connection.execute(
            "SELECT * FROM assets WHERE ip_address = ? ORDER BY last_seen DESC LIMIT 1",
            (ip_address,),
        ).fetchone()
        if row is not None:
            ip_matches.append(row)

    unique_ip_matches = {row["asset_id"]: row for row in ip_matches}
    ip_match = None
    if len(unique_ip_matches) == 1:
        ip_match = next(iter(unique_ip_matches.values()))

    category = "new-asset"
    matched_asset = None
    reasons = []
    conflict = None

    if mac_match is not None:
        matched_asset = mac_match
        reasons.append("mac-address")
        category = "match-by-mac"

        if hostname_match is not None and hostname_match["asset_id"] != mac_match["asset_id"]:
            conflict = "hostname-conflicts-with-mac"
            category = "conflict"
        elif ip_match is not None and ip_match["asset_id"] != mac_match["asset_id"]:
            conflict = "ip-conflicts-with-mac"
            category = "conflict"
        elif hostname_match is not None:
            reasons.append("short-hostname")
        elif ip_match is not None:
            reasons.append("ip-signal")
    elif hostname_match is not None:
        matched_asset = hostname_match
        reasons.append("short-hostname")
        category = "match-by-short-hostname"

        if ip_match is not None and ip_match["asset_id"] != hostname_match["asset_id"]:
            conflict = "ip-conflicts-with-hostname"
            category = "conflict"
        elif ip_match is not None:
            reasons.append("ip-signal")
    elif ip_match is not None:
        matched_asset = ip_match
        category = "ip-only-review"
        reasons.append("ip-signal")

    return {
        "Category": category,
        "MatchedAsset": dict(matched_asset) if matched_asset is not None else None,
        "Conflict": conflict,
        "Reasons": reasons,
        "IpSignalAsset": dict(ip_match) if ip_match is not None else None,
        "HostnameSignalAsset": dict(hostname_match) if hostname_match is not None else None,
        "MacSignalAsset": dict(mac_match) if mac_match is not None else None,
    }


def update_existing_asset(connection, asset_id, record):
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


def build_repaired_ninja_record(payload):
    hostname = normalize_ninja_device_name(payload.get("RawDeviceName") or payload.get("Hostname"))
    all_ip_addresses = payload.get("AllIpAddresses") or split_delimited_values(payload.get("IpAddress"))
    parsed_ip_addresses = [value for value in (normalize_ipv4(item) for item in all_ip_addresses) if value]
    all_mac_addresses = payload.get("AllMacAddresses") or split_delimited_values(payload.get("MacAddress"))
    normalized_mac_addresses = [normalize_mac(value) for value in all_mac_addresses if normalize_mac(value)]

    record = {
        "AssetId": str(uuid.uuid4()),
        "Hostname": hostname,
        "IpAddress": choose_preferred_ninja_ip(parsed_ip_addresses),
        "MacAddress": choose_preferred_ninja_mac(normalized_mac_addresses),
        "AssetType": payload.get("AssetType"),
        "OperatingSystem": payload.get("OperatingSystem"),
        "Owner": payload.get("Owner") or payload.get("LastLogin"),
        "Environment": payload.get("Environment") or payload.get("Location"),
        "Source": payload.get("Source") or "ninja-export",
        "LastSeen": payload.get("LastSeen") or utc_now(),
        "Notes": payload.get("Notes"),
        "AllIpAddresses": parsed_ip_addresses,
        "AllMacAddresses": normalized_mac_addresses,
        "RawDeviceName": payload.get("RawDeviceName") or payload.get("Hostname"),
    }
    return record


def find_repair_target_asset(connection, record, excluded_asset_ids):
    excluded_ids = tuple(excluded_asset_ids)

    if record["MacAddress"]:
        placeholders = ",".join("?" for _ in excluded_ids)
        parameters = [record["MacAddress"], *excluded_ids]
        row = connection.execute(
            f"""
            SELECT *
            FROM assets
            WHERE LOWER(mac_address) = LOWER(?)
              AND asset_id NOT IN ({placeholders})
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            parameters,
        ).fetchone()
        if row is not None:
            return row, "mac-address"

    if is_hostname_candidate(record["Hostname"]):
        placeholders = ",".join("?" for _ in excluded_ids)
        rows = connection.execute(
            f"""
            SELECT *
            FROM assets
            WHERE COALESCE(hostname, '') <> ''
              AND asset_id NOT IN ({placeholders})
            ORDER BY last_seen DESC
            """,
            list(excluded_ids),
        ).fetchall()

        exact_matches = [
            row for row in rows
            if str(row["hostname"]).strip().lower() == str(record["Hostname"]).strip().lower()
        ]
        if len(exact_matches) == 1:
            return exact_matches[0], "hostname"
        if len(exact_matches) > 1:
            return None, None

        normalized = short_hostname(record["Hostname"])
        short_matches = [row for row in rows if short_hostname(row["hostname"]) == normalized]
        if len(short_matches) == 1:
            return short_matches[0], "short-hostname"

    return None, None


def repair_bad_ninja_mac_merge(db_path: Path, bad_mac_address: str):
    normalized_bad_mac = normalize_mac(bad_mac_address)
    if not normalized_bad_mac:
        raise ValueError(f"Invalid MAC address: {bad_mac_address}")

    connection = connect(db_path)
    repaired_assets = 0
    moved_observations = 0
    deleted_assets = 0
    created_assets = 0
    updated_assets = 0
    asset_summaries = []

    try:
        bad_assets = connection.execute(
            """
            SELECT asset_id, hostname, ip_address, mac_address, source
            FROM assets
            WHERE LOWER(mac_address) = LOWER(?)
              AND LOWER(COALESCE(source, '')) = 'ninja-export'
            ORDER BY asset_id
            """,
            (normalized_bad_mac,),
        ).fetchall()

        excluded_asset_ids = {row["asset_id"] for row in bad_assets}
        if not bad_assets:
            return {
                "DatabasePath": str(db_path),
                "BadMacAddress": normalized_bad_mac,
                "RepairedAssets": 0,
                "MovedObservations": 0,
                "DeletedAssets": 0,
                "CreatedAssets": 0,
                "UpdatedAssets": 0,
                "Assets": [],
            }

        for bad_asset in bad_assets:
            observations = connection.execute(
                """
                SELECT observation_id, run_id, observed_at, hostname, ip_address, mac_address, source, raw_payload
                FROM asset_observations
                WHERE asset_id = ?
                ORDER BY observed_at
                """,
                (bad_asset["asset_id"],),
            ).fetchall()

            touched_targets = []
            for observation in observations:
                payload = json.loads(observation["raw_payload"]) if observation["raw_payload"] else {}
                repaired_record = build_repaired_ninja_record(payload)

                if not repaired_record["MacAddress"]:
                    continue

                target_asset, _match_reason = find_repair_target_asset(connection, repaired_record, excluded_asset_ids)
                if target_asset is None:
                    target_asset_id = repaired_record["AssetId"]
                    connection.execute(
                        """
                        INSERT INTO assets (
                            asset_id, hostname, ip_address, mac_address, asset_type, operating_system,
                            mac_vendor, owner, environment, source, first_seen, last_seen, azure_verified, status, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            target_asset_id,
                            repaired_record["Hostname"],
                            repaired_record["IpAddress"],
                            repaired_record["MacAddress"],
                            repaired_record["AssetType"],
                            repaired_record["OperatingSystem"],
                            None,
                            repaired_record["Owner"],
                            repaired_record["Environment"],
                            repaired_record["Source"],
                            repaired_record["LastSeen"],
                            repaired_record["LastSeen"],
                            0,
                            "active",
                            repaired_record["Notes"],
                        ),
                    )
                    created_assets += 1
                else:
                    target_asset_id = target_asset["asset_id"]
                    update_existing_asset(connection, target_asset_id, repaired_record)
                    updated_assets += 1

                payload["Hostname"] = repaired_record["Hostname"]
                payload["IpAddress"] = repaired_record["IpAddress"]
                payload["MacAddress"] = repaired_record["MacAddress"]

                connection.execute(
                    """
                    UPDATE asset_observations
                    SET asset_id = ?,
                        observed_at = ?,
                        hostname = ?,
                        ip_address = ?,
                        mac_address = ?,
                        source = ?,
                        raw_payload = ?
                    WHERE observation_id = ?
                    """,
                    (
                        target_asset_id,
                        repaired_record["LastSeen"],
                        repaired_record["Hostname"],
                        repaired_record["IpAddress"],
                        repaired_record["MacAddress"],
                        repaired_record["Source"],
                        json.dumps(payload, separators=(",", ":")),
                        observation["observation_id"],
                    ),
                )
                moved_observations += 1
                touched_targets.append(target_asset_id)

            remaining = connection.execute(
                "SELECT COUNT(*) FROM asset_observations WHERE asset_id = ?",
                (bad_asset["asset_id"],),
            ).fetchone()[0]
            if remaining == 0:
                connection.execute("DELETE FROM assets WHERE asset_id = ?", (bad_asset["asset_id"],))
                deleted_assets += 1

            repaired_assets += 1
            asset_summaries.append(
                {
                    "AssetId": bad_asset["asset_id"],
                    "Hostname": bad_asset["hostname"],
                    "MovedObservations": len(observations),
                    "RemainingObservations": remaining,
                    "TouchedTargetAssets": sorted(set(touched_targets)),
                }
            )

        connection.commit()
    finally:
        connection.close()

    return {
        "DatabasePath": str(db_path),
        "BadMacAddress": normalized_bad_mac,
        "RepairedAssets": repaired_assets,
        "MovedObservations": moved_observations,
        "DeletedAssets": deleted_assets,
        "CreatedAssets": created_assets,
        "UpdatedAssets": updated_assets,
        "Assets": asset_summaries,
    }


def sample_report_rows(report_rows, limit=10):
    return report_rows[:limit]


def summarize_ninja_report(report_rows):
    summary = {
        "Processed": len(report_rows),
        "MatchByMac": 0,
        "MatchByShortHostname": 0,
        "IpOnlyReview": 0,
        "Conflicts": 0,
        "NewAssets": 0,
    }

    for row in report_rows:
        category = row["Category"]
        if category == "match-by-mac":
            summary["MatchByMac"] += 1
        elif category == "match-by-short-hostname":
            summary["MatchByShortHostname"] += 1
        elif category == "ip-only-review":
            summary["IpOnlyReview"] += 1
        elif category == "conflict":
            summary["Conflicts"] += 1
        elif category == "new-asset":
            summary["NewAssets"] += 1

    return summary


def compare_ninja_export(db_path: Path, input_path: Path, output_path: Path | None):
    records = load_ninja_records(input_path)
    connection = connect(db_path)
    report_rows = []

    try:
        for record in records:
            comparison = compare_ninja_record(connection, record)
            report_rows.append(
                {
                    "Device": record["RawDeviceName"],
                    "Hostname": record["Hostname"],
                    "IpAddress": record["IpAddress"],
                    "MacAddress": record["MacAddress"],
                    "AllIpAddresses": record["AllIpAddresses"],
                    "AllMacAddresses": record["AllMacAddresses"],
                    "LastSeen": record["LastSeen"],
                    "Owner": record["Owner"],
                    "Environment": record["Environment"],
                    "Category": comparison["Category"],
                    "Reasons": comparison["Reasons"],
                    "Conflict": comparison["Conflict"],
                    "MatchedAssetId": comparison["MatchedAsset"]["asset_id"] if comparison["MatchedAsset"] else None,
                    "MatchedHostname": comparison["MatchedAsset"]["hostname"] if comparison["MatchedAsset"] else None,
                    "MatchedIpAddress": comparison["MatchedAsset"]["ip_address"] if comparison["MatchedAsset"] else None,
                    "MatchedMacAddress": comparison["MatchedAsset"]["mac_address"] if comparison["MatchedAsset"] else None,
                    "IpSignalAssetId": comparison["IpSignalAsset"]["asset_id"] if comparison["IpSignalAsset"] else None,
                }
            )
    finally:
        connection.close()

    summary = summarize_ninja_report(report_rows)
    payload = {
        "InputPath": str(input_path),
        "DatabasePath": str(db_path),
        "Summary": summary,
        "ConflictSamples": sample_report_rows([row for row in report_rows if row["Category"] == "conflict"]),
        "IpOnlyReviewSamples": sample_report_rows([row for row in report_rows if row["Category"] == "ip-only-review"]),
        "Rows": report_rows,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return payload


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


def import_ninja_export(db_path: Path, input_path: Path, report_path: Path | None, notes: str | None):
    records = load_ninja_records(input_path)
    connection = connect(db_path)
    inserted = 0
    updated = 0
    skipped_ip_only = 0
    skipped_conflicts = 0
    observations = 0
    match_reasons = {}
    report_rows = []
    run_id = str(uuid.uuid4())
    started_at = utc_now()

    try:
        connection.execute(
            """
            INSERT INTO discovery_runs (run_id, source_file, source_type, started_at, completed_at, asset_count, notes)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (run_id, str(input_path), "ninja-export", started_at, started_at, notes),
        )

        for record in records:
            comparison = compare_ninja_record(connection, record)
            category = comparison["Category"]
            report_row = {
                "Device": record["RawDeviceName"],
                "Hostname": record["Hostname"],
                "IpAddress": record["IpAddress"],
                "MacAddress": record["MacAddress"],
                "AllIpAddresses": record["AllIpAddresses"],
                "AllMacAddresses": record["AllMacAddresses"],
                "Category": category,
                "Reasons": comparison["Reasons"],
                "Conflict": comparison["Conflict"],
                "MatchedAssetId": comparison["MatchedAsset"]["asset_id"] if comparison["MatchedAsset"] else None,
                "MatchedHostname": comparison["MatchedAsset"]["hostname"] if comparison["MatchedAsset"] else None,
            }

            if category == "conflict":
                skipped_conflicts += 1
                report_rows.append(report_row)
                continue

            if category == "ip-only-review":
                skipped_ip_only += 1
                report_rows.append(report_row)
                continue

            import_record = {
                "AssetId": record["AssetId"],
                "Hostname": record["Hostname"],
                "IpAddress": record["IpAddress"],
                "MacAddress": record["MacAddress"],
                "AssetType": record["AssetType"],
                "OperatingSystem": record["OperatingSystem"],
                "Owner": record["Owner"],
                "Environment": record["Environment"],
                "Source": record["Source"],
                "LastSeen": record["LastSeen"],
                "Notes": record["Notes"],
            }

            if comparison["MatchedAsset"] is not None:
                import_record["AssetId"] = comparison["MatchedAsset"]["asset_id"]

            asset_id, action, match_reason = upsert_asset(connection, import_record)
            if action == "inserted":
                inserted += 1
            else:
                updated += 1
                effective_reason = match_reason or ",".join(comparison["Reasons"]) or "ninja-export"
                match_reasons[effective_reason] = match_reasons.get(effective_reason, 0) + 1

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
            report_rows.append(report_row)

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

    summary = summarize_ninja_report(report_rows)
    payload = {
        "RunId": run_id,
        "SourceFile": str(input_path),
        "SourceType": "ninja-export",
        "Processed": len(records),
        "InsertedAssets": inserted,
        "UpdatedAssets": updated,
        "ObservationsAdded": observations,
        "SkippedIpOnlyReview": skipped_ip_only,
        "SkippedConflicts": skipped_conflicts,
        "MatchReasons": match_reasons,
        "ComparisonSummary": summary,
    }

    if report_path is not None:
        report_payload = {
            "InputPath": str(input_path),
            "DatabasePath": str(db_path),
            "ImportSummary": payload,
            "ConflictSamples": sample_report_rows([row for row in report_rows if row["Category"] == "conflict"]),
            "IpOnlyReviewSamples": sample_report_rows([row for row in report_rows if row["Category"] == "ip-only-review"]),
            "Rows": report_rows,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return payload


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

    compare_ninja_parser = subparsers.add_parser("compare-ninja-export")
    compare_ninja_parser.add_argument("--db-path", required=True)
    compare_ninja_parser.add_argument("--input-path", required=True)
    compare_ninja_parser.add_argument("--output-path")

    import_ninja_parser = subparsers.add_parser("import-ninja-export")
    import_ninja_parser.add_argument("--db-path", required=True)
    import_ninja_parser.add_argument("--input-path", required=True)
    import_ninja_parser.add_argument("--report-path")
    import_ninja_parser.add_argument("--notes")

    repair_bad_mac_parser = subparsers.add_parser("repair-bad-ninja-mac-merge")
    repair_bad_mac_parser.add_argument("--db-path", required=True)
    repair_bad_mac_parser.add_argument("--bad-mac-address", required=True)

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
        elif args.command == "compare-ninja-export":
            output_path = Path(args.output_path) if args.output_path else None
            result = compare_ninja_export(Path(args.db_path), Path(args.input_path), output_path)
        elif args.command == "import-ninja-export":
            report_path = Path(args.report_path) if args.report_path else None
            result = import_ninja_export(Path(args.db_path), Path(args.input_path), report_path, args.notes)
        elif args.command == "repair-bad-ninja-mac-merge":
            result = repair_bad_ninja_mac_merge(Path(args.db_path), args.bad_mac_address)
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
