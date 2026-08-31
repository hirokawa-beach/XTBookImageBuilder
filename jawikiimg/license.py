from __future__ import annotations

from dataclasses import dataclass
import html
import re


ALLOW_STATES = {"ALLOW_PD", "ALLOW_CC0", "ALLOW_CC_BY", "ALLOW_CC_BY_SA"}
LICENSE_POLICY_VERSION = 4


@dataclass(frozen=True)
class Decision:
    state: str
    reason: str


def metadata_value(extmetadata: dict, key: str) -> str:
    item = extmetadata.get(key)
    if isinstance(item, dict):
        item = item.get("value", "")
    if item is None:
        return ""
    text = html.unescape(str(item))
    return re.sub(r"<[^>]*>", " ", text).strip()


def _license_families(text: str) -> tuple[set[str], bool]:
    families: set[str] = set()
    if "cc0" in text or "publicdomain/zero" in text:
        families.add("cc0")
    if re.search(
        r"creativecommons(?:\.org)?/(?:licenses/)?by-sa|"
        r"\bcc\s*by-sa\b|creative commons attribution[- ]sharealike",
        text,
    ):
        families.add("by-sa")
    if re.search(
        r"creativecommons(?:\.org)?/(?:licenses/)?by/|"
        r"\bcc\s*by(?!-sa)\b|creative commons attribution(?![- ]sharealike)",
        text,
    ):
        families.add("by")
    if re.search(r"\b(public domain|public-domain|pd[- _]?(?:mark)?\b)|publicdomain/mark", text):
        families.add("pd")
    unsupported = bool(re.search(r"\b(gfdl|gnu free documentation|art libre|fal|free art)\b", text))
    return families, unsupported


def supported_allow_state(license_short_name: str, license_url: str = "") -> str | None:
    """Map LicenseShortName to an ALLOW state; other metadata is not consulted."""
    del license_url  # Kept in the signature for callers; policy uses the name only.
    name = license_short_name.strip().lower()
    if re.search(r"(?:^|[-_/\s])(?:nc|nd)(?:[-_/\s\d.]|$)", name):
        return None
    families, _unsupported = _license_families(name)
    if not families:
        return None
    # A supported option in a multi-license name is sufficient; the generated
    # attribution files retain the original complete LicenseShortName.
    for family, state in (
        ("cc0", "ALLOW_CC0"),
        ("pd", "ALLOW_PD"),
        ("by", "ALLOW_CC_BY"),
        ("by-sa", "ALLOW_CC_BY_SA"),
    ):
        if family in families:
            return state
    return None


def classify(extmetadata: dict) -> Decision:
    short = metadata_value(extmetadata, "LicenseShortName").strip()
    if not short:
        return Decision("REVIEW", "LicenseShortName is missing")

    lowered = short.lower()
    if re.search(r"(?:^|[-_/\s])(?:nc|nd)(?:[-_/\s\d.]|$)", lowered):
        return Decision("DENY", f"LicenseShortName is NC/ND: {short}")
    if re.search(r"\b(?:fair use|non[- ]?free|all rights reserved)\b", lowered):
        return Decision("DENY", f"LicenseShortName is non-free: {short}")

    state = supported_allow_state(short)
    if state:
        return Decision(state, f"allowed by LicenseShortName: {short}")
    return Decision("REVIEW", f"unsupported or unrecognized LicenseShortName: {short}")
