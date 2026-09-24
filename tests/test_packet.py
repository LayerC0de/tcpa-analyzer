"""The intake packet must never overstate a case to the attorney reading it."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tcpa import db  # noqa: E402
from tcpa.report import packet  # noqa: E402

GAP = "No defendant (caller or seller) identified"


class TestDefendantGap(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.dir.name) / "tcpa.db")
        c = self.con
        c.execute("""INSERT INTO calls (source, source_row_id, number, ts_utc, local_iso,
                     local_date, local_hour, direction)
                     VALUES ('test','1','2025550100',0,'2026-09-01 12:00:00',
                             '2026-09-01',12,'MISSED')""")
        db.rebuild_numbers(c)
        cid = c.execute("INSERT INTO campaigns (label, detection_method) "
                        "VALUES ('t','fingerprint')").lastrowid
        c.execute("INSERT INTO campaign_numbers (campaign_id, number) VALUES (?,?)",
                  (cid, "2025550100"))
        c.commit()
        self.cid = cid

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _entity(self, role):
        self.con.execute("INSERT INTO entities (campaign_id, legal_name, role) "
                         "VALUES (?,?,?)", (self.cid, "EXAMPLE LLC", role))
        self.con.commit()

    def test_carrier_entity_is_not_a_defendant(self):
        self._entity("carrier")
        text = packet.build(self.con, campaign_id=self.cid)
        self.assertIn(GAP, text)
        self.assertIn("NOT a defendant", text)

    def test_seller_entity_closes_the_gap(self):
        self._entity("seller")
        self.assertNotIn(GAP, packet.build(self.con, campaign_id=self.cid))


if __name__ == "__main__":
    unittest.main()
