from pathlib import Path
import json
import tempfile
import unittest

from jawikiimg.api import classify_pending
from jawikiimg.control import Control
from jawikiimg.db import Database
from jawikiimg.license import LICENSE_POLICY_VERSION


class ReclassifyTests(unittest.TestCase):
    def test_policy_update_reclassifies_once_then_resumes(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "test.sqlite3")
            db.add_images(["Example.jpg"])
            ext = {
                "LicenseShortName": {"value": "CC BY 4.0"},
                "Permission": {"value": "This work is licensed under Creative Commons Attribution 4.0."},
            }
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE images SET metadata_status='done',classification='REVIEW',extmetadata_json=?",
                    (json.dumps(ext),),
                )

            self.assertEqual(classify_pending(db, Control()), 1)
            with db.connect() as conn:
                state = conn.execute("SELECT classification FROM images").fetchone()[0]
            self.assertEqual(state, "ALLOW_CC_BY")
            self.assertEqual(db.get_state("license_policy_version"), LICENSE_POLICY_VERSION)
            self.assertEqual(classify_pending(db, Control()), 0)


if __name__ == "__main__":
    unittest.main()
