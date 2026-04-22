"""词典匹配与术语缺失诊断 helper。"""

from __future__ import annotations

import re


def _normalize_glossary_item(item) -> tuple[str, str] | None:
    if not isinstance(item, (list, tuple)) or len(item) < 2:
        return None
    term = str(item[0] or "").strip()
    defn = str(item[1] or "").strip()
    if not term or not defn:
        return None
    return term, defn


def match_glossary_terms(source_text: str, glossary: list) -> list[tuple[str, str]]:
    source = str(source_text or "")
    matched: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in glossary or []:
        normalized = _normalize_glossary_item(item)
        if normalized is None:
            continue
        term, defn = normalized
        key = term.lower()
        if key in seen:
            continue
        if re.search(re.escape(term), source, flags=re.IGNORECASE):
            matched.append((term, defn))
            seen.add(key)
    return matched


def missing_glossary_terms(target_text: str, matched_terms: list[tuple[str, str]]) -> list[tuple[str, str]]:
    target = str(target_text or "")
    return [
        (term, defn)
        for term, defn in (matched_terms or [])
        if defn not in target
    ]


def diagnose_segment_glossary(source_text: str, target_text: str, glossary: list) -> dict:
    matched_terms = match_glossary_terms(source_text, glossary)
    missing_terms = missing_glossary_terms(target_text, matched_terms)
    return {
        "matched_terms": matched_terms,
        "missing_terms": missing_terms,
        "has_issue": bool(missing_terms),
    }
