from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from jawikiimg.api import MetadataFetcher
from jawikiimg.config import Settings
from jawikiimg.control import Control, StopRequested
from jawikiimg.db import Database


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def close(self):
        pass


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None):
        del url
        title = params["titles"]
        self.calls.append(title)
        bare = title.removeprefix("File:")
        page = {
            "pageid": len(self.calls), "ns": 6, "title": title,
            "imageinfo": [{
                "canonicaltitle": title, "thumburl": "https://upload.wikimedia.org/test.jpg",
                "mime": "image/jpeg", "thumbmime": "image/jpeg", "sha1": "abc",
                "width": 10, "height": 10, "size": 100,
                "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{bare}",
                "extmetadata": {"LicenseShortName": {"value": "CC0 1.0"}},
            }],
        }
        return FakeResponse({"query": {"pages": [page]}})


class ResumeTests(unittest.TestCase):
    def test_metadata_resume_skips_completed_rows(self):
        with tempfile.TemporaryDirectory() as td:
            settings = replace(
                Settings(), workdir=Path(td), api_batch_size=1,
                user_agent="JawikiImgBuilderBot/0.1 (test@example.org) requests/2",
            )
            db = Database(settings.db_path)
            db.add_images(["One.jpg", "Two.jpg", "Three.jpg"])
            control = Control()
            first_client = FakeClient()

            def stop_after_first(event):
                if event.get("done") == 1:
                    control.stop()

            with self.assertRaises(StopRequested):
                MetadataFetcher(settings, db, control, first_client).run(stop_after_first)
            self.assertEqual(len(first_client.calls), 1)
            second_client = FakeClient()
            MetadataFetcher(settings, db, Control(), second_client).run()
            self.assertEqual(len(second_client.calls), 2)
            self.assertEqual(db.counts()["metadata_done"], 3)


if __name__ == "__main__":
    unittest.main()

