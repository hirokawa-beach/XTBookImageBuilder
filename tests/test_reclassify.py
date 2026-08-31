from pathlib import Path
import json
import tempfile
import unittest

from jawikiimg.api import classify_pending
from jawikiimg.control import Control
from jawikiimg.db import Database
from jawikiimg.license import LICENSE_POLICY_VERSION
from jawikiimg.manual_review import approve_reviews, clear_manual_decisions, deny_reviews


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

    def test_manual_approval_persists_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "test.sqlite3")
            db.add_images(["Trademarked.svg"])
            ext = {
                "LicenseShortName": {"value": "Public domain"},
                "Restrictions": {"value": "trademarked"},
            }
            with db.transaction() as conn:
                conn.execute(
                    """UPDATE images SET metadata_status='done',classification='REVIEW',
                    classification_reason='Restrictions requires review: trademarked',
                    license_short_name='Public domain',extmetadata_json=?""",
                    (json.dumps(ext),),
                )
            image_id = 1
            self.assertEqual(approve_reviews(db, [image_id], "商標用途ではないことを確認"), 1)
            db.set_state("license_policy_version", LICENSE_POLICY_VERSION - 1)
            classify_pending(db, Control())
            with db.connect() as conn:
                row = conn.execute(
                    "SELECT classification,manual_override,manual_note FROM images WHERE id=?", (image_id,)
                ).fetchone()
            self.assertEqual(tuple(row), ("ALLOW_PD", "ALLOW_PD", "商標用途ではないことを確認"))

            self.assertEqual(clear_manual_decisions(db, [image_id]), 1)
            with db.connect() as conn:
                row = conn.execute(
                    "SELECT classification,manual_override FROM images WHERE id=?", (image_id,)
                ).fetchone()
            self.assertEqual(tuple(row), ("ALLOW_PD", None))

    def test_manual_deny_and_deny_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "test.sqlite3")
            db.add_images(["Review.jpg", "Nonfree.jpg"])
            with db.transaction() as conn:
                conn.execute(
                    """UPDATE images SET classification='REVIEW',license_short_name='CC BY 4.0',
                    extmetadata_json='{}' WHERE dump_title='Review.jpg'"""
                )
                conn.execute(
                    """UPDATE images SET classification='DENY',license_short_name='Fair use',
                    extmetadata_json='{}' WHERE dump_title='Nonfree.jpg'"""
                )
            self.assertEqual(deny_reviews(db, [1], "収録しない"), 1)
            with self.assertRaises(ValueError):
                approve_reviews(db, [2], "override")


if __name__ == "__main__":
    unittest.main()
