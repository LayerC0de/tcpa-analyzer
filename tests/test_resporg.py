"""Toll-free RespOrg attribution. No test here touches the network: `fetch`
is replaced with canned responses shaped like resporgs.com's history API."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tcpa import db  # noqa: E402
from tcpa.enrich import resporg  # noqa: E402

HISTORY = {
    "event_count": 2, "phone": "8005550199", "source": "somos",
    "events": [  # deliberately out of order: the parser must sort by ts
        {"date": "2022-01-14", "ts": "2022-01-14T23:01:42.446", "org": "VZM01",
         "status": "Working",
         "holder": {"code": "VZM01", "group": "Verizon", "name": "Verizon Business"}},
        {"date": "2017-08-07", "ts": "2017-08-07T16:29:28.355", "org": "IVN04",
         "status": "Working",
         "holder": {"code": "IVN04", "group": "Verizon", "name": "XO Communications"}},
    ],
}
EMPTY = {"event_count": 0, "events": [], "phone": "8330000001", "source": "somos"}


class TestParsing(unittest.TestCase):
    def test_number_must_be_toll_free(self):
        self.assertEqual(resporg.parse_number("1-800-555-0199"), "8005550199")
        with self.assertRaises(ValueError):
            resporg.parse_number("202-555-0100")   # geographic
        with self.assertRaises(ValueError):
            resporg.parse_number("12345")

    def test_resporg_id_format(self):
        self.assertEqual(resporg.parse_id(" vzm01 "), "VZM01")
        for bad in ("", "VZM", "VZM0A", "VZM011"):
            with self.assertRaises(ValueError):
                resporg.parse_id(bad)

    def test_current_holder_is_latest_event(self):
        p = resporg.parse_history(HISTORY)
        self.assertEqual(p["resporg_id"], "VZM01")
        self.assertEqual(p["resporg_name"], "Verizon Business")
        self.assertEqual(p["resporg_group"], "Verizon")
        self.assertEqual(p["status"], "WORKING")
        self.assertEqual(p["status_since"], "2022-01-14")

    def test_names_are_whitespace_normalized(self):
        data = {"events": [{"ts": "2026-08-19T00:00:00", "status": "Working",
                            "holder": {"code": "PJP03", "group": " ATLC ",
                                       "name": "Independent\xa0Resporg"}}]}
        p = resporg.parse_history(data)
        self.assertEqual(p["resporg_name"], "Independent Resporg")
        self.assertEqual(p["resporg_group"], "ATLC")

    def test_no_events_is_not_found(self):
        p = resporg.parse_history(EMPTY)
        self.assertIsNone(p["resporg_id"])
        self.assertEqual(p["status"], "NOT_FOUND")


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.dir.name) / "tcpa.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _lookup(self, numbers, responses):
        with mock.patch.object(resporg, "fetch", side_effect=responses):
            return resporg.lookup(self.con, numbers, sleep=0, verbose=False)

    def test_auto_lookup_logged_and_rerun_same_day_replaces(self):
        stats = self._lookup(["8005550199", "8330000001"], [HISTORY, EMPTY])
        self.assertEqual(stats, {"resolved": 1, "not_found": 1, "failed": 0})
        self._lookup(["8005550199"], [HISTORY])
        rows = resporg.history(self.con, "8005550199")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["method"], "auto")
        self.assertIn("VZM01", rows[0]["raw_json"])

    def test_failure_is_counted_not_stored(self):
        stats = self._lookup(["8005550199"], [ValueError("resporgs.com: invalid phone")])
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(resporg.history(self.con, "8005550199"), [])

    def test_recently_checked_numbers_are_not_due(self):
        self._lookup(["8005550199"], [HISTORY])
        self.assertEqual(resporg.due(self.con, ["8005550199", "8330000001"]),
                         ["8330000001"])

    def test_manual_entry_requires_source_and_wins_same_day(self):
        with self.assertRaises(ValueError):
            resporg.record_manual(self.con, "8005550199", "ABC01", source="  ")
        self._lookup(["8005550199"], [HISTORY])
        resporg.record_manual(self.con, "8005550199", "abc01", "somos.com lookup",
                              name="Example Telecom")
        rows = resporg.history(self.con, "8005550199")
        self.assertEqual([r["method"] for r in rows], ["manual", "auto"])
        self.assertEqual(rows[0]["resporg_id"], "ABC01")

    def test_manual_entry_accepts_name_without_id(self):
        # somos.com's public form shows the company, not the RespOrg ID.
        with self.assertRaises(ValueError):
            resporg.record_manual(self.con, "8005550199", None, "somos.com")
        resporg.record_manual(self.con, "8005550199", None, "somos.com",
                              name="Example\xa0Telecom")
        row = resporg.history(self.con, "8005550199")[0]
        self.assertIsNone(row["resporg_id"])
        self.assertEqual(row["resporg_name"], "Example Telecom")

    def test_worklist_includes_fcc_callbacks_and_survives_rollup_rebuild(self):
        self.con.execute("INSERT INTO complaints (fcc_id, advertiser_phone) "
                         "VALUES ('x1', '8885550123')")
        self.con.execute("INSERT INTO complaints (fcc_id, advertiser_phone) "
                         "VALUES ('x2', '2025550100')")  # not toll-free: skipped
        self.con.commit()
        self._lookup(["8885550123"], [HISTORY])
        db.rebuild_numbers(self.con)   # prunes `numbers`; lookups must remain
        rows = resporg.worklist(self.con)
        self.assertEqual([r["number"] for r in rows], ["8885550123"])
        self.assertEqual(rows[0]["fcc_callbacks"], 1)
        self.assertEqual(rows[0]["resporg_id"], "VZM01")


if __name__ == "__main__":
    unittest.main()
