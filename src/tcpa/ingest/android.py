"""Ingest the Android call log via `adb shell content query`.

The device call log is strictly better evidence than a carrier bill for TCPA
work: carriers record *billable* usage, so unanswered and blocked calls -- the
ones that matter most -- frequently never appear on a statement.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ..phone import normalize

# Values may themselves contain ", " (geocoded_location="Buffalo, NY"), so split
# only where the next token is a bare `key=`.
_FIELD_SPLIT = re.compile(r",\s+(?=[a-z0-9_]+=)")
_ROW_PREFIX = re.compile(r"^Row:\s+\d+\s+")

CALL_TYPES = {
    1: "INCOMING", 2: "OUTGOING", 3: "MISSED", 4: "VOICEMAIL",
    5: "REJECTED", 6: "BLOCKED", 7: "ANSWERED_EXTERNALLY",
}
PRESENTATION = {1: "ALLOWED", 2: "RESTRICTED", 3: "PAYPHONE", 4: "UNKNOWN"}

CONTENT_URI = "content://call_log/calls"


def _local(ms: int, tz_name: str = "America/New_York") -> datetime:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo(tz_name))
    except Exception:
        # zoneinfo needs the `tzdata` package on Windows. Fall back to a US
        # Eastern approximation rather than silently emitting UTC hours, which
        # would corrupt the 8am-9pm calling-window analysis.
        return dt + timedelta(hours=-4 if 3 <= dt.month <= 11 else -5)


def pull(dest: Path, adb: str | None = None) -> Path:
    """Dump the device call log to `dest`. Returns the path written."""
    adb = adb or shutil.which("adb")
    if not adb:
        raise RuntimeError("adb not found on PATH; install Android platform-tools")

    devices = subprocess.run([adb, "devices"], capture_output=True, text=True, check=True)
    attached = [l for l in devices.stdout.splitlines()[1:] if l.strip().endswith("device")]
    if not attached:
        raise RuntimeError(
            "No authorized device. Connect by USB, enable USB debugging, "
            "and accept the 'Allow USB debugging?' prompt on the phone."
        )

    out = subprocess.run([adb, "shell", "content", "query", "--uri", CONTENT_URI],
                         capture_output=True, text=True, check=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(out.stdout, encoding="utf-8")
    return dest


def parse(raw_path: Path, tz_name: str = "America/New_York") -> list[dict]:
    records = []
    for line in raw_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("Row:"):
            continue
        fields = {}
        for part in _FIELD_SPLIT.split(_ROW_PREFIX.sub("", line.rstrip())):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            fields[k.strip()] = None if v == "NULL" else v

        def as_int(key, default=None):
            try:
                return int(fields.get(key))
            except (TypeError, ValueError):
                return default

        ts = as_int("date", 0)
        loc = _local(ts, tz_name)
        raw_number = fields.get("normalized_number") or fields.get("number")
        records.append({
            "source": "android",
            "source_row_id": fields.get("_id"),
            "number_raw": fields.get("number"),
            "number": normalize(raw_number),
            "contact_name": fields.get("name"),
            "ts_utc": ts,
            "local_iso": loc.strftime("%Y-%m-%d %H:%M:%S"),
            "local_date": loc.strftime("%Y-%m-%d"),
            "local_hour": loc.hour,
            "duration_s": as_int("duration", 0),
            "direction": CALL_TYPES.get(as_int("type"), "UNKNOWN"),
            "presentation": PRESENTATION.get(as_int("presentation")),
            "block_reason": as_int("block_reason", 0),
            "geo": fields.get("geocoded_location"),
            "own_number": fields.get("phone_account_address"),
            "transcription": fields.get("transcription"),
        })
    return records


COLUMNS = ("source", "source_row_id", "number_raw", "number", "contact_name",
           "ts_utc", "local_iso", "local_date", "local_hour", "duration_s",
           "direction", "presentation", "block_reason", "geo", "own_number",
           "transcription")


def load(con, records: list[dict]) -> int:
    """Insert records idempotently. Re-running an import adds only new calls."""
    before = con.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    con.executemany(
        f"INSERT OR IGNORE INTO calls ({','.join(COLUMNS)}) "
        f"VALUES ({','.join('?' * len(COLUMNS))})",
        [tuple(r[c] for c in COLUMNS) for r in records],
    )
    con.commit()
    return con.execute("SELECT COUNT(*) FROM calls").fetchone()[0] - before
