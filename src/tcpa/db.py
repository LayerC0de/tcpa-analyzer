"""SQLite schema and connection handling.

Design note: campaigns -- not phone numbers -- are the unit of legal action.
A single operation rotates through dozens of disposable DIDs, so the schema
treats a number as evidence *of* a campaign rather than as a defendant.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from .phone import normalize

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "tcpa.db"

SCHEMA = """
-- Raw call events, one row per call as reported by the source device/carrier.
CREATE TABLE IF NOT EXISTS calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT NOT NULL,        -- 'android', 'att', 'ios'
    source_row_id     TEXT,                 -- native id, for idempotent re-import
    number_raw        TEXT,
    number            TEXT,                 -- normalized 10-digit, NULL if not NANP
    contact_name      TEXT,                 -- non-NULL => in address book => not spam
    ts_utc            INTEGER NOT NULL,     -- epoch ms
    local_iso         TEXT NOT NULL,
    local_date        TEXT NOT NULL,
    local_hour        INTEGER NOT NULL,
    duration_s        INTEGER NOT NULL DEFAULT 0,
    direction         TEXT NOT NULL,        -- INCOMING/OUTGOING/MISSED/REJECTED/BLOCKED/VOICEMAIL
    presentation      TEXT,                 -- ALLOWED/RESTRICTED/PAYPHONE/UNKNOWN
    block_reason      INTEGER DEFAULT 0,
    geo               TEXT,
    own_number        TEXT,                 -- which of your lines received it
    transcription     TEXT,                 -- voicemail transcript, when present
    -- 1 when duration came from billed minutes rather than exact seconds.
    -- Duration-sensitive analysis MUST exclude these rows.
    duration_estimated INTEGER NOT NULL DEFAULT 0,
    -- 1 when this carrier row restates a call the device log already has.
    -- Kept for source comparison; excluded from every rollup and count.
    dup_of_device     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source, source_row_id)
);
CREATE INDEX IF NOT EXISTS idx_calls_number ON calls(number);
CREATE INDEX IF NOT EXISTS idx_calls_ts ON calls(ts_utc);

-- Per-number rollup plus enrichment. One row per distinct dialable number.
CREATE TABLE IF NOT EXISTS numbers (
    number            TEXT PRIMARY KEY,
    npa_nxx           TEXT NOT NULL,
    is_toll_free      INTEGER NOT NULL DEFAULT 0,
    first_seen        TEXT,
    last_seen         TEXT,
    call_count        INTEGER NOT NULL DEFAULT 0,
    answered_count    INTEGER NOT NULL DEFAULT 0,
    zero_dur_count    INTEGER NOT NULL DEFAULT 0,
    max_duration_s    INTEGER NOT NULL DEFAULT 0,
    geo               TEXT,
    -- enrichment (populated by the enrich stage, NULL until then)
    line_type         TEXT,                 -- VOIP_WHOLESALE / WIRELESS / CLEC_ILEC
    carrier_name      TEXT,                 -- block holder, NOT necessarily the subscriber
    carrier_ocn       TEXT,                 -- Operating Company Number: who to subpoena
    rate_center       TEXT,
    lata              TEXT,
    ilec_name         TEXT,
    is_spoofed_guess  INTEGER,
    enriched_at       TEXT
);

-- A campaign is one operation, inferred from shared infrastructure/behavior.
CREATE TABLE IF NOT EXISTS campaigns (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    label             TEXT NOT NULL,
    detection_method  TEXT NOT NULL,        -- 'fingerprint', 'did_block', 'manual'
    confidence        REAL NOT NULL DEFAULT 0.0,
    pitch_vertical    TEXT,                 -- solar / warranty / medicare / debt / ...
    notes             TEXT,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS campaign_numbers (
    campaign_id       INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    number            TEXT NOT NULL REFERENCES numbers(number),
    evidence          TEXT,
    PRIMARY KEY (campaign_id, number)
);

-- Text messages. Under the TCPA a text to a cell is a "call", so these are a
-- separate violation surface with the same statutory damages. Only carrier
-- exports carry them -- the device call log has no text history.
CREATE TABLE IF NOT EXISTS texts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT NOT NULL,
    source_row_id     TEXT,
    number            TEXT,
    number_raw        TEXT,
    direction         TEXT,
    kind              TEXT,                 -- TEXT / MMS
    ts_utc            INTEGER NOT NULL,
    local_iso         TEXT,
    local_date        TEXT,
    own_number        TEXT,
    UNIQUE (source, source_row_id)
);
CREATE INDEX IF NOT EXISTS idx_texts_number ON texts(number);

