"""Shared snapshot, calendar, and pickup-screening rules for the TLC pipeline."""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa

ROOT = Path(__file__).resolve().parents[1]
BOROUGHS = {"Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"}
THRESHOLD_PERCENT = 1.0
TZ = "America/New_York"
SUPPORTED_MONTHS = ("2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09")
PICKUP_COLUMNS = ("tpep_pickup_datetime", "PULocationID")
UTILS_PATH = Path(__file__).resolve()


def month_bounds(month: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Calculate half-open recorded-local calendar bounds without guessing DST.

    Args:
        month: Strict YYYY-MM calendar month.

    Output:
        tuple: Naive month start and next-month start for source-clock screening.

    Raises:
        ValueError: Month is invalid or crosses a New York clock transition.
    """
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("Use YYYY-MM, for example 2025-05")
    start = pd.Timestamp(datetime.strptime(month, "%Y-%m"))
    end = start + pd.offsets.MonthBegin(1)
    if start.tz_localize(TZ).utcoffset() != end.tz_localize(TZ).utcoffset():
        raise ValueError("Clock-change months need a separately approved DST policy")
    return start, end


def sha256(path: Path) -> str:
    """Fingerprint a file using bounded-memory reads.

    Args:
        path: File to read without modification.

    Output:
        str: SHA-256 hexadecimal digest of the file contents.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_path(value: str) -> Path:
    """Anchor relative paths to the repository root; preserve absolute paths.

    Args:
        value: Relative or absolute filesystem path.

    Output:
        Path: Project-anchored or unchanged absolute path; existence is not checked.
    """
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def verify_input(path: Path, entries: list[dict]) -> dict:
    """Return provenance after matching one manifest entry and verifying size/hash.

    Args:
        path: Local input file to verify.
        entries: Manifest file records containing paths, sizes, hashes, and sources.

    Output:
        dict: Verified path, size, checksum, and recorded source/download metadata.

    Raises:
        ValueError: Manifest match is ambiguous/missing or input size/hash differs.
    """
    matches = [item for item in entries if project_path(item["path"]).resolve() == path.resolve()]
    if len(matches) != 1:
        raise ValueError(f"Expected one manifest entry for {path}; found {len(matches)}")
    item = matches[0]
    size = path.stat().st_size
    digest = sha256(path)
    if size != item["size_bytes"] or digest != item["sha256"]:
        raise ValueError(f"Manifest size/checksum mismatch: {path}. Preserve and investigate the file.")
    return {"path": str(path.resolve()), "size_bytes": size, "sha256": digest,
            "manifest_match": True, "source_url": item["source_url"],
            "download_date": item.get("download_date"),
            "download_date_status": item.get("download_date_status")}


def read_lookup(path: Path) -> tuple[dict[int, str], set[int]]:
    """Validate lookup keys/labels; return ID-to-borough mapping and NYC zone IDs.

    Args:
        path: Taxi-zone lookup CSV with LocationID, Borough, and Zone columns.

    Output:
        tuple[dict[int, str], set[int]]: All ID-to-borough mappings and the subset
        of IDs belonging to NYC's five boroughs.

    Raises:
        ValueError: Required columns/labels are missing, IDs are invalid or
        duplicated, or no usable NYC reference entries exist.
    """
    lookup: dict[int, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"LocationID", "Borough", "Zone"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Lookup lacks required columns: {sorted(required)}")
        for line, row in enumerate(reader, start=2):
            try:
                zone_id = int(row["LocationID"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid lookup LocationID at line {line}") from exc
            if zone_id in lookup:
                raise ValueError(f"Duplicate lookup LocationID: {zone_id}; join would be ambiguous")
            if not row["Borough"] or not row["Zone"]:
                raise ValueError(f"Missing borough/zone label at lookup line {line}")
            lookup[zone_id] = row["Borough"].strip()
    if not lookup:
        raise ValueError("Lookup is empty")
    nyc = {zone_id for zone_id, borough in lookup.items() if borough in BOROUGHS}
    if not nyc:
        raise ValueError("Lookup contains no recognized NYC borough zones")
    return lookup, nyc


def verify_snapshots(inputs: list[dict], baseline_inputs: list[dict]) -> None:
    """Verify file identities across machines.

    Args:
        inputs: Verified local input metadata.
        baseline_inputs: File identities recorded by an earlier run.

    Output:
        None. Raises ValueError if a filename, byte size, or digest differs.
    """
    for item in inputs:
        matches = [old for old in baseline_inputs if Path(old["path"]).name == Path(item["path"]).name]
        if len(matches) != 1 or any(matches[0][key] != item[key] for key in ("sha256", "size_bytes")):
            raise ValueError(f"Input differs from baseline snapshot: {item['path']}")


def pickup_time_type(schema: pa.Schema) -> pa.TimestampType:
    """Validate the pickup columns before scanning.

    Args:
        schema: Source Arrow schema.

    Output:
        Arrow timestamp type, including its published timezone metadata.
    """
    required = PICKUP_COLUMNS
    if any(schema.names.count(name) != 1 for name in required):
        raise ValueError("Trip file must contain exactly one pickup timestamp and pickup-zone column")
    time_type = schema.field(required[0]).type
    zone_type = schema.field(required[1]).type
    if not pa.types.is_timestamp(time_type):
        raise ValueError(f"Unexpected timestamp type {time_type}; review schema before parsing")
    if not pa.types.is_integer(zone_type):
        raise ValueError(f"Unexpected zone type {zone_type}; review schema before coercing identifiers")
    return time_type


def classify_pickups(frame, mapped, nyc, start, end):
    """Apply the project rules to one batch of pickup records.

    Args:
        frame: Batch with the two validated pickup columns.
        mapped: All recognized lookup IDs.
        nyc: In-scope NYC pickup IDs.
        start: Inclusive local month start.
        end: Exclusive local month end.

    Output:
        Local timestamps, nullable zone IDs, diagnostic masks, and exclusive masks.
    """
    original_time = frame[PICKUP_COLUMNS[0]]
    # Preserve nullable integer IDs rather than filling missing IDs with a real code.
    zone = frame[PICKUP_COLUMNS[1]].astype("Int64")
    missing_time = original_time.isna()
    pickup = pd.to_datetime(original_time, errors="coerce")
    if pickup.dt.tz is not None:
        pickup = pickup.dt.tz_convert(TZ).dt.tz_localize(None)
    # Naive source timestamps are screened AS NYC wall time, not proven to be so.
    invalid_time = pickup.isna() & ~missing_time
    valid_time = pickup.notna()
    missing_zone = zone.isna()
    unmapped_zone = ~missing_zone & ~zone.isin(mapped)
    bad_zone = missing_zone | unmapped_zone
    bad_time = ~valid_time
    in_month = valid_time & pickup.ge(start) & pickup.lt(end)
    out_of_month = valid_time & ~in_month
    outside_nyc = in_month & ~bad_zone & ~zone.isin(nyc)
    accepted = in_month & zone.isin(nyc)

    masks = {"missing_pickup_timestamp": missing_time,
             "unparseable_pickup_timestamp": invalid_time,
             "missing_pickup_zone": missing_zone,
             "unmapped_pickup_zone": unmapped_zone,
             "combined_key_quality_failures": bad_time | bad_zone,
             "out_of_month_timestamp": out_of_month,
             "in_month_mapped_non_nyc_scope_exclusions": outside_nyc,
             "accepted_for_month_nyc_screening": accepted}
    exclusive = {
        "bad_timestamp": bad_time,
        "bad_zone_after_timestamp_check": valid_time & bad_zone,
        "out_of_month_after_key_checks": out_of_month & ~bad_zone,
        "mapped_non_nyc_in_month": outside_nyc,
        "accepted": accepted,
    }
    return pickup, zone, masks, exclusive


def april_keys(counts: dict) -> dict:
    """Return counts using the original April report schema.

    Args:
        counts: Monthly diagnostic or exclusive-disposition counts.

    Output:
        Dictionary preserving the historical April field names.
    """
    return {name.replace("month", "april"): value for name, value in counts.items()}


def hourly_coverage(hours, start, end):
    """Summarize observed hourly counts and flag gaps for review.

    Args:
        hours: Counts keyed by recorded local hour.
        start: Inclusive local month start.
        end: Exclusive local month end.

    Output:
        Hourly coverage table and daily totals for the full calendar month.
    """
    index = pd.date_range(start, end, freq="h", inclusive="left")
    observed = pd.Series([hours.get(hour, 0) for hour in index], index=index, dtype="int64")
    hourly = observed.rename("observed_accepted_records").to_frame()
    hourly.index.name = "hour_start_assumed_nyc_local"
    reference = observed.groupby(observed.index.hour).transform("median")
    hourly["same_clock_hour_month_median"] = reference
    hourly["zero_observed_records"] = observed.eq(0)

    # Diagnostic heuristic, NOT an acceptance threshold or proof of an outage.
    hourly["unusually_low_review_flag"] = observed.gt(0) & observed.lt(0.1 * reference)
    daily = observed.resample("D").sum().rename("observed_accepted_records").to_frame()
    daily.index.name = "date_assumed_nyc_local"
    return hourly, daily


def screen_batches(parquet, lookup, nyc, start, end):
    """Count and reconcile pickups over bounded Parquet batches.

    Args:
        parquet: Open Parquet file with validated pickup columns.
        lookup: All recognized zone IDs.
        nyc: In-scope zone IDs.
        start: Inclusive local month start.
        end: Exclusive local month end.

    Output:
        Diagnostics, exclusive counts, hourly and zone counts, and timestamp extrema.
    """
    counts: Counter = Counter()
    dispositions: Counter = Counter()
    hours: Counter = Counter()
    zones: Counter = Counter()
    minimum = maximum = None
    for batch in parquet.iter_batches(batch_size=100_000, columns=list(PICKUP_COLUMNS)):
        frame = batch.to_pandas()
        pickup, zone, masks, exclusive = classify_pickups(frame, lookup, nyc, start, end)
        counts["total_rows"] += len(frame)
        counts.update({name: int(mask.sum()) for name, mask in masks.items()})
        dispositions.update({name: int(mask.sum()) for name, mask in exclusive.items()})
        accepted = exclusive["accepted"]
        valid_pickups = pickup.dropna()
        if not valid_pickups.empty:
            batch_min, batch_max = valid_pickups.min(), valid_pickups.max()
            minimum = batch_min if minimum is None else min(minimum, batch_min)
            maximum = batch_max if maximum is None else max(maximum, batch_max)
        hours.update({key: int(value) for key, value in
                      pickup[accepted].dt.floor("h").value_counts().items()})
        zones.update({int(key): int(value) for key, value in zone[accepted].value_counts().items()})

    total = counts["total_rows"]
    if total == 0:
        raise ValueError("Trip file is empty")
    if total != parquet.metadata.num_rows:
        raise ValueError("Scanned rows do not match Parquet metadata")
    if sum(dispositions.values()) != total:
        raise ValueError("Exclusive row dispositions do not reconcile to source rows")
    if sum(hours.values()) != counts["accepted_for_month_nyc_screening"]:
        raise ValueError("Hourly counts do not reconcile to accepted rows")
    if sum(zones.values()) != sum(hours.values()):
        raise ValueError("Zone totals do not reconcile to hourly totals")

    return counts, dispositions, hours, zones, minimum, maximum
