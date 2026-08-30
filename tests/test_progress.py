import unittest

from jawikiimg.progress import format_duration, format_progress


class ProgressFormattingTests(unittest.TestCase):
    def test_formats_percentage_counts_speed_and_eta(self):
        text = format_progress({
            "stage": "metadata", "phase": "api", "done": 25, "total": 100,
            "unit": "items", "processed": 25, "rate": 5.0, "rate_unit": "items/s",
            "api_rate": 5.0, "elapsed": 5.0, "current": "File:Example.jpg",
        })
        self.assertIn("metadata取得 / Action API", text)
        self.assertIn("25.0%", text)
        self.assertIn("API 5.00画像/秒", text)
        self.assertIn("残り約 00:15", text)
        self.assertIn("File:Example.jpg", text)

    def test_formats_extract_rows_and_found_count(self):
        text = format_progress({
            "stage": "extract", "phase": "imagelinks", "done": 5242880,
            "total": 10485760, "unit": "bytes", "rows": 123456,
            "found": 7890, "rate": 25000, "rate_unit": "rows/s", "elapsed": 10,
        })
        self.assertIn("5.0 MiB / 10.0 MiB", text)
        self.assertIn("走査 123,456行", text)
        self.assertIn("発見 7,890件", text)
        self.assertIn("25,000行/秒", text)

    def test_duration_over_one_hour(self):
        self.assertEqual(format_duration(3723), "1:02:03")


if __name__ == "__main__":
    unittest.main()
