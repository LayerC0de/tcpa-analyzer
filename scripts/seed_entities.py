#!/usr/bin/env python3
"""Record resolved entities with the public source each fact came from.

This is a TEMPLATE. The entries below are fictional placeholders showing the
expected shape. Replace them with entities you have resolved yourself from
public records, and keep your working copy out of version control -- an entity
record is an assertion about a real company, and it belongs in your local
database rather than in a public repository.

WHY EVERY ENTRY CARRIES A SOURCE URL

Anything asserted in a filing needs a citation a judge can check independently.
An entity record without a verifiable source is worse than no record: it looks
authoritative while being unverifiable.

WHY `role` MATTERS MORE THAN THE NAME

  carrier  Holds the number block. NOT a defendant. Carriers lease numbers
           wholesale and are generally not liable for what a customer dials.
           They are the subpoena target and the traceback entry point, because
           they know which customer bought the block.
  caller   Placed the calls. Frequently an offshore shell with no assets.
  seller   Whoever the pitch was for. Domestic, collectable, and potentially
           vicariously liable for its lead generators. Usually the real
           defendant.

Recording a carrier with role='caller' because it appeared in enrichment output
would be a serious factual error. Resist it.

Run:  python scripts/seed_entities.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tcpa import db  # noqa: E402

ENTITIES = [
    {
        "legal_name": "EXAMPLE CARRIER LLC",
        "dba": None,
        "role": "carrier",
        "state_of_reg": "NV (organized); XX foreign registration T0000000",
        "registered_agent": "Example Registered Agent Inc.",
        "agent_address": "1 Example Street, Suite 100, Example City, XX 00000",
        "source_url": "https://example-state-registry.gov/entity/T0000000",
        "confidence": 0.9,
        "notes": (
            "PLACEHOLDER -- replace with an entity you resolved yourself. "
            "Carrier of record for a number block, identified from public NANPA "
            "block-assignment data. Being the block holder does NOT mean this "
            "company placed any call. Note that registered agents are "
            "per-state: for service in your state, obtain that state's "
            "registration rather than reusing another one."
        ),
    },
]


def main():
    con = db.connect()
    campaign = con.execute(
        "SELECT id FROM campaigns ORDER BY id DESC LIMIT 1").fetchone()
    cid = campaign["id"] if campaign else None

    for e in ENTITIES:
        existing = con.execute(
            "SELECT id FROM entities WHERE legal_name = ? AND role = ?",
            (e["legal_name"], e["role"])).fetchone()
        if existing:
            con.execute("""
                UPDATE entities SET campaign_id=?, state_of_reg=?, registered_agent=?,
                       agent_address=?, source_url=?, confidence=? WHERE id=?
            """, (cid, e["state_of_reg"], e["registered_agent"], e["agent_address"],
                  e["source_url"], e["confidence"], existing["id"]))
            print(f"updated  {e['legal_name']} ({e['role']})")
        else:
            con.execute("""
                INSERT INTO entities (campaign_id, legal_name, dba, role, state_of_reg,
                                      registered_agent, agent_address, source_url, confidence)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (cid, e["legal_name"], e["dba"], e["role"], e["state_of_reg"],
                  e["registered_agent"], e["agent_address"], e["source_url"],
                  e["confidence"]))
            print(f"recorded {e['legal_name']} ({e['role']})")
        print(f"         {e['notes']}\n")
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
