from pathlib import Path
import gzip
import tempfile
import unittest

from jawikiimg.sqlparser import iter_table_rows, parse_values


class SQLParserTests(unittest.TestCase):
    def test_mysql_values_quotes_commas_and_escapes(self):
        text = "(1,'A,B','quote\\\'s',NULL,'line\\nnext','back\\\\slash'),(2,'日本語',3.5,0,'x','y');"
        rows = list(parse_values(text))
        self.assertEqual(rows[0][1], "A,B")
        self.assertEqual(rows[0][2], "quote's")
        self.assertIsNone(rows[0][3])
        self.assertEqual(rows[0][4], "line\nnext")
        self.assertEqual(rows[0][5], "back\\slash")
        self.assertEqual(rows[1][1], "日本語")

    def test_schema_columns_and_explicit_columns(self):
        sql = """CREATE TABLE `linktarget` (
  `lt_id` bigint unsigned NOT NULL,
  `lt_namespace` int NOT NULL,
  `lt_title` varbinary(255) NOT NULL
);
INSERT INTO `linktarget` VALUES (1,6,'A,B.png'),(2,0,'Article');
INSERT INTO `linktarget` (`lt_title`,`lt_id`,`lt_namespace`) VALUES ('Reordered.jpg',3,6);
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.sql"
            path.write_text(sql, encoding="utf-8")
            rows = list(iter_table_rows(path, "linktarget"))
        self.assertEqual(rows[0], {"lt_id": 1, "lt_namespace": 6, "lt_title": "A,B.png"})
        self.assertEqual(rows[2]["lt_id"], 3)
        self.assertEqual(rows[2]["lt_title"], "Reordered.jpg")

    def test_old_imagelinks_schema(self):
        sql = """CREATE TABLE `imagelinks` (
 `il_from` int NOT NULL,
 `il_to` varbinary(255) NOT NULL,
 `il_from_namespace` int NOT NULL
);
INSERT INTO `imagelinks` VALUES (4,'Old\\_name.png',0);
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.sql"
            path.write_text(sql, encoding="utf-8")
            row = next(iter_table_rows(path, "imagelinks"))
        self.assertEqual(row["il_to"], "Old_name.png")

    def test_reports_input_byte_progress(self):
        sql = """CREATE TABLE `sample` (\n `id` int NOT NULL\n);\nINSERT INTO `sample` VALUES (1),(2);\n"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.sql.gz"
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                fh.write(sql)
            size = path.stat().st_size
            events = []
            rows = list(iter_table_rows(path, "sample", lambda done, total: events.append((done, total))))
        self.assertEqual(len(rows), 2)
        self.assertTrue(events)
        self.assertEqual(events[-1], (size, size))


if __name__ == "__main__":
    unittest.main()
