"""SQLite schema and connection handling.

Design note: campaigns -- not phone numbers -- are the unit of legal action.
A single operation rotates through dozens of disposable DIDs, so the schema
treats a number as evidence *of* a campaign rather than as a defendant.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

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

-- Revocation events: the willfulness predicate. $500 -> $1500 per call after this.
CREATE TABLE IF NOT EXISTS revocations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id       INTEGER REFERENCES campaigns(id),
    number            TEXT,
    ts_utc            INTEGER NOT NULL,
    method            TEXT,                 -- 'verbal' / 'written' / 'sms'
    evidence_path     TEXT,                 -- recording or screenshot on disk
    verbatim          TEXT
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
}


def _migrate(con: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    con.commit()


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path) if path else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


# A number is a KNOWN CONTACT if either is true:
#   - any source ever attached an address-book name to it, or
#   - the account holder placed an outgoing call to it.
# The second test carries the weight for carrier data, which exports no contact
# names at all. Without it every relative and doctor's office is scored as an
# unsolicited caller -- and because they call often, they dominate the ranking.
# Calling someone is affirmative evidence of a relationship, which is also the
# opposite of the "no prior express consent" a TCPA claim requires.
KNOWN_CONTACT_SQL = """
    SELECT number FROM calls
    WHERE number IS NOT NULL AND contact_name IS NOT NULL AND contact_name != ''
    UNION
    SELECT number FROM calls
    WHERE number IS NOT NULL AND direction = 'OUTGOING'
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