-- FCC consumer complaints (open dataset vakf-fz8e), used to corroborate a
-- campaign with independent third-party reports. `exact_match` distinguishes
-- a complaint about one of YOUR numbers (direct) from one about a neighbouring
-- number in the same DID block (circumstantial). Never conflate the two.
CREATE TABLE IF NOT EXISTS complaints (
    fcc_id            TEXT PRIMARY KEY,
    caller_id_number  TEXT,
    npa_nxx           TEXT,
    advertiser_phone  TEXT,                 -- callback number: often leads to the seller
    call_type         TEXT,                 -- 'Prerecorded Voice' => 227(b) predicate
    issue             TEXT,
    issue_date        TEXT,
    state             TEXT,
    zip               TEXT,
    method            TEXT,
    exact_match       INTEGER NOT NULL DEFAULT 0,
    fetched_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_complaints_block ON complaints(npa_nxx);
CREATE INDEX IF NOT EXISTS idx_complaints_number ON complaints(caller_id_number);

-- Resolved legal entities. This is what you actually sue -- or subpoena.
CREATE TABLE IF NOT EXISTS entities (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id       INTEGER REFERENCES campaigns(id),
    legal_name        TEXT,
    dba               TEXT,
    -- 'caller'  the dialer, often an offshore shell with no assets
    -- 'seller'  who the pitch was for: domestic, collectable, vicariously liable
    -- 'carrier' the DID block holder. NOT a defendant -- the subpoena/traceback path
    role              TEXT,
    state_of_reg      TEXT,
    registered_agent  TEXT,
    agent_address     TEXT,
    prior_tcpa_suits  INTEGER,
    source_url        TEXT,
    confidence        REAL DEFAULT 0.0
);

-- Numbers the owner has identified as legitimate (their bank, a doctor's office)
-- but that never show up as a contact in any source. Mirrored from
-- known_numbers.txt on every connect; the file is the source of truth.
CREATE TABLE IF NOT EXISTS known_numbers (
    number            TEXT PRIMARY KEY,
    note              TEXT
);

-- RespOrg lookups for toll-free numbers. A toll-free number has no carrier
-- block; the Responsible Organization on file in the Somos registry is the
-- equivalent subpoena / traceback path. Like the block holder, it is NOT the
-- caller. Kept as a dated log rather than columns on `numbers` because:
--   - the rollup is rebuilt and prunes rows, which would lose manual entries,
--   - FCC callback numbers never appear in `numbers` at all, and
--   - numbers move between RespOrgs, so the date of each lookup matters.
-- `method` separates a third-party automated result (a lead) from one the
-- owner confirmed on somos.com (citable). Never present the first as the second.
CREATE TABLE IF NOT EXISTS resporg_lookups (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    number            TEXT NOT NULL,        -- normalized 10-digit toll-free
    resporg_id        TEXT,                 -- e.g. VZM01; NULL = no registry record
    resporg_name      TEXT,                 -- company holding that RespOrg ID
    resporg_group     TEXT,                 -- parent company, when known
    status            TEXT,                 -- WORKING / SPARE / ... / NOT_FOUND
    status_since      TEXT,                 -- date of the latest registry change
    checked_on        TEXT NOT NULL,        -- date the lookup was made
    method            TEXT NOT NULL,        -- 'auto' or 'manual'
    source            TEXT NOT NULL,        -- where the answer came from
    note              TEXT,
    raw_json          TEXT,                 -- full response, for auto lookups
    recorded_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (number, method, checked_on)
);
CREATE INDEX IF NOT EXISTS idx_resporg_number ON resporg_lookups(number);

-- Revocation events: the willfulness predicate. $500 -> $1500 per call after this.
-- Applies to calls from `number` placed after ts_utc. Extending one revocation
-- to a whole campaign of rotating numbers is a legal judgment, never automatic.
CREATE TABLE IF NOT EXISTS revocations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id       INTEGER REFERENCES campaigns(id),
    number            TEXT,
    ts_utc            INTEGER NOT NULL,
    method            TEXT,                 -- 'verbal' / 'written' / 'sms'
    evidence_path     TEXT,                 -- recording or screenshot on disk
    verbatim          TEXT,
    call_id           INTEGER REFERENCES calls(id),  -- the call it was said on
    basis             TEXT,                 -- 'recording' / 'recollection' / 'document'
    note              TEXT,
    entered_on        TEXT,                 -- when it was recorded in this tool
    local_iso         TEXT                  -- local time of the request
);
"""


# Columns added after the first databases were created. SQLite has no
# ADD COLUMN IF NOT EXISTS, so they are applied conditionally.
_MIGRATIONS = {
    "numbers": {
        "rate_center": "TEXT",
        "lata": "TEXT",
        "ilec_name": "TEXT",
    },
    "calls": {
        "duration_estimated": "INTEGER NOT NULL DEFAULT 0",
        "dup_of_device": "INTEGER NOT NULL DEFAULT 0",
    },
    "revocations": {
        "call_id": "INTEGER REFERENCES calls(id)",
        "basis": "TEXT",
        "note": "TEXT",
        "entered_on": "TEXT",
        "local_iso": "TEXT",
    },
}


def _migrate(con: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    con.commit()


KNOWN_NUMBERS_FILE = "known_numbers.txt"


def parse_known_numbers(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse the known-numbers file into ({number: note}, [invalid lines]).

    One number per line, any common format, with an optional note after `#`:

        202-555-0100   # Example Bank -- auto loan

    Lines that are blank or start with `#` are ignored. A line whose number
    does not normalize is returned as invalid rather than silently dropped,
    since a typo here would quietly leave a legitimate caller in the targets.
    """
    known, invalid = {}, []
    for line in text.splitlines():
        raw, _, note = line.partition("#")
        if not raw.strip():
            continue
        number = normalize(raw)
        if number is None:
            invalid.append(line.strip())
        else:
            known[number] = note.strip()
    return known, invalid


def sync_known_numbers(con: sqlite3.Connection, path: Path) -> list[str]:
    """Mirror the known-numbers file into its table. Returns invalid lines."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    known, invalid = parse_known_numbers(text)
    con.execute("DELETE FROM known_numbers")
    con.executemany("INSERT INTO known_numbers (number, note) VALUES (?, ?)",
                    known.items())
    con.commit()
    return invalid


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path) if path else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    _migrate(con)
    for line in sync_known_numbers(con, path.parent / KNOWN_NUMBERS_FILE):
        print(f"warning: {KNOWN_NUMBERS_FILE}: not a NANP number, ignored: {line!r}",
              file=sys.stderr)
    return con


# A number is a KNOWN CONTACT if any of these is true:
#   - any source ever attached an address-book name to it,
#   - the account holder placed an outgoing call to it, or
#   - the account holder listed it in known_numbers.txt.
# The second test carries the weight for carrier data, which exports no contact
# names at all. Without it every relative and doctor's office is scored as an
# unsolicited caller -- and because they call often, they dominate the ranking.
# Calling someone is affirmative evidence of a relationship, which is also the
# opposite of the "no prior express consent" a TCPA claim requires. The third
# covers businesses the owner has a relationship with but never calls or saves.
KNOWN_CONTACT_SQL = """
    SELECT number FROM calls
    WHERE number IS NOT NULL AND contact_name IS NOT NULL AND contact_name != ''
    UNION
    SELECT number FROM calls
    WHERE number IS NOT NULL AND direction = 'OUTGOING'
    UNION
    SELECT number FROM known_numbers
"""


def rebuild_numbers(con: sqlite3.Connection) -> int:
    """Recompute the per-number rollup from raw calls.

    Only inbound calls with no contact name count toward spam statistics --
    a number in your address book is not an unsolicited caller.

    Upserts rather than DELETE+INSERT so that enrichment (carrier, OCN, rate
    center) survives re-ingesting the call log. Enrichment is expensive and
    rate-limited; losing it on every `ingest` would be a serious defect.
    """
    con.execute(f"""
        INSERT INTO numbers (number, npa_nxx, is_toll_free, first_seen, last_seen,
                             call_count, answered_count, zero_dur_count,
                             max_duration_s, geo)
        SELECT number,
               substr(number, 1, 6),
               CASE WHEN substr(number,1,3) IN
                    ('800','833','844','855','866','877','888') THEN 1 ELSE 0 END,
               MIN(local_date), MAX(local_date),
               COUNT(*),
               SUM(CASE WHEN direction='INCOMING' AND duration_s > 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN duration_s = 0 THEN 1 ELSE 0 END),
               MAX(duration_s),
               MAX(geo)
        FROM calls
        WHERE number IS NOT NULL
          AND direction IN ('INCOMING','MISSED','REJECTED','BLOCKED')
          AND dup_of_device = 0
          AND number NOT IN ({KNOWN_CONTACT_SQL})
        GROUP BY number
        ON CONFLICT(number) DO UPDATE SET
            first_seen     = excluded.first_seen,
            last_seen      = excluded.last_seen,
            call_count     = excluded.call_count,
            answered_count = excluded.answered_count,
            zero_dur_count = excluded.zero_dur_count,
            max_duration_s = excluded.max_duration_s,
            geo            = excluded.geo
    """)
    # Drop rollups for numbers that no longer qualify (e.g. a caller was added
    # to contacts since the last run, so they are no longer "unknown inbound").
    stale = f"""
        SELECT number FROM numbers WHERE number NOT IN (
            SELECT number FROM calls
            WHERE number IS NOT NULL
              AND direction IN ('INCOMING','MISSED','REJECTED','BLOCKED')
              AND dup_of_device = 0
              AND number NOT IN ({KNOWN_CONTACT_SQL})
        )
    """
    # campaign_numbers references numbers(number). A member can stop qualifying
    # -- most often because the account holder later called it back, which makes
    # it a known contact. Clear the dependent rows first; campaigns are derived
    # data and `analyze` rebuilds them from scratch.
    con.execute(f"DELETE FROM campaign_numbers WHERE number IN ({stale})")
    con.execute(f"DELETE FROM numbers WHERE number IN ({stale})")
    con.commit()
    return con.execute("SELECT COUNT(*) FROM numbers").fetchone()[0]
