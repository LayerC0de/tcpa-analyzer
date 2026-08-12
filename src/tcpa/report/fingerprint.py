"""Shareable campaign fingerprints -- how strangers find each other's defendant.

A TCPA class action needs many people hit by the SAME operation. The obstacle is
that finding each other normally means publishing call records, which are deeply
personal: who you bank with, which clinic called, when you were awake.

A fingerprint solves that by describing the CALLER and nothing about the
recipient. Everything here is the spam operation's own infrastructure -- number
blocks it leased, carriers it bought from, callback numbers it advertised, and
the shape of its dialing behaviour. None of it identifies who was called.

Deliberately excluded, and why:
  - your phone number, name, carrier, or location   -> identifies you
  - exact call timestamps                           -> a timeline of your life,
                                                       and re-identifying against
                                                       any other record you appear in
  - contact names, texts, durations                 -> not needed to match a campaign

What remains still matches campaigns reliably, because operations are identified
by the infrastructure they reuse across victims, not by whom they happened to
dial. Two people hit by one operation will share number blocks and carriers even
though they share no personal data at all.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone

SCHEMA_VERSION = 1


def build(con, campaign_id: int) -> dict:
    members = [r["number"] for r in con.execute(
        "SELECT number FROM campaign_numbers WHERE campaign_id=? ORDER BY number",
        (campaign_id,))]
    if not members:
        raise ValueError(f"campaign {campaign_id} has no members")
    marks = ",".join("?" * len(members))

    camp = con.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    blocks = sorted({m[:6] for m in members})
    npas = sorted({m[:3] for m in members})

    carriers = sorted({
        (r["carrier_name"], r["carrier_ocn"])
        for r in con.execute(
            f"SELECT carrier_name, carrier_ocn FROM numbers "
            f"WHERE number IN ({marks}) AND carrier_name IS NOT NULL", tuple(members))
    })

    # Hour-of-day shape, normalised to a 0-9 scale so it describes the dialer's
    # working pattern without revealing when any individual call landed.
    hours = Counter(r["local_hour"] for r in con.execute(
        f"SELECT local_hour FROM calls WHERE number IN ({marks}) "
        f"AND direction IN ('INCOMING','MISSED','REJECTED','BLOCKED') "
        f"AND dup_of_device = 0", tuple(members)))
    peak = max(hours.values()) if hours else 1
    hour_shape = "".join(str(round(9 * hours.get(h, 0) / peak)) for h in range(24))

    callbacks = sorted({
        r["advertiser_phone"] for r in con.execute(
            "SELECT DISTINCT advertiser_phone FROM complaints "
            "WHERE advertiser_phone IS NOT NULL AND npa_nxx IN "
            f"(SELECT DISTINCT substr(number,1,6) FROM numbers WHERE number IN ({marks}))",
            tuple(members))
        if r["advertiser_phone"]
    })

    # Coarse month buckets only: enough to tell an active campaign from a dormant
    # one, not enough to place anyone at a moment in time.
    months = sorted({r["local_date"][:7] for r in con.execute(
        f"SELECT local_date FROM calls WHERE number IN ({marks}) "
        f"AND direction IN ('INCOMING','MISSED','REJECTED','BLOCKED') "
        f"AND dup_of_device = 0", tuple(members))})

    fp = {
        "schema": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "detection_method": camp["detection_method"] if camp else None,
        "confidence": camp["confidence"] if camp else None,
        "number_count": len(members),
        "did_blocks": blocks,
        "area_codes": npas,
        "carriers": [{"name": n, "ocn": o} for n, o in carriers],
        "callback_numbers": callbacks,
        "hour_shape": hour_shape,
        "active_months": months,
        "call_volume_bucket": _bucket(sum(
            r[0] for r in con.execute(
                f"SELECT call_count FROM numbers WHERE number IN ({marks})", tuple(members)))),
    }
    fp["id"] = hashlib.sha256(
        json.dumps([blocks, sorted(o for _, o in carriers), callbacks],
                   sort_keys=True).encode()).hexdigest()[:16]
    return fp


def _bucket(n: int) -> str:
    for hi, label in ((10, "1-10"), (50, "11-50"), (100, "51-100"), (500, "101-500")):
        if n <= hi:
            return label
    return "500+"


def match(a: dict, b: dict) -> dict:
    """Score how strongly two fingerprints describe the same operation."""
    def jac(x, y):
        sx, sy = set(x), set(y)
        return len(sx & sy) / len(sx | sy) if (sx | sy) else 0.0

    blocks = jac(a.get("did_blocks", []), b.get("did_blocks", []))
    ocns = jac([c["ocn"] for c in a.get("carriers", [])],
               [c["ocn"] for c in b.get("carriers", [])])
    cbs = jac(a.get("callback_numbers", []), b.get("callback_numbers", []))

    # A shared callback number is the single strongest signal: an operation must
    # be able to RECEIVE on it, so it cannot be spoofed or coincidental.
    score = round(0.30 * blocks + 0.25 * ocns + 0.45 * cbs, 3)
    shared_cb = sorted(set(a.get("callback_numbers", [])) & set(b.get("callback_numbers", [])))
    return {
        "score": score,
        "block_overlap": round(blocks, 3),
        "carrier_overlap": round(ocns, 3),
        "callback_overlap": round(cbs, 3),
        "shared_callbacks": shared_cb,
        "shared_blocks": sorted(set(a.get("did_blocks", [])) & set(b.get("did_blocks", []))),
        "verdict": ("same operation" if score >= 0.5 or shared_cb
                    else "possible overlap" if score >= 0.2 else "unrelated"),
    }
