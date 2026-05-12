"""UnitPageSegmentRecord / UnitParagraphRecord 的压缩序列化/反序列化。

策略：DB 存储用短键名 + 省略可推导字段，反序列化时还原为完整 dict（消费方零修改）。
"""

from __future__ import annotations

from typing import Any


def serialize_segments(segments: list[Any]) -> list[dict]:
    """压缩序列化 page_segments 列表。"""
    return [_serialize_segment(s) for s in (segments or [])]


def deserialize_segments_to_dicts(raw: list[Any]) -> list[dict]:
    """反序列化 page_segments 列表为完整 dict 格式（兼容旧格式）。"""
    return [_deserialize_segment_to_dict(s) for s in (raw or [])]


# ── Segment ──

def _serialize_segment(seg: Any) -> dict:
    paragraphs_raw = getattr(seg, "paragraphs", None) or seg.get("paragraphs", [])
    paragraphs = [_serialize_paragraph(p) for p in paragraphs_raw]
    d: dict[str, Any] = {"p": getattr(seg, "page_no", seg.get("page_no", 0))}
    if paragraphs:
        d["ps"] = paragraphs
    return d


def _deserialize_segment_to_dict(seg: Any) -> dict:
    if not isinstance(seg, dict):
        return {}
    # 旧格式兼容
    if "paragraphs" in seg or "page_no" in seg:
        paragraphs_raw = seg.get("paragraphs") or []
        paragraphs = [_deserialize_paragraph(p) for p in paragraphs_raw]
        visible = [p for p in paragraphs if not p.get("consumed_by_prev", False)]
        source_text = "\n\n".join(
            p.get("source_text", "").strip() for p in visible
            if p.get("source_text", "").strip()
        )
        display_text = "\n\n".join(
            (p.get("display_text") or p.get("source_text", "")).strip()
            for p in visible
            if (p.get("display_text") or p.get("source_text", "")).strip()
        )
        return {
            "page_no": int(seg.get("page_no", 0)),
            "paragraph_count": int(seg.get("paragraph_count", 0)) or len(visible),
            "source_text": source_text,
            "display_text": display_text,
            "paragraphs": paragraphs,
        }
    # 新格式
    paragraphs = [_deserialize_paragraph(p) for p in seg.get("ps") or []]
    visible = [p for p in paragraphs if not p.get("consumed_by_prev", False)]
    page_no = int(seg.get("p", 0))
    source_text = "\n\n".join(
        p.get("source_text", "").strip() for p in visible
        if p.get("source_text", "").strip()
    )
    display_text = "\n\n".join(
        (p.get("display_text") or p.get("source_text", "")).strip()
        for p in visible
        if (p.get("display_text") or p.get("source_text", "")).strip()
    )
    return {
        "page_no": page_no,
        "paragraph_count": len(visible),
        "source_text": source_text,
        "display_text": display_text,
        "paragraphs": paragraphs,
    }


# ── Paragraph ──

def _serialize_paragraph(p: Any) -> dict:
    source = getattr(p, "source_text", "") or p.get("source_text", "") or ""
    display = getattr(p, "display_text", "") or p.get("display_text", "") or ""
    d: dict[str, Any] = {
        "o": getattr(p, "order", p.get("order", 0)),
        "k": getattr(p, "kind", p.get("kind", "body")) or "body",
        "s": source,
    }
    hl = getattr(p, "heading_level", p.get("heading_level", 0))
    if hl:
        d["hl"] = hl
    if display and display != source:
        d["d"] = display
    cp = getattr(p, "cross_page", None) or p.get("cross_page", None)
    if cp:
        d["cp"] = cp
    if getattr(p, "consumed_by_prev", False) or p.get("consumed_by_prev", False):
        d["cbp"] = True
    sp = getattr(p, "section_path", None) or p.get("section_path", None)
    if sp:
        d["sp"] = sp
    ppl = getattr(p, "print_page_label", "") or p.get("print_page_label", "") or ""
    if ppl:
        d["ppl"] = ppl
    tt = getattr(p, "translated_text", "") or p.get("translated_text", "") or ""
    if tt:
        d["tt"] = tt
    ts = getattr(p, "translation_status", p.get("translation_status", "pending")) or "pending"
    if ts != "pending":
        d["ts"] = ts
    ac = getattr(p, "attempt_count", 0) or p.get("attempt_count", 0) or 0
    if ac:
        d["ac"] = ac
    le = getattr(p, "last_error", "") or p.get("last_error", "") or ""
    if le:
        d["le"] = le
    if getattr(p, "manual_resolved", False) or p.get("manual_resolved", False):
        d["mr"] = True
    return d


def _deserialize_paragraph(d: dict) -> dict:
    source = d.get("s") or d.get("source_text") or ""
    display = d.get("d") or d.get("display_text") or ""
    return {
        "order": d.get("o") if "o" in d else d.get("order", 0),
        "kind": d.get("k") if "k" in d else d.get("kind", "body"),
        "heading_level": d.get("hl") if "hl" in d else d.get("heading_level", 0),
        "source_text": source,
        "display_text": display or source,
        "cross_page": d.get("cp") if "cp" in d else d.get("cross_page"),
        "consumed_by_prev": bool(d.get("cbp") if "cbp" in d and "consumed_by_prev" not in d else d.get("consumed_by_prev", False)),
        "section_path": d.get("sp") if "sp" in d else d.get("section_path", []),
        "print_page_label": d.get("ppl") if "ppl" in d else d.get("print_page_label", ""),
        "translated_text": d.get("tt") if "tt" in d else d.get("translated_text", ""),
        "translation_status": (d.get("ts") if "ts" in d else d.get("translation_status", "pending")) or "pending",
        "attempt_count": d.get("ac") if "ac" in d else d.get("attempt_count", 0),
        "last_error": d.get("le") if "le" in d else d.get("last_error", ""),
        "manual_resolved": bool(d.get("mr") if "mr" in d and "manual_resolved" not in d else d.get("manual_resolved", False)),
    }
