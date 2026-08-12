"""Campaign detection: find one operation hiding behind many disposable numbers.

Two independent signals, deliberately kept separate so they can corroborate
each other rather than being blended into one opaque score:

  1. BEHAVIORAL  -- numbers that share a call pattern too specific to be chance
                    (identical call count, same-day spacing, same duration shape).
  2. INFRASTRUCTURE -- numbers drawn from the same NPA-NXX block, i.e. one
                    dialer leasing one contiguous range of DIDs.

Neither is conclusive alone. A hospital legitimately holds a DID block; a
coincidence can produce one matching pair. Their intersection rarely lies.
"""
from __future__ import annotations

from collections import Counter, defaultdict

# A local business holding consecutive DIDs looks identical to a dialer on the
# block signal alone. Blocks whose numbers hold long conversations are almost
# certainly legitimate, so they are excluded before clustering.
LEGIT_CONVERSATION_S = 180


def _inbound_unknown(con):
    return con.execute("""
        SELECT * FROM numbers ORDER BY call_count DESC, number
    """).fetchall()


def fingerprint_cluster(con, max_answer_s: int = 60, same_day_hours: float = 24.0):
    """Numbers with the burn-after-use signature.

    Exactly two calls, within one day of each other, one connected briefly and
    one never connecting at all -- then the number is retired. Legitimate
    callers do not behave this way; they either reach you or keep trying.
    """
    # duration_estimated rows are excluded deliberately. This fingerprint keys
    # on a zero-duration call paired with a sub-60-second one; carrier records
    # bill in rounded minutes and omit unanswered calls entirely, so including
    # them would both blur the durations and hide half the signature.
    rows = con.execute("""
        SELECT number, local_date, duration_s, ts_utc, geo
        FROM calls
        WHERE number IS NOT NULL
          AND direction IN ('INCOMING','MISSED','REJECTED','BLOCKED')
          AND (contact_name IS NULL OR contact_name = '')
          AND duration_estimated = 0
          AND dup_of_device = 0
        ORDER BY number, ts_utc
    """).fetchall()

    by_number = defaultdict(list)
    for r in rows:
        by_number[r["number"]].append(r)

    hits = []
    for number, calls in by_number.items():
        if len(calls) != 2:
            continue
        span_h = (calls[-1]["ts_utc"] - calls[0]["ts_utc"]) / 3_600_000
        durations = sorted(c["duration_s"] for c in calls)
        if span_h <= same_day_hours and durations[0] == 0 and 0 < durations[1] <= max_answer_s:
            hits.append({
                "number": number,
                "answered_s": durations[1],
                "date": calls[0]["local_date"],
                "geo": calls[0]["geo"] or "",
            })
    return sorted(hits, key=lambda h: h["date"])


def did_blocks(con, min_numbers: int = 2):
    """NPA-NXX ranges hit by multiple distinct numbers.

    Blocks where any number held a real conversation are dropped as legitimate
    businesses rather than dialer infrastructure.
    """
    rows = con.execute("""
        SELECT npa_nxx, number, call_count, max_duration_s, geo
        FROM numbers ORDER BY npa_nxx, number
    """).fetchall()

    blocks = defaultdict(list)
    for r in rows:
        blocks[r["npa_nxx"]].append(r)

    out = []
    for block, members in blocks.items():
        if len(members) < min_numbers:
            continue
        if any(m["max_duration_s"] >= LEGIT_CONVERSATION_S for m in members):
            continue  # someone had a real conversation -> legitimate business
        out.append({
            "block": block,
            "numbers": [m["number"] for m in members],
            "calls": sum(m["call_count"] for m in members),
            "geo": next((m["geo"] for m in members if m["geo"]), ""),
        })
    return sorted(out, key=lambda b: (-len(b["numbers"]), b["block"]))


def _carrier_concentration(con, members: set[str]):
    """Share of enriched member numbers held by the single largest carrier family.

    Returns (share, family_name, enriched_count). Share is 0.0 when enrichment
    has not run, so an un-enriched campaign is never credited for a signal that
    was never measured.
    """
    if not members:
        return 0.0, None, 0
    from ..enrich.nanpa import carrier_family

    placeholders = ",".join("?" * len(members))
    rows = con.execute(
        f"SELECT carrier_name FROM numbers "
        f"WHERE number IN ({placeholders}) AND carrier_name IS NOT NULL",
        tuple(sorted(members)),
    ).fetchall()
    if not rows:
        return 0.0, None, 0

    families = Counter(carrier_family(r["carrier_name"]) for r in rows)
    family, count = families.most_common(1)[0]
    return count / len(rows), family, len(rows)


