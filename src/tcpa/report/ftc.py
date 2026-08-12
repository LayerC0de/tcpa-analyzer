"""Generate regulator complaint text (FTC, FCC, and the Do Not Call registry).

This module deliberately does NOT submit anything. It produces text you read,
edit, and paste yourself. Three reasons, in order of importance:

  1. A complaint is a statement you are personally attesting to. Software must
     not attest on your behalf, and an automated filing you never read is a
     statement you cannot stand behind.
  2. Automated submission would violate those sites' terms of use.
  3. The agencies' value comes from aggregation across real complainants;
     machine-generated volume degrades the signal they rely on.

Where to file the output:
  reportfraud.ftc.gov          fraud, scams, unwanted calls generally
  donotcall.gov/report.html    Do Not Call registry violations specifically
  consumercomplaints.fcc.gov   FCC informal complaint (Form 1088)
"""
from __future__ import annotations

from datetime import datetime

from ..phone import display

WRAP = 78


def _fmt_calls(rows) -> str:
    lines = []
    for r in rows:
        dur = f"{r['duration_s'] // 60}m{r['duration_s'] % 60:02d}s" if r["duration_s"] else "no answer"
        lines.append(f"  {r['local_iso']}  {display(r['number'])}  {dur}")
    return "\n".join(lines)


def for_number(con, number: str, your_state: str = "[YOUR STATE]") -> str:
    """A complaint narrative for one calling number."""
    rows = con.execute("""
        SELECT local_iso, number, duration_s, direction FROM calls
        WHERE number = ? AND direction IN ('INCOMING','MISSED','REJECTED','BLOCKED')
          AND dup_of_device = 0
        ORDER BY ts_utc
    """, (number,)).fetchall()
    if not rows:
        return f"No calls on record for {display(number)}."

    meta = con.execute("""
        SELECT carrier_name, carrier_ocn, line_type, first_seen, last_seen, call_count
        FROM numbers WHERE number = ?
    """, (number,)).fetchone()

    comp = con.execute("""
        SELECT COUNT(*) n,
               SUM(CASE WHEN LOWER(COALESCE(call_type,'')) LIKE '%prerecorded%'
                   THEN 1 ELSE 0 END) pre
        FROM complaints WHERE caller_id_number = ?
    """, (number,)).fetchone()

    out = [
        f"COMPLAINT REGARDING UNWANTED CALLS FROM {display(number)}",
        "=" * WRAP, "",
        f"Calling number: {display(number)}",
        f"Total calls received: {len(rows)}",
        f"Date range: {rows[0]['local_iso'][:10]} to {rows[-1]['local_iso'][:10]}",
        f"My state: {your_state}",
        "",
        "CALL LOG",
        "-" * WRAP,
        _fmt_calls(rows),
        "",
    ]

    if meta and meta["carrier_name"]:
        out += [
            "CARRIER OF RECORD (from public NANPA block-assignment data)",
            "-" * WRAP,
            f"  Carrier: {meta['carrier_name']}",
            f"  OCN: {meta['carrier_ocn']}",
            f"  Line type: {meta['line_type']}",
            "  NOTE: this is the holder of the number block, which is not",
            "  necessarily the entity that placed these calls.",
            "",
        ]

    if comp and comp["n"]:
        out += [
            "RELATED PUBLIC COMPLAINTS (FCC open dataset, this exact number)",
            "-" * WRAP,
            f"  {comp['n']} complaints on file; {comp['pre'] or 0} report a prerecorded voice.",
            "",
        ]

    out += [
        "STATEMENT",
        "-" * WRAP,
        "I did not consent to these calls and have no business relationship",
        "with this caller. [EDIT THIS PARAGRAPH: describe what the caller said,",
        "whether you asked them to stop, and on what date. Specifics matter far",
        "more than volume -- delete anything you cannot personally attest to.]",
        "",
        "-" * WRAP,
        f"Prepared {datetime.now().strftime('%Y-%m-%d')} with tcpa-analyzer.",
        "Review every line before filing. You are attesting to this content.",
    ]
    return "\n".join(out)


def for_campaign(con, campaign_id: int, your_state: str = "[YOUR STATE]") -> str:
    """One narrative covering every number attributed to a campaign."""
    members = [r["number"] for r in con.execute(
        "SELECT number FROM campaign_numbers WHERE campaign_id=? ORDER BY number",
        (campaign_id,))]
    if not members:
        return f"Campaign {campaign_id} has no member numbers."

    marks = ",".join("?" * len(members))
    rows = con.execute(f"""
        SELECT local_iso, number, duration_s FROM calls
        WHERE number IN ({marks})
          AND direction IN ('INCOMING','MISSED','REJECTED','BLOCKED')
          AND dup_of_device = 0
        ORDER BY ts_utc
    """, tuple(members)).fetchall()

    camp = con.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    carriers = con.execute(f"""
        SELECT carrier_name, COUNT(*) c FROM numbers
        WHERE number IN ({marks}) AND carrier_name IS NOT NULL
        GROUP BY carrier_name ORDER BY c DESC LIMIT 5
    """, tuple(members)).fetchall()

    out = [
        "COMPLAINT REGARDING A COORDINATED UNWANTED CALLING CAMPAIGN",
        "=" * WRAP, "",
        f"This campaign used {len(members)} different calling numbers to place",
        f"{len(rows)} calls to my phone between {rows[0]['local_iso'][:10]} and",
        f"{rows[-1]['local_iso'][:10]}.",
        "",
        f"My state: {your_state}",
        "",
        "WHY THESE NUMBERS ARE ONE OPERATION",
        "-" * WRAP,
        f"  Detection: {camp['detection_method'] if camp else 'n/a'}",
        f"  Confidence: {camp['confidence']:.2f}" if camp else "",
        "  The numbers share a common calling pattern and were drawn from",
        "  overlapping carrier number blocks. Numbers spread across many area",
        "  codes resolving to a small number of carriers indicates one customer",
        "  buying numbers wholesale rather than unrelated callers.",
        "",
    ]
    if carriers:
        out.append("CARRIERS OF RECORD")
        out.append("-" * WRAP)
        for c in carriers:
            out.append(f"  {c['c']:>3} numbers  {c['carrier_name']}")
        out += ["  NOTE: carriers hold the number blocks. They are the entities",
                "  a traceback would route through, not necessarily the caller.", ""]

    out += ["CALLING NUMBERS USED", "-" * WRAP]
    out += ["  " + ", ".join(display(m) for m in members[i:i + 4])
            for i in range(0, len(members), 4)]
    out += ["", "FULL CALL LOG", "-" * WRAP, _fmt_calls(rows), "",
            "STATEMENT", "-" * WRAP,
            "I did not consent to any of these calls. [EDIT: describe the pitch,",
            "any callback number given, and every occasion you asked them to stop.]",
            "",
            "-" * WRAP,
            f"Prepared {datetime.now().strftime('%Y-%m-%d')} with tcpa-analyzer.",
            "Review every line before filing. You are attesting to this content."]
    return "\n".join(l for l in out if l is not None)
