from __future__ import annotations

from dataclasses import dataclass
import html
import re


ALLOW_STATES = {"ALLOW_PD", "ALLOW_CC0", "ALLOW_CC_BY", "ALLOW_CC_BY_SA"}
LICENSE_POLICY_VERSION = 2


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


def _excerpt(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[:limit - 1] + "…"


_PERMISSION_WARNINGS = (
    (r"\b(?:non[- ]?commercial|no[- ]?derivatives?|all rights reserved)\b", "usage restriction"),
    (r"\b(?:may|might|could|possibly)\b.{0,80}\bcopyright", "uncertain copyright status"),
    (r"\bcopyright\b.{0,80}\b(?:unknown|uncertain|unclear|undetermined)\b", "uncertain copyright status"),
    (r"\bno known (?:copyright )?restrictions?\b", "copyright status is not guaranteed"),
    (r"\bcannot\b.{0,100}\b(?:guarantee|determine|verify|absolute statement)\b", "status cannot be verified"),
    (r"\b(?:source|publication date|date of publication)\b.{0,100}\b(?:missing|unknown|needed|required|provide)\b", "source or publication date needs review"),
    (r"\b(?:provide|supply)\b.{0,80}\b(?:source|publication date|date of publication)\b", "source or publication date needs review"),
    (r"\bpermission\b.{0,50}\b(?:required|needed|obtain|contact)\b", "additional permission may be required"),
    (r"\bcontact\b.{0,50}\b(?:author|creator|copyright|rightsholder|rights holder)\b", "contact with a rightsholder is requested"),
    (r"\b(?:additional|special)\b.{0,40}\b(?:terms?|conditions?|restrictions?|permission)\b", "additional conditions are present"),
    (r"\b(?:only|solely)\b", "an additional limitation may be present"),
)


def _permission_problem(permission: str, license_families: set[str]) -> str | None:
    """Return a review reason, or ``None`` for known non-restrictive metadata.

    Permission is free text.  We only accept a small set of common Commons
    boilerplates; unknown prose remains REVIEW rather than being guessed safe.
    """
    if not permission:
        return None
    text = re.sub(r"\s+", " ", permission).strip().lower()
    for pattern, reason in _PERMISSION_WARNINGS:
        if re.search(pattern, text, flags=re.DOTALL):
            return f"Permission: {reason}: {_excerpt(permission)}"

    permission_families, unsupported = _license_families(text)
    if unsupported or len(permission_families) > 1:
        return f"Permission mentions another or multiple licenses: {_excerpt(permission)}"
    if permission_families and permission_families != license_families:
        return f"Permission conflicts with LicenseShortName/LicenseUrl: {_excerpt(permission)}"

    # Commons' Flickr review boilerplate confirms the license already recorded
    # in LicenseShortName/LicenseUrl; it does not add a use restriction.
    if "flickr" in text and re.search(r"confirm(?:ed|ation).{0,100}licen[cs]", text):
        return None

    # Public-domain explanations for works made by US federal employees in
    # their official duties are supporting provenance, not extra conditions.
    if "pd" in license_families or "cc0" in license_families:
        if "public domain" in text and re.search(
            r"(?:united states|u\.s\.).{0,80}(?:federal government|military|armed forces)|"
            r"(?:officer|employee).{0,100}official duties",
            text,
        ):
            return None

    # Image-maintenance templates recommending an SVG/vector replacement do
    # not change the copyright license.
    if re.search(
        r"vector (?:version|graphics).{0,120}(?:available|recreat|replace|instead)|"
        r"(?:recreat|replace).{0,100}vector graphics",
        text,
    ):
        return None

    # A restatement of the same supported license, optionally with ordinary
    # attribution wording, is safe when no warning above was found.
    if permission_families == license_families and re.search(
        r"\b(?:is |are |was )?licen[cs]ed under\b|\bcreative commons\b", text
    ):
        return None

    return f"unrecognized Permission text requires review: {_excerpt(permission)}"


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
    free_text_conditions = f"{values['Permission']} {values['Restrictions']}".lower()
    if re.search(r"\b(?:non[- ]?commercial|no[- ]?derivatives?)\b", free_text_conditions):
        return Decision("DENY", "metadata explicitly contains a non-commercial or no-derivatives restriction")
    if not short and not url:
        return Decision("REVIEW", "license name and URL are missing")
    # Multiple, materially different license markers are not auto-resolved.
    families, unsupported_marker = _license_families(combined)
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

    if values["Restrictions"]:
        return Decision(
            "REVIEW",
            f"Restrictions requires review: {_excerpt(values['Restrictions'])}",
        )
    permission_problem = _permission_problem(values["Permission"], families)
    if permission_problem:
        return Decision("REVIEW", permission_problem)

    permission_note = " (Permission contains known non-restrictive metadata)" if values["Permission"] else ""
    if "cc0" in families:
        return Decision("ALLOW_CC0", "unambiguous CC0 metadata" + permission_note)
    if "by-sa" in families:
        return Decision("ALLOW_CC_BY_SA", "unambiguous CC BY-SA metadata" + permission_note)
    if "by" in families:
        return Decision("ALLOW_CC_BY", "unambiguous CC BY metadata" + permission_note)
    if "pd" in families:
        return Decision("ALLOW_PD", "unambiguous Public Domain metadata" + permission_note)
    return Decision("REVIEW", f"unsupported or unrecognized license: {short or url}")
