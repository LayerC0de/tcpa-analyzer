"""The intake packet must never overstate a case to the attorney reading it."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tcpa import db  # noqa: E402
from tcpa.report import leads, packet  # noqa: E402

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


class TestLeads(unittest.TestCase):
    """Leads are reported beside the campaign, never folded into it."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.dir.name) / "tcpa.db")
        for i, (num, dur) in enumerate([("4165550101", 8), ("6045550102", 0),
                                        ("8005550199", 5), ("8005550199", 0)]):
            self.con.execute("""INSERT INTO calls (source, source_row_id, number, ts_utc,
                     local_iso, local_date, local_hour, duration_s, direction)
                     VALUES ('test',?,?,?,'2026-09-01 12:00:00','2026-09-01',12,?,?)""",
                             (str(i), num, i, dur, "INCOMING" if dur else "MISSED"))
        db.rebuild_numbers(self.con)
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _campaign(self, *numbers):
        cid = self.con.execute("INSERT INTO campaigns (label, detection_method) "
                               "VALUES ('t','fingerprint')").lastrowid
        for n in numbers:
            self.con.execute("INSERT INTO campaign_numbers VALUES (?,?,NULL)", (cid, n))
        self.con.commit()
        return "\n".join(leads.section(self.con))

    def test_canadian_and_toll_free_reported(self):
        from tcpa.enrich import resporg
        resporg.record_manual(self.con, "8005550199", None, "somos.com",
                              name="Example Telecom")
        text = self._campaign()
        self.assertIn("2 calls from 2 numbers across 2 Canadian area codes", text)
        self.assertIn("Example Telecom", text)
        self.assertIn("confirmed on somos.com", text)

    def test_somos_basis_never_overstates(self):
        row = {"method": "manual", "resporg_name": "Example Labs LLC"}
        self.assertEqual(leads._basis(row, "EXAMPLE LABS"), "confirmed on somos.com")
        row = {"method": "manual", "resporg_name": "Other Media Inc"}
        self.assertEqual(leads._basis(row, "Example Labs LLC"),
                         "somos.com now: Other Media Inc")
        row = {"method": "manual", "resporg_name": None}
        self.assertEqual(leads._basis(row, "Example Labs LLC"),
                         "somos.com now: available")

    def test_campaign_members_are_not_double_counted(self):
        text = self._campaign("4165550101")
        self.assertIn("1 calls from 1 numbers across 1 Canadian area codes", text)


class TestSingleNumberPacket(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.dir.name) / "tcpa.db")
        self.con.execute("""INSERT INTO calls (source, source_row_id, number, ts_utc,
                 local_iso, local_date, local_hour, duration_s, direction)
                 VALUES ('test','1','8005550199',0,'2026-09-01 12:00:00',
                         '2026-09-01',12,7,'INCOMING')""")
        db.rebuild_numbers(self.con)
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def test_cli_normalizes_the_number_argument(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import cli
        self.assertEqual(cli._number_arg("1 (800) 555-0199"), "8005550199")
        with self.assertRaises(SystemExit):
            cli._number_arg("12345")

    def test_toll_free_number_shows_resporg_not_carrier_gap(self):
        from tcpa.enrich import resporg
        resporg.record_manual(self.con, "8005550199", None, "somos.com",
                              name="Example Telecom")
        text = packet.build(self.con, number="8005550199")
        self.assertIn("Toll-free RespOrg", text)
        self.assertIn("Example Telecom", text)
        self.assertNotIn("Carrier data not resolved", text)


if __name__ == "__main__":
    unittest.main()
