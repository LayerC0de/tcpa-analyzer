"""Who counts as a known text sender. A single reply may have been STOP."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tcpa import db  # noqa: E402
from tcpa.analyze import texts as tx  # noqa: E402


class TestKnownSenders(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.dir.name) / "tcpa.db")
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _text(self, number, direction, ts):
        self.n += 1
        self.con.execute("""INSERT INTO texts (source, source_row_id, number, number_raw,
                 direction, kind, ts_utc, local_date)
                 VALUES ('test', ?, ?, ?, ?, 'TEXT', ?, '2026-09-01')""",
                         (str(self.n), number, number, direction, ts))

    def test_stop_reply_keeps_sender_and_counts_later_texts(self):
        self._text("2025550101", "INCOMING", 1)
        self._text("2025550101", "OUTGOING", 2)      # e.g. STOP
        self._text("2025550101", "INCOMING", 3)
        self._text("2025550101", "INCOMING", 4)
        s = tx.summarize(self.con)
        self.assertIn("2025550101", s["unknown"])
        r = tx.rank_unknown(s)[0]
        self.assertEqual((r["replies"], r["after_reply"]), (1, 2))

    def test_owner_first_contact_is_a_relationship(self):
        self._text("2025550102", "OUTGOING", 1)
        self._text("2025550102", "INCOMING", 2)
        self.assertNotIn("2025550102", tx.summarize(self.con)["unknown"])

    def test_conversation_is_a_relationship(self):
        self._text("2025550103", "INCOMING", 1)
        for ts in (2, 3, 4):
            self._text("2025550103", "OUTGOING", ts)
        self.assertNotIn("2025550103", tx.summarize(self.con)["unknown"])


if __name__ == "__main__":
    unittest.main()
