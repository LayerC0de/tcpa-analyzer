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
            "800-555-0100   # Example Bank -- auto loan\n"
            "+1 (716) 555-1234\n"
            "12345  # short code, not NANP\n"
        )
        self.assertEqual(known, {"8005550100": "Example Bank -- auto loan",
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
        _call(con, 1, "8005550100")
        _call(con, 2, "8005550100", "MISSED", 0)
        _call(con, 3, "7165550000")
        con.commit()
        con.close()
        self.assertEqual(self._rollup(), {"8005550100", "7165550000"})

        (Path(self.dir.name) / db.KNOWN_NUMBERS_FILE).write_text(
            "(800) 555-0100  # bank\n", encoding="utf-8")
        self.assertEqual(self._rollup(), {"7165550000"})

    def test_removing_entry_restores_number(self):
        known = Path(self.dir.name) / db.KNOWN_NUMBERS_FILE
        known.write_text("8005550100\n", encoding="utf-8")
        con = db.connect(self.path)
        _call(con, 1, "8005550100")
        con.commit()
        con.close()
        self.assertEqual(self._rollup(), set())

        known.write_text("", encoding="utf-8")
        self.assertEqual(self._rollup(), {"8005550100"})


if __name__ == "__main__":
    unittest.main()
