from pathlib import Path
import sqlite3
import tempfile
import unittest

from jawikiimg.db import Database


class DatabaseMigrationTests(unittest.TestCase):
    def test_existing_images_table_gets_manual_review_columns(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy.sqlite3"
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    """CREATE TABLE images (
                    id INTEGER PRIMARY KEY, dump_title TEXT,
                    metadata_status TEXT, classification TEXT,
                    download_status TEXT, convert_status TEXT
                    )"""
                )
                conn.commit()
            finally:
                conn.close()
            db = Database(path)
            with db.connect() as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(images)")}
            self.assertTrue({"manual_override", "manual_note", "manual_updated_at"} <= columns)


if __name__ == "__main__":
    unittest.main()
