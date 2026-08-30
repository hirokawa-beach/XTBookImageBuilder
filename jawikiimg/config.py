from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
import tomllib


@dataclass(frozen=True)
class Settings:
    workdir: Path = Path("work")
    user_agent: str = (
        "JawikiImgBuilderBot/0.1 "
        "(https://example.invalid/replace-with-real-contact) requests/2"
    )
    api_url: str = "https://ja.wikipedia.org/w/api.php"
    dump_base_url: str = "https://dumps.wikimedia.org/jawiki"
    api_requests_per_second: float = 2.0
    api_batch_size: int = 10
    media_workers: int = 2
    media_mbps: float = 20.0
    convert_workers: int = 2
    minimum_free_gib: float = 2.0
    thumbnail_width: int = 960
    jpeg_quality: int = 85
    max_width: int = 800
    max_height: int = 480
    mkimagecomplex_bin: str | None = None

    @property
    def db_path(self) -> Path:
        return self.workdir / "jawikiimg.sqlite3"

    @property
    def dumps_dir(self) -> Path:
        return self.workdir / "dumps"

    @property
    def downloads_dir(self) -> Path:
        return self.workdir / "downloads"

    @property
    def converted_dir(self) -> Path:
        return self.workdir / "converted"

    @property
    def output_dir(self) -> Path:
        return self.workdir / "output"

    def ensure_dirs(self) -> None:
        for path in (
            self.workdir,
            self.dumps_dir,
            self.downloads_dir,
            self.converted_dir,
            self.output_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def validate(self, *, network: bool = False) -> None:
        if not 1 <= self.api_batch_size <= 50:
            raise ValueError("api_batch_size must be between 1 and 50")
        if not 1 <= self.media_workers <= 2:
            raise ValueError("media_workers must be 1 or 2")
        if self.media_mbps <= 0 or self.media_mbps > 25:
            raise ValueError("media_mbps must be in (0, 25]")
        if self.api_requests_per_second <= 0 or self.api_requests_per_second >= 5:
            raise ValueError("api_requests_per_second must be in (0, 5)")
        if network:
            lowered = self.user_agent.lower()
            if "bot" not in lowered or "example.invalid" in lowered:
                raise ValueError(
                    "Set a descriptive bot User-Agent with real contact information "
                    "in config.toml (see config.toml.example)."
                )
            contact = re.search(r"\(([^)]+)\)", self.user_agent)
            if not contact or not any(
                marker in contact.group(1) for marker in ("@", "http://", "https://", "User:")
            ):
                raise ValueError("Wikimedia User-Agent must contain operator contact information")


def load_settings(config_path: Path | None, workdir: Path | None = None) -> Settings:
    settings = Settings()
    path = config_path or Path("config.toml")
    if path.exists():
        with path.open("rb") as fh:
            raw = tomllib.load(fh).get("jawikiimg", {})
        known = set(Settings.__dataclass_fields__)
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {', '.join(sorted(unknown))}")
        if "workdir" in raw:
            raw["workdir"] = Path(raw["workdir"])
        settings = replace(settings, **raw)
    if workdir is not None:
        settings = replace(settings, workdir=workdir)
    settings.validate()
    return settings

