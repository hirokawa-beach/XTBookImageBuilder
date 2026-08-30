from __future__ import annotations

import json
import sys
import time


STAGE_NAMES = {
    "fetch-dumps": "Dump取得",
    "extract": "Dump解析",
    "metadata": "metadata取得",
    "classify": "ライセンス判定",
    "download": "画像取得",
    "convert": "JPEG変換",
    "build": "辞書生成",
}

PHASE_NAMES = {
    "discover": "日付確認",
    "imagelinks": "imagelinks",
    "linktarget": "linktarget",
    "api": "Action API",
    "license": "分類",
    "media": "サムネイル",
    "jpeg": "変換",
    "pack": "画像登録",
    "index": "索引作成",
    "report": "付属ファイル",
    "complete": "完了済み",
}

STATUS_NAMES = {
    "done": "完了",
    "reused": "再利用",
    "limited": "上限到達",
    "running": "処理中",
}


def format_bytes(value: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _amount(value, unit: str | None) -> str:
    if unit == "bytes":
        return format_bytes(float(value))
    return f"{int(value):,}件" if unit == "items" else f"{int(value):,}行"


def format_progress(event: dict) -> str:
    stage = STAGE_NAMES.get(str(event.get("stage", "")), str(event.get("stage", "処理")))
    phase_value = str(event.get("phase", ""))
    phase = PHASE_NAMES.get(phase_value, phase_value)
    heading = f"[{stage}{' / ' + phase if phase else ''}]"
    parts: list[str] = [heading]

    status = event.get("status")
    if status in STATUS_NAMES and status != "running":
        parts.append(STATUS_NAMES[status])

    done = event.get("done")
    total = event.get("total")
    unit = event.get("unit")
    if isinstance(done, (int, float)) and isinstance(total, (int, float)) and total > 0:
        percent = min(100.0, max(0.0, float(done) / float(total) * 100))
        parts.append(f"{_amount(done, unit)} / {_amount(total, unit)} ({percent:5.1f}%)")
    elif isinstance(done, (int, float)):
        parts.append(_amount(done, unit))

    if isinstance(event.get("rows"), (int, float)):
        parts.append(f"走査 {int(event['rows']):,}行")
    if isinstance(event.get("matched"), (int, float)):
        parts.append(f"File候補 {int(event['matched']):,}件")
    if isinstance(event.get("found"), (int, float)):
        parts.append(f"発見 {int(event['found']):,}件")

    if isinstance(event.get("api_rate"), (int, float)):
        parts.append(f"API {event['api_rate']:.2f}画像/秒")
    elif isinstance(event.get("rate"), (int, float)):
        rate_unit = event.get("rate_unit")
        if rate_unit == "B/s":
            parts.append(f"{format_bytes(event['rate'])}/秒")
        elif rate_unit == "rows/s":
            parts.append(f"{event['rate']:,.0f}行/秒")
        else:
            parts.append(f"{event['rate']:.2f}件/秒")
    if isinstance(event.get("dl_mbps"), (int, float)):
        parts.append(f"{event['dl_mbps']:.2f} Mbps")

    elapsed = event.get("elapsed")
    if isinstance(elapsed, (int, float)):
        parts.append(f"経過 {format_duration(elapsed)}")
        if (
            isinstance(done, (int, float)) and isinstance(total, (int, float))
            and 0 < done < total
        ):
            rate = event.get("rate")
            processed = event.get("processed")
            if isinstance(rate, (int, float)) and rate > 0 and unit != "bytes":
                eta = (total - done) / rate
            elif not processed:
                eta = elapsed * (total - done) / done
            else:
                eta = None
            if eta is not None:
                parts.append(f"残り約 {format_duration(eta)}")

    message = event.get("message")
    current = event.get("current")
    if message:
        parts.append(str(message))
    elif current:
        current_text = str(current)
        if len(current_text) > 72:
            current_text = "…" + current_text[-71:]
        parts.append(current_text)
    return " | ".join(parts)


class ConsoleProgress:
    def __init__(self, *, json_mode: bool = False, stream=None):
        self.json_mode = json_mode
        self.stream = stream or sys.stderr
        self.tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.last_key: tuple[str, str] | None = None
        self.last_printed = 0.0
        self.active_line = False

    def __call__(self, event: dict) -> None:
        if self.json_mode:
            print(json.dumps(event, ensure_ascii=False), file=self.stream, flush=True)
            return
        now = time.monotonic()
        key = (str(event.get("stage", "")), str(event.get("phase", "")))
        terminal = event.get("status") in {"done", "reused", "limited"}
        changed = key != self.last_key
        interval = 0.5 if self.tty else 5.0
        if not (changed or terminal or now - self.last_printed >= interval):
            return
        if self.tty:
            if changed and self.active_line:
                print(file=self.stream)
            print("\r\033[K" + format_progress(event), end="\n" if terminal else "", file=self.stream, flush=True)
            self.active_line = not terminal
        else:
            print(format_progress(event), file=self.stream, flush=True)
        self.last_key = key
        self.last_printed = now

    def close(self) -> None:
        if self.tty and self.active_line:
            print(file=self.stream, flush=True)
            self.active_line = False
