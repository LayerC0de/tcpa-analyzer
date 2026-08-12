"""The privacy guarantees are the load-bearing claim of this project.

If normalization breaks, counts are wrong. If the contribution allowlist breaks,
someone publishes their own phone records to a public repository. These tests
exist for the second case.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tcpa.phone import normalize, npa_nxx, is_toll_free, display  # noqa: E402
from tcpa.report.contribute import audit  # noqa: E402
from tcpa.report.fingerprint import match  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_equivalent_formats_collapse(self):
        """The bug that motivated this module: one line, four spellings."""
        for raw in ("+18602994748", "8602994748", "1-860-299-4748",
                    "+1 (860) 299-4748"):
            self.assertEqual(normalize(raw), "8602994748", raw)

    def test_rejects_non_nanp(self):
        for raw in (None, "", "45987", "911", "+442071234567", "0123456789"):
            self.assertIsNone(normalize(raw), raw)

    def test_rejects_invalid_npa_nxx(self):
        self.assertIsNone(normalize("0165551234"))
        self.assertIsNone(normalize("7160551234"))

    def test_helpers(self):
        self.assertEqual(npa_nxx("7432863156"), "743286")
        self.assertTrue(is_toll_free("8005551234"))
        self.assertFalse(is_toll_free("7165551234"))
        self.assertEqual(display("7165551234"), "(716) 555-1234")


class TestContributionAudit(unittest.TestCase):
    def _doc(self, **over):
        doc = {
            "schema": 1, "generated_utc": "2026-01-01", "tool_version": "0.1.0",
            "contributor_note": None,
            "fingerprint": {"id": "abc123", "did_blocks": ["743286"]},
            "numbers": [{
                "number": "7432863156", "npa_nxx": "743286",
                "carrier_name": "EXAMPLE", "carrier_ocn": "321J",
                "line_type": "VOIP_WHOLESALE",
                "first_month": "2026-03", "last_month": "2026-04",
                "observations": "3-5",
            }],
        }
        doc.update(over)
        return doc

    def test_clean_document_passes(self):
        self.assertEqual(audit(self._doc()), [])

    def test_rejects_recipient_number(self):
        self.assertTrue(audit(self._doc(own_number="5551234567")))

    def test_rejects_unknown_top_level_field(self):
        self.assertTrue(audit(self._doc(my_location="Buffalo NY")))

    def test_rejects_exact_timestamp_in_number(self):
        doc = self._doc()
        doc["numbers"][0]["local_iso"] = "2026-03-04 10:11:12"
        self.assertTrue(audit(doc))

    def test_rejects_full_date_instead_of_month(self):
        doc = self._doc()
        doc["numbers"][0]["first_month"] = "2026-03-04"
        self.assertTrue(audit(doc))

    def test_rejects_digits_in_note(self):
        """A free-text note is where a phone number would leak."""
        self.assertTrue(audit(self._doc(contributor_note="called me at 716-430-4600")))
        self.assertEqual(audit(self._doc(contributor_note="auto warranty pitch")), [])

    def test_rejects_recipient_data_in_fingerprint(self):
        self.assertTrue(audit(self._doc(fingerprint={"id": "x", "own_number": "5551234567"})))


class TestFingerprintMatch(unittest.TestCase):
    def test_shared_callback_is_conclusive(self):
        a = {"did_blocks": ["111222"], "carriers": [{"ocn": "1A"}],
             "callback_numbers": ["8005550147"]}
        b = {"did_blocks": ["999888"], "carriers": [{"ocn": "9Z"}],
             "callback_numbers": ["8005550147"]}
        self.assertEqual(match(a, b)["verdict"], "same operation")

    def test_disjoint_is_unrelated(self):
        a = {"did_blocks": ["111222"], "carriers": [{"ocn": "1A"}], "callback_numbers": []}
        b = {"did_blocks": ["999888"], "carriers": [{"ocn": "9Z"}], "callback_numbers": []}
        self.assertEqual(match(a, b)["verdict"], "unrelated")

    def test_empty_inputs_do_not_crash(self):
        self.assertEqual(match({}, {})["score"], 0.0)


if __name__ == "__main__":
    unittest.main()
