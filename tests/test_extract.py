from dataclasses import replace
from pathlib import Path
import gzip
import tempfile
import unittest

from jawikiimg.config import Settings
from jawikiimg.control import Control
from jawikiimg.db import Database
from jawikiimg.dumps import extract_images


class ExtractTests(unittest.TestCase):
    def test_current_linktarget_schema_namespace_filter_and_limit(self):
        linktarget = """CREATE TABLE `linktarget` (
 `lt_id` bigint NOT NULL,
 `lt_namespace` int NOT NULL,
 `lt_title` varbinary(255) NOT NULL
);
INSERT INTO `linktarget` VALUES (10,6,'First.png'),(11,6,'Second.jpg'),(12,0,'Not_a_file'),(13,6,'Third.svg');
"""
        imagelinks = """CREATE TABLE `imagelinks` (
 `il_from` int NOT NULL,
 `il_from_namespace` int NOT NULL,
 `il_target_id` bigint NOT NULL
);
INSERT INTO `imagelinks` VALUES (1,1,10),(2,0,10),(3,0,11),(4,0,12),(5,0,13);
"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            settings = replace(Settings(), workdir=root)
            settings.ensure_dirs()
            paths = {}
            for kind, content in (("linktarget", linktarget), ("imagelinks", imagelinks)):
                path = settings.dumps_dir / f"{kind}.sql.gz"
                with gzip.open(path, "wt", encoding="utf-8") as fh:
                    fh.write(content)
                paths[kind] = path
            db = Database(settings.db_path)
            with db.transaction() as conn:
                for kind, path in paths.items():
                    conn.execute(
                        "INSERT INTO dumps(kind,snapshot_date,url,local_path,status) VALUES(?,?,?,?, 'done')",
                        (kind, "20260101", "https://example.invalid/" + path.name, str(path)),
                    )
            found = extract_images(settings, db, Control(), limit=2)
            self.assertEqual(found, 2)
            with db.connect() as conn:
                titles = [row[0] for row in conn.execute("SELECT dump_title FROM images ORDER BY id")]
            self.assertEqual(titles, ["First.png", "Second.jpg"])
            events = []
            found = extract_images(settings, db, Control(), limit=3, progress=events.append)
            self.assertEqual(found, 3)
            self.assertTrue(any(
                event.get("phase") == "linktarget" and event.get("status") == "reused"
                for event in events
            ))


if __name__ == "__main__":
    unittest.main()
