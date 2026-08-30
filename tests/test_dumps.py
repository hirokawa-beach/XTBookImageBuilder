import unittest

from jawikiimg.dumps import _get_status, _snapshot_dates


def status(date, *, complete=True):
    job_status = "done" if complete else "waiting"
    return {
        # This is the dumpstatus schema version, not the snapshot date.
        "version": "0.8",
        "jobs": {
            "imagelinkstable": {
                "status": job_status,
                "files": {
                    f"jawiki-{date}-imagelinks.sql.gz": {
                        "url": f"/jawiki/{date}/jawiki-{date}-imagelinks.sql.gz"
                    }
                },
            },
            "linktargettable": {
                "status": job_status,
                "files": {
                    f"jawiki-{date}-linktarget.sql.gz": {
                        "url": f"/jawiki/{date}/jawiki-{date}-linktarget.sql.gz"
                    }
                },
            },
        },
    }


class FakeResponse:
    def __init__(self, *, text="", payload=None):
        self.text = text
        self.payload = payload

    def json(self):
        return self.payload

    def close(self):
        pass


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return self.responses[url]


class DumpDiscoveryTests(unittest.TestCase):
    def test_snapshot_dates_are_unique_and_newest_first(self):
        html = '<a href="20260101/">old</a><a href="latest/">latest</a>' \
               '<a href="20260301/">new</a><a href="20260101/">duplicate</a>'
        self.assertEqual(_snapshot_dates(html), ["20260301", "20260101"])

    def test_latest_skips_incomplete_snapshot(self):
        base = "https://dumps.wikimedia.org/jawiki"
        client = FakeClient({
            base + "/": FakeResponse(
                text='<a href="20260801/">new</a><a href="20260701/">old</a>'
            ),
            base + "/20260801/dumpstatus.json": FakeResponse(
                payload=status("20260801", complete=False)
            ),
            base + "/20260701/dumpstatus.json": FakeResponse(
                payload=status("20260701")
            ),
        })
        date, data = _get_status(client, base, None)
        self.assertEqual(date, "20260701")
        self.assertEqual(data["version"], "0.8")

    def test_explicit_snapshot_uses_directory_date_not_json_version(self):
        base = "https://dumps.wikimedia.org/jawiki"
        client = FakeClient({
            base + "/20260801/dumpstatus.json": FakeResponse(
                payload=status("20260801")
            )
        })
        date, _ = _get_status(client, base, "20260801")
        self.assertEqual(date, "20260801")


if __name__ == "__main__":
    unittest.main()
