from __future__ import annotations

from collections.abc import Iterator
import gzip
import io
from pathlib import Path
import re


_INSERT = re.compile(
    r"^INSERT INTO\s+`(?P<table>[^`]+)`(?:\s*\((?P<columns>[^)]+)\))?\s+VALUES\s*",
    re.IGNORECASE,
)
_COLUMN = re.compile(r"^\s*`([^`]+)`\s+", re.ASCII)


def mysql_unescape(value: str) -> str:
    mapping = {
        "0": "\0",
        "b": "\b",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "Z": "\x1a",
        "\\": "\\",
        "'": "'",
        '"': '"',
        "%": "%",
        "_": "_",
    }
    out: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            i += 1
            out.append(mapping.get(value[i], value[i]))
        else:
            out.append(value[i])
        i += 1
    return "".join(out)


def parse_values(text: str) -> Iterator[tuple[object, ...]]:
    """Parse MySQL VALUES tuples without using comma splitting."""
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,;":
            i += 1
        if i >= n:
            return
        if text[i] != "(":
            raise ValueError(f"expected '(' at offset {i}")
        i += 1
        row: list[object] = []
        while True:
            while i < n and text[i].isspace():
                i += 1
            if i >= n:
                raise ValueError("unterminated tuple")
            if text[i] == "'":
                i += 1
                raw: list[str] = []
                while i < n:
                    ch = text[i]
                    if ch == "\\":
                        if i + 1 >= n:
                            raise ValueError("unterminated escape")
                        raw.extend((ch, text[i + 1]))
                        i += 2
                    elif ch == "'":
                        i += 1
                        break
                    else:
                        raw.append(ch)
                        i += 1
                else:
                    raise ValueError("unterminated string")
                value: object = mysql_unescape("".join(raw))
            else:
                start = i
                while i < n and text[i] not in ",)":
                    i += 1
                token = text[start:i].strip()
                if token.upper() == "NULL":
                    value = None
                elif re.fullmatch(r"[-+]?\d+", token):
                    value = int(token)
                elif re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)(?:[Ee][-+]?\d+)?", token):
                    value = float(token)
                else:
                    value = token
            row.append(value)
            while i < n and text[i].isspace():
                i += 1
            if i >= n:
                raise ValueError("unterminated tuple")
            if text[i] == ",":
                i += 1
                continue
            if text[i] == ")":
                i += 1
                yield tuple(row)
                break
            raise ValueError(f"expected ',' or ')' at offset {i}")


def _open_text(path: Path):
    raw = gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")
    return io.TextIOWrapper(raw, encoding="utf-8", errors="surrogateescape", newline="")


def iter_table_rows(path: Path, table: str) -> Iterator[dict[str, object]]:
    columns: list[str] = []
    in_create = False
    with _open_text(path) as fh:
        for line_no, line in enumerate(fh, 1):
            if re.match(rf"^CREATE TABLE\s+`{re.escape(table)}`", line, re.IGNORECASE):
                in_create = True
                columns = []
                continue
            if in_create:
                match = _COLUMN.match(line)
                if match:
                    columns.append(match.group(1))
                if line.startswith(")"):
                    in_create = False
                continue
            match = _INSERT.match(line)
            if not match or match.group("table").lower() != table.lower():
                continue
            explicit = match.group("columns")
            row_columns = (
                [part.strip().strip("`") for part in explicit.split(",")]
                if explicit
                else columns
            )
            if not row_columns:
                raise ValueError(f"no columns known for {table} at line {line_no}")
            for values in parse_values(line[match.end() :]):
                if len(values) != len(row_columns):
                    raise ValueError(
                        f"column/value mismatch for {table} at line {line_no}: "
                        f"{len(row_columns)} != {len(values)}"
                    )
                yield dict(zip(row_columns, values))

