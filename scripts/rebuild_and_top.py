#!/usr/bin/env python3
"""Rebuild the number rollup and show the top unknown inbound callers."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tcpa import db          # noqa: E402
from tcpa.phone import display  # noqa: E402


def main():
    con = db.connect()
    n = db.rebuild_numbers(con)
    total_known = con.execute(
        f"SELECT COUNT(DISTINCT number) FROM ({db.KNOWN_CONTACT_SQL})").fetchone()[0]
    print(f"known contacts excluded : {total_known}")
    print(f"unknown inbound numbers : {n}\n")

    print("top unknown inbound callers:")
    print(f"  {'number':<16}{'calls':>6}{'ans':>5}{'longest':>9}  {'first':<12}{'last':<12} geo")
    for r in con.execute("""SELECT number, call_count, answered_count, max_duration_s,
                                   first_seen, last_seen, geo
                            FROM numbers ORDER BY call_count DESC LIMIT 20"""):
        d = r["max_duration_s"]
        print(f"  {display(r['number']):<16}{r['call_count']:>6}{r['answered_count']:>5}"
              f"{d//60:>6}m{d%60:02d}  {r['first_seen']:<12}{r['last_seen']:<12} {r['geo'] or ''}")

    dist = con.execute("""SELECT call_count, COUNT(*) c FROM numbers
                          GROUP BY call_count ORDER BY call_count""").fetchall()
    ones = next((r["c"] for r in dist if r["call_count"] == 1), 0)
    multi = sum(r["c"] for r in dist if r["call_count"] >= 2)
    print(f"\n  single-call numbers : {ones}")
    print(f"  2+ call numbers     : {multi}   <- 227(c)(5) eligible")
    con.close()


if __name__ == "__main__":
    main()
