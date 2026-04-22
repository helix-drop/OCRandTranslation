"""FNM_RE 复核覆盖层工具。"""

from __future__ import annotations


def group_review_overrides(rows: list[dict] | None) -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, dict]] = {
        "page": {},
        "chapter": {},
        "region": {},
        "link": {},
        "llm_suggestion": {},
        "anchor": {},
        "note_item": {},
    }
    for row in rows or []:
        scope = str((row or {}).get("scope") or "").strip().lower()
        target_id = str((row or {}).get("target_id") or "").strip()
        if not scope or not target_id:
            continue
        grouped.setdefault(scope, {})[target_id] = dict((row or {}).get("payload") or {})
    return grouped


def annotate_review_note_links(note_links: list[dict] | None, overrides: dict[str, dict[str, dict]] | None) -> list[dict]:
    link_overrides = dict((overrides or {}).get("link") or {})
    annotated: list[dict] = []
    for link in note_links or []:
        payload = dict(link or {})
        override = dict(link_overrides.get(str(payload.get("link_id") or ""), {}) or {})
        if override:
            payload["review_override"] = override
            payload["review_action"] = str(override.get("action") or "").strip().lower()
        annotated.append(payload)
    return annotated


def collect_llm_suggestions(overrides: dict[str, dict[str, dict]] | None) -> list[dict]:
    suggestions: list[dict] = []
    for suggestion_id, payload in sorted(dict((overrides or {}).get("llm_suggestion") or {}).items()):
        item = dict(payload or {})
        item["suggestion_id"] = suggestion_id
        suggestions.append(item)
    return suggestions
