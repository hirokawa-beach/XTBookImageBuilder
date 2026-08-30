from __future__ import annotations

from .api import MetadataFetcher, classify_pending
from .attribution import write_attribution, write_report
from .builder import build_dictionary
from .config import Settings
from .control import Control, ProgressCallback, null_progress
from .converter import Converter
from .db import Database
from .downloader import MediaDownloader
from .dumps import extract_images, fetch_dumps


class Pipeline:
    def __init__(self, settings: Settings, control: Control | None = None):
        self.settings = settings
        settings.ensure_dirs()
        self.db = Database(settings.db_path)
        self.control = control or Control()

    def fetch_dumps(self, date=None, progress=null_progress):
        return fetch_dumps(self.settings, self.db, self.control, date, progress)

    def extract(self, limit=None, progress=null_progress):
        return extract_images(self.settings, self.db, self.control, limit, progress)

    def metadata(self, progress=null_progress):
        return MetadataFetcher(self.settings, self.db, self.control).run(progress)

    def classify(self, progress=null_progress):
        return classify_pending(self.db, self.control, progress)

    def download(self, progress=null_progress):
        return MediaDownloader(self.settings, self.db, self.control).run(progress)

    def convert(self, progress=null_progress):
        return Converter(self.settings, self.db, self.control).run(progress)

    def build(self, progress=null_progress):
        return build_dictionary(self.settings, self.db, self.control, progress)

    def report(self):
        snapshot = str(self.db.get_state("snapshot_date", "unknown"))
        target = self.settings.output_dir / f"jawikiimg-{snapshot}-reports"
        write_attribution(self.db, target, snapshot)
        return write_report(self.db, target, snapshot)

    def all(self, *, limit=None, date=None, progress: ProgressCallback = null_progress):
        self.fetch_dumps(date, progress)
        self.extract(limit, progress)
        self.metadata(progress)
        self.classify(progress)
        self.download(progress)
        self.convert(progress)
        return self.build(progress)

