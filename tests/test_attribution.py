from pathlib import Path
import csv
import tempfile
import unittest

from jawikiimg.attribution import write_report
from jawikiimg.db import Database


class AttributionReportTests(unittest.TestCase):
    def test_review_csv_contains_license_and_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = Database(root / "test.sqlite3")
            db.add_images(["Needs-review.jpg"])
            with db.transaction() as conn:
                conn.execute(
                    """UPDATE images SET classification='REVIEW',
                    classification_reason='unrecognized Permission text requires review',
                    license_short_name='CC BY 4.0',
                    license_url='https://creativecommons.org/licenses/by/4.0/',
                    artist='Example Artist',description_url='https://commons.wikimedia.org/example',
                    permission='See below',restrictions_text='Trademark'"""
                )
            write_report(db, root / "report", "20260801")
            with (root / "report" / "review.csv").open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["license_short_name"], "CC BY 4.0")
            self.assertEqual(rows[0]["license_url"], "https://creativecommons.org/licenses/by/4.0/")
            self.assertEqual(rows[0]["artist"], "Example Artist")
            self.assertEqual(rows[0]["permission"], "See below")
            self.assertEqual(rows[0]["restrictions_text"], "Trademark")


if __name__ == "__main__":
    unittest.main()
