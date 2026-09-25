"""Revocations decide whether a call is worth $500 or up to $1,500, so these
tests pin down the ways that number could be overstated."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tcpa import db, revoke  # noqa: E402
from tcpa.report import packet  # noqa: E402

A, B = "2025550101", "2025550102"


class TestRevoke(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.dir.name) / "tcpa.db")
        calls = [  # (number, local_iso, ts_utc, duration, direction)
            (A, "2026-03-01 10:00:00", 1000, 40, "INCOMING"),
            (A, "2026-03-01 15:00:00", 2000, 20, "INCOMING"),
            (A, "2026-03-02 10:00:00", 3000, 0, "MISSED"),
            (A, "2026-03-03 10:00:00", 4000, 0, "MISSED"),
            (B, "2026-03-05 10:00:00", 5000, 0, "MISSED"),   # other number, later
        ]
        for i, (num, iso, ts, dur, d) in enumerate(calls):
            self.con.execute("""INSERT INTO calls (source, source_row_id, number, ts_utc,
                     local_iso, local_date, local_hour, duration_s, direction)
                     VALUES ('test',?,?,?,?,?,10,?,?)""",
                             (str(i), num, ts, iso, iso[:10], dur, d))
        db.rebuild_numbers(self.con)
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def test_ambiguous_date_asks_for_a_time(self):
        with self.assertRaises(ValueError) as cm:
            revoke.record(self.con, A, "2026-03-01", "recollection")
        self.assertIn("10:00", str(cm.exception))
        res = revoke.record(self.con, A, "2026-03-01 15:02", "recollection",
                            said="stop calling")
        self.assertEqual(res["local_iso"], "2026-03-01 15:00:00")
        self.assertEqual(res["calls_after"], 2)

    def test_verbal_request_needs_an_answered_call(self):
        with self.assertRaises(ValueError):
            revoke.record(self.con, A, "2026-03-02", "recollection")   # missed call

    def test_recording_basis_needs_a_real_file(self):
        with self.assertRaises(ValueError):
            revoke.record(self.con, A, "2026-03-01 10:00", "recording")
        with self.assertRaises(ValueError):
            revoke.record(self.con, A, "2026-03-01 10:00", "recording",
                          evidence=str(Path(self.dir.name) / "missing.m4a"))
        rec = Path(self.dir.name) / "call.m4a"
        rec.write_bytes(b"x")
        revoke.record(self.con, A, "2026-03-01 10:00", "recording", evidence=str(rec))

    def test_duplicate_is_rejected(self):
        revoke.record(self.con, A, "2026-03-01 10:00", "recollection")
        with self.assertRaises(ValueError):
            revoke.record(self.con, A, "2026-03-01 10:01", "recollection")

    def test_revocation_never_spreads_to_other_numbers(self):
        cid = self.con.execute("INSERT INTO campaigns (label, detection_method) "
                               "VALUES ('t','fingerprint')").lastrowid
        for n in (A, B):
            self.con.execute("INSERT INTO campaign_numbers VALUES (?,?,NULL)", (cid, n))
        self.con.commit()
        revoke.record(self.con, A, "2026-03-01 10:00", "recollection")
        text = packet.build(self.con, campaign_id=cid)
        # A's three later calls count; B's call, though later in time, does not.
        self.assertIn("Calls after a documented revocation (same number): 3", text)
        self.assertIn("2 x $500", text)
        self.assertIn("Revocations rest on recollection only", text)


if __name__ == "__main__":
    unittest.main()
