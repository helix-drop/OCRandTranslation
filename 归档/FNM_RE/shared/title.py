"""FNM_RE 标题相关工具。"""

from __future__ import annotations

import re
import unicodedata

_TITLE_KEY_CLEAN_RE = re.compile(r"[^0-9a-zà-ÿ]+")
_TITLE_PREFIX_RE = re.compile(r"^\s*(?:\d+|[ivxlcdm]+)[\.\)]\s*", re.IGNORECASE)
_TITLE_LABEL_RE = re.compile(r"^\s*(?:chapter|chapitre|part|section)\b[:\s\-]*", re.IGNORECASE)
_OTHER_TITLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("contents", (r"^contents\b", r"^table of contents$", r"^table$", r"^table des mati[eè]res$", r"^sommaire$")),
    (
        "illustrations",
        (
            r"^illustrations?$",
            r"^list of illustrations$",
            r"^list of figures$",
            r"^liste des illustrations?$",
            r"^liste des figures?$",
            r"^tables and maps$",
            r"^tables$",
            r"^figures and tables$",
            r"^figures$",
        ),
    ),
    ("bibliography", (r"^bibliograph", r"^references?$", r"^works cited$", r"^livres et articles\b")),
    ("index", (r"^index\b", r"^indices?\b")),
    ("appendix", (r"^appendix\b", r"^appendices$", r"^annex", r"^glossary$", r"^note on sources$", r"^sources?$", r"^conventions$", r"^abbreviations?$")),
    (
        "front_matter",
        (r"^acknowledg", r"^remerciement", r"^foreword$", r"^preface$", r"^avant-propos$", r"^avertissement$", r"^abstract$", r"^introduction$"),
    ),
)


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).strip()


def normalized_title_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", normalize_title(value).lower())
    folded = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]+", "", folded)


def chapter_title_match_key(value: str) -> str:
    normalized = normalize_title(value).lower()
    normalized = _TITLE_LABEL_RE.sub("", normalized).strip()
    normalized = _TITLE_PREFIX_RE.sub("", normalized).strip()
    return _TITLE_KEY_CLEAN_RE.sub("", normalized)


def guess_title_family(value: str, *, page_no: int, total_pages: int) -> str:
    safe_page_no = max(1, int(page_no))
    safe_total_pages = max(1, int(total_pages))
    lowered = normalize_title(value).lower()
    for family, patterns in _OTHER_TITLE_PATTERNS:
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns):
            return family
    if safe_page_no <= max(12, int(safe_total_pages * 0.08)) and lowered == "introduction":
        return "front_matter"
    return "body"
