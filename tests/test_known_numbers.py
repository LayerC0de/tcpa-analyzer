"""A number the owner has identified as legitimate must drop out of every
unknown-caller count, the same way an address-book contact does."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tcpa import db  # noqa: E402


def _call(con, row_id, number, direction="INCOMING", duration=30):
    con.execute("""
        INSERT INTO calls (source, source_row_id, number_raw, number, ts_utc,
                           local_iso, local_date, local_hour, duration_s, direction)
        VALUES ('test', ?, ?, ?, 0, '2026-09-01 12:00:00', '2026-09-01', 12, ?, ?)
    """, (str(row_id), number, number, duration, direction))


class TestParse(unittest.TestCase):
    def test_formats_and_notes(self):
        known, invalid = db.parse_known_numbers(
            "# header comment\n"
            "\n"
            "202-555-0100   # Example Bank -- auto loan\n"
            "+1 (716) 555-1234\n"
            "12345  # short code, not NANP\n"
        )
        self.assertEqual(known, {"2025550100": "Example Bank -- auto loan",
                                 "7165551234": ""})
        self.assertEqual(invalid, ["12345  # short code, not NANP"])


class TestExclusion(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "tcpa.db"

    def tearDown(self):
        self.dir.cleanup()

    def _rollup(self):
        con = db.connect(self.path)
        db.rebuild_numbers(con)
        nums = {r[0] for r in con.execute("SELECT number FROM numbers")}
        con.close()
        return nums

    def test_listed_number_leaves_rollup(self):
        con = db.connect(self.path)
        _call(con, 1, "2025550100")
        _call(con, 2, "2025550100", "MISSED", 0)
        _call(con, 3, "7165550000")
        con.commit()
        con.close()
        self.assertEqual(self._rollup(), {"2025550100", "7165550000"})

        (Path(self.dir.name) / db.KNOWN_NUMBERS_FILE).write_text(
            "(202) 555-0100  # bank\n", encoding="utf-8")
        self.assertEqual(self._rollup(), {"7165550000"})

    def test_removing_entry_restores_number(self):
        known = Path(self.dir.name) / db.KNOWN_NUMBERS_FILE
        known.write_text("2025550100\n", encoding="utf-8")
        con = db.connect(self.path)
        _call(con, 1, "2025550100")
        con.commit()
        con.close()
        self.assertEqual(self._rollup(), set())

        known.write_text("", encoding="utf-8")
        self.assertEqual(self._rollup(), {"2025550100"})


class TestCallbacks(unittest.TestCase):
    """Calling a number back to identify it must not hide it from analysis."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.dir.name) / "tcpa.db")

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _call(self, row_id, number, direction, ts):
        self.con.execute("""
            INSERT INTO calls (source, source_row_id, number, ts_utc, local_iso,
                               local_date, local_hour, duration_s, direction)
            VALUES ('test', ?, ?, ?, '2026-09-01 12:00:00', '2026-09-01', 12, 10, ?)
        """, (str(row_id), number, ts, direction))

    def test_callback_keeps_number_and_is_counted(self):
        self._call(1, "2025550101", "MISSED", 1000)
        self._call(2, "2025550101", "OUTGOING", 2000)    # owner calls back
        db.rebuild_numbers(self.con)
        row = self.con.execute("SELECT owner_calls FROM numbers "
                               "WHERE number='2025550101'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["owner_calls"], 1)

    def test_owner_calling_first_is_a_relationship(self):
        self._call(1, "2025550102", "OUTGOING", 1000)    # owner called first
        self._call(2, "2025550102", "INCOMING", 2000)
        db.rebuild_numbers(self.con)
        self.assertIsNone(self.con.execute(
            "SELECT 1 FROM numbers WHERE number='2025550102'").fetchone())

    def test_packet_discloses_callbacks(self):
        from tcpa.report import packet
        self._call(1, "2025550101", "MISSED", 1000)
        self._call(2, "2025550101", "OUTGOING", 2000)
        db.rebuild_numbers(self.con)
        text = packet.build(self.con, number="2025550101")
        self.assertIn("Owner called back 1 of these number(s)", text)
        self.assertIn("Disclose it", text)


if __name__ == "__main__":
    unittest.main()
