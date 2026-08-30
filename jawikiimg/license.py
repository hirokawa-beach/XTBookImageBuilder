from __future__ import annotations

from dataclasses import dataclass
import html
import re


ALLOW_STATES = {"ALLOW_PD", "ALLOW_CC0", "ALLOW_CC_BY", "ALLOW_CC_BY_SA"}


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


def _truth(value: str) -> bool | None:
    normalized = re.sub(r"\s+", "", value).lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


def classify(extmetadata: dict) -> Decision:
    values = {key: metadata_value(extmetadata, key) for key in (
        "LicenseShortName", "LicenseUrl", "AttributionRequired", "Copyrighted",
        "NonFree", "Permission", "Restrictions",
    )}
    short = values["LicenseShortName"].strip()
    url = values["LicenseUrl"].strip()
    combined = f"{short} {url}".lower()

    if _truth(values["NonFree"]) is True:
        return Decision("DENY", "NonFree=true")
    # Match NC/ND as license components, avoiding ordinary words.
    if re.search(r"(?:^|[-_/\s])(?:nc|nd)(?:[-_/\s\d.]|$)", combined):
        return Decision("DENY", "license contains a non-commercial or no-derivatives restriction")
    if not short and not url:
        return Decision("REVIEW", "license name and URL are missing")
    if values["Permission"] or values["Restrictions"]:
        fields = ", ".join(key for key in ("Permission", "Restrictions") if values[key])
        return Decision("REVIEW", f"special conditions present in {fields}")

    # Multiple, materially different license markers are not auto-resolved.
    families = set()
    if "cc0" in combined or "publicdomain/zero" in combined:
        families.add("cc0")
    if re.search(r"creativecommons(?:\.org)?/(?:licenses/)?by-sa|\bcc\s*by-sa\b", combined):
        families.add("by-sa")
    if re.search(r"creativecommons(?:\.org)?/(?:licenses/)?by/|\bcc\s*by(?!-sa)\b", combined):
        families.add("by")
    if re.search(r"\b(public domain|public-domain|pd[- _]?(?:mark)?\b)|publicdomain/mark", combined):
        families.add("pd")
    unsupported_marker = re.search(r"\b(gfdl|gnu|art libre|fal|free art)\b", combined)
    if len(families) > 1 or (families and unsupported_marker):
        return Decision("REVIEW", "multiple or conflicting license families")
    if unsupported_marker:
        return Decision("REVIEW", "unsupported license (for example GFDL/FAL)")

    copyrighted = _truth(values["Copyrighted"])
    if families & {"by", "by-sa"} and copyrighted is False:
        return Decision("REVIEW", "metadata contradiction: CC license but Copyrighted=false")
    if "pd" in families and copyrighted is True:
        return Decision("REVIEW", "metadata contradiction: Public Domain but Copyrighted=true")
    if families & {"by", "by-sa"} and _truth(values["AttributionRequired"]) is False:
        return Decision("REVIEW", "metadata contradiction: CC attribution license but AttributionRequired=false")
    if "cc0" in families:
        return Decision("ALLOW_CC0", "unambiguous CC0 metadata")
    if "by-sa" in families:
        return Decision("ALLOW_CC_BY_SA", "unambiguous CC BY-SA metadata")
    if "by" in families:
        return Decision("ALLOW_CC_BY", "unambiguous CC BY metadata")
    if "pd" in families:
        return Decision("ALLOW_PD", "unambiguous Public Domain metadata")
    return Decision("REVIEW", f"unsupported or unrecognized license: {short or url}")
