#!/usr/bin/env python3
"""Quantify what the carrier record omits versus the device call log.

Run over any period where both sources overlap. The gap this measures is the
reason device logs are the primary evidence and carrier statements are only a
way to reach further back in time.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tcpa import db  # noqa: E402

INBOUND = "('INCOMING','MISSED','REJECTED','BLOCKED')"


def main():
    con = db.connect()
    span = con.execute(
        "SELECT MIN(local_date), MAX(local_date) FROM calls WHERE source='att'").fetchone()
    if not span or not span[0]:
        sys.exit("no AT&T rows loaded yet")
    lo, hi = span
    print(f"overlap window: {lo} .. {hi}\n")

    def count(sql):
        return con.execute(sql, (lo, hi)).fetchone()[0]

    dev = count(f"""SELECT COUNT(*) FROM calls WHERE source='android'
                    AND local_date BETWEEN ? AND ? AND direction IN {INBOUND}""")
    att = count("""SELECT COUNT(*) FROM calls WHERE source='att'
                   AND local_date BETWEEN ? AND ? AND direction='INCOMING'""")
    zero = count(f"""SELECT COUNT(*) FROM calls WHERE source='android'
                     AND local_date BETWEEN ? AND ? AND direction IN {INBOUND}
                     AND duration_s = 0""")
    short = count(f"""SELECT COUNT(*) FROM calls WHERE source='android'
                      AND local_date BETWEEN ? AND ? AND direction IN {INBOUND}
                      AND duration_s > 0 AND duration_s < 60""")

    print(f"  device inbound events : {dev}")
    print(f"  AT&T inbound events   : {att}")
    gap = dev - att
    pct = (gap / dev * 100) if dev else 0
    print(f"  MISSING from AT&T     : {gap}  ({pct:.0f}% of device events)\n")
    print("  breakdown of device events AT&T cannot represent:")
    print(f"    never connected (0s)          : {zero}")
    print(f"    1-59s (billed as a full min)  : {short}")

    print("\n  worst case for TCPA work: the campaign fingerprint needs a")
    print("  zero-duration call paired with a short one. AT&T shows neither.")
    con.close()


if __name__ == "__main__":
    main()
