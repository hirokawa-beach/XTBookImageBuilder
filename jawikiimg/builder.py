from __future__ import annotations

from pathlib import Path
import plistlib
import shutil
import subprocess

from .attribution import write_attribution, write_report
from .config import Settings
from .control import Control, ProgressCallback, null_progress
from .db import Database
from .http import check_free_space
from .license import ALLOW_STATES


def info_plist() -> dict:
    return {
        "XTBDictionaryIdentifier": "com.nexhawks.XTBook.WikipediaImages.ja",
        "XTBDictionaryScheme": "jawikiimg",
        "XTBDictionaryTypeIdentifier": "com.nexhawks.XTBook.ImageComplex",
        "XTBImageComplexImagesFile": "Images",
        "XTBDictionaryDisplayName": "Japanese Wikipedia Images",
    }


def find_mkimagecomplex(settings: Settings) -> str:
    candidates = [settings.mkimagecomplex_bin, shutil.which("MkImageComplex-bin")]
    local = Path("tools") / "MkImageComplex-bin"
    if local.exists():
        candidates.append(str(local.resolve()))
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate).resolve())
    raise RuntimeError(
        "MkImageComplex-bin not found. Set mkimagecomplex_bin or run "
        "scripts/build_mkimagecomplex_arm64.sh on Raspberry Pi."
    )


def build_dictionary(
    settings: Settings,
    db: Database,
    control: Control,
    progress: ProgressCallback = null_progress,
) -> Path:
    settings.ensure_dirs()
    snapshot = str(db.get_state("snapshot_date", ""))
    if not snapshot:
        raise RuntimeError("dump snapshot date is unknown")
    placeholders = ",".join("?" for _ in ALLOW_STATES)
    params = tuple(sorted(ALLOW_STATES))
    with db.connect() as conn:
        converted_count = int(conn.execute(
            f"SELECT COUNT(*) FROM images WHERE classification IN ({placeholders}) "
            "AND convert_status='done'", params,
        ).fetchone()[0])
        incomplete = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE classification IN ({placeholders}) "
            "AND convert_status!='done'", params,
        ).fetchone()[0]
    if incomplete:
        raise RuntimeError(f"cannot build: {incomplete} ALLOW images are not converted")
    if not converted_count:
        raise RuntimeError("cannot build an empty dictionary")
    binary = find_mkimagecomplex(settings)
    bundle = settings.output_dir / f"jawikiimg-{snapshot}.xtbdict"
    bundle.mkdir(parents=True, exist_ok=True)
    progress({"stage": "build", "current": "MkImageComplex-bin", "total": converted_count})
    process = subprocess.Popen(
        [binary, "-o", str(bundle.resolve())], stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    assert process.stdin is not None
    try:
        with db.connect() as conn:
            rows = conn.execute(
                f"SELECT jpeg_path FROM images WHERE classification IN ({placeholders}) "
                "AND convert_status='done' ORDER BY id", params,
            )
            for index, row in enumerate(rows, 1):
                control.checkpoint()
                if index % 1000 == 0:
                    check_free_space(bundle, settings.minimum_free_gib)
                process.stdin.write(str(Path(row["jpeg_path"]).resolve()) + "\n")
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr else ""
        code = process.wait()
    except BaseException:
        process.terminate()
        process.wait(timeout=10)
        raise
    if code:
        raise RuntimeError(f"MkImageComplex-bin exited {code}: {stderr[-4000:]}")
    with (bundle / "Info.plist").open("wb") as fh:
        plistlib.dump(info_plist(), fh, fmt=plistlib.FMT_XML, sort_keys=False)
    write_attribution(db, bundle, snapshot)
    write_report(db, bundle, snapshot)
    db.set_state("build_complete", str(bundle))
    progress({"stage": "build", "current": "done", "bundle": str(bundle)})
    return bundle