def carrier_breakdown(con, campaign_id: int):
    """Member numbers grouped by carrier family, largest first."""
    from ..enrich.nanpa import carrier_family

    rows = con.execute("""
        SELECT n.number, n.carrier_name, n.carrier_ocn, n.line_type, n.call_count
        FROM numbers n JOIN campaign_numbers cn ON cn.number = n.number
        WHERE cn.campaign_id = ? AND n.carrier_name IS NOT NULL
    """, (campaign_id,)).fetchall()

    fam = defaultdict(lambda: {"numbers": 0, "calls": 0, "npas": set(),
                               "ocns": set(), "types": set()})
    for r in rows:
        f = fam[carrier_family(r["carrier_name"])]
        f["numbers"] += 1
        f["calls"] += r["call_count"]
        f["npas"].add(r["number"][:3])
        f["ocns"].add(r["carrier_ocn"])
        f["types"].add(r["line_type"])
    return sorted(
        ({"family": k, **v} for k, v in fam.items()),
        key=lambda d: (-d["numbers"], -d["calls"]),
    )


def build(con, label: str = "Rotating-DID campaign"):
    """Cluster, persist, and return the campaign with a confidence score."""
    fp = fingerprint_cluster(con)
    blocks = did_blocks(con)
    fp_numbers = {h["number"] for h in fp}
    block_numbers = {n for b in blocks for n in b["numbers"]}

    corroborated = fp_numbers & block_numbers
    members = fp_numbers | {n for b in blocks for n in b["numbers"]
                            if any(m in fp_numbers for m in b["numbers"])}

    # A block only joins the campaign if it shares at least one number with the
    # behavioral cluster. Unattributed blocks are still reported -- they are
    # leads, not members -- but must be labelled as such so the two are never
    # read as equivalent evidence.
    for b in blocks:
        b["corroborated"] = any(n in fp_numbers for n in b["numbers"])

    # Third signal: carrier concentration. Numbers scattered across many area
    # codes that all trace to one small carrier is far stronger evidence of a
    # single operation than DID-block adjacency -- geography can coincide, but
    # twenty states resolving to one wholesaler cannot. Weighted highest of the
    # three, and it only counts once enrichment has actually run.
    carrier_share, top_carrier, enriched_n = _carrier_concentration(con, members)

    size_term = min(len(fp) / 25.0, 1.0) * 0.40
    corrob_term = (len(corroborated) / len(fp) if fp else 0) * 0.25
    carrier_term = carrier_share * 0.35
    confidence = round(size_term + corrob_term + carrier_term, 3)

    # Auto-detected campaigns are derived data -- recomputed from scratch each
    # run. Drop prior automatic results so repeated analysis doesn't accumulate
    # duplicates, but never touch manually curated ones.
    con.execute("DELETE FROM campaign_numbers WHERE campaign_id IN "
                "(SELECT id FROM campaigns WHERE detection_method != 'manual')")
    con.execute("DELETE FROM campaigns WHERE detection_method != 'manual'")

    cur = con.execute(
        "INSERT INTO campaigns (label, detection_method, confidence, notes) VALUES (?,?,?,?)",
        (label, "fingerprint+did_block", confidence,
         f"{len(fp)} fingerprint numbers, {len(blocks)} DID blocks, "
         f"{len(corroborated)} corroborated by both signals"),
    )
    cid = cur.lastrowid
    for n in sorted(members):
        ev = "fingerprint+block" if n in corroborated else (
            "fingerprint" if n in fp_numbers else "block")
        con.execute(
            "INSERT OR IGNORE INTO campaign_numbers (campaign_id, number, evidence) VALUES (?,?,?)",
            (cid, n, ev))
    con.commit()

    calls = con.execute("""
        SELECT COUNT(*) FROM calls WHERE number IN
          (SELECT number FROM campaign_numbers WHERE campaign_id = ?)
          AND direction IN ('INCOMING','MISSED','REJECTED','BLOCKED')
    """, (cid,)).fetchone()[0]

    return {
        "campaign_id": cid,
        "confidence": confidence,
        "fingerprint_numbers": len(fp),
        "did_blocks": len(blocks),
        "corroborated": len(corroborated),
        "member_numbers": len(members),
        "total_calls": calls,
        "fingerprint": fp,
        "blocks": blocks,
        "area_codes": Counter(n[:3] for n in members).most_common(),
        "enriched_numbers": enriched_n,
        "top_carrier": top_carrier,
        "carrier_share": carrier_share,
        "carriers": carrier_breakdown(con, cid),
    }
