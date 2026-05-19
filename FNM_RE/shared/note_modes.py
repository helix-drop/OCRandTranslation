"""note_mode 的 canonical ↔ DB alias 双向映射。

Canonical NoteMode（来自 `FNM_RE.constants.NoteMode`）：
- footnote_primary
- chapter_endnote_primary
- book_endnote_bound
- no_notes
- review_required

DB / 展示用别名（在 status summary 和 fnm_chapter_note_modes 表中持久化）：
- footnote_primary          → footnote_primary
- chapter_endnote_primary   → chapter_endnotes
- book_endnote_bound        → book_endnotes
- no_notes                  → body_only
- 其他（review_required 等） → mixed_or_unclear

集中在此文件，避免散落到多处启发式 `if "footnote" in mode.lower()` 判断。
"""

from __future__ import annotations

from FNM_RE.constants import NoteMode

# Canonical → DB / 展示别名
MODE_TO_DB_ALIAS: dict[str, str] = {
    "footnote_primary": "footnote_primary",
    "chapter_endnote_primary": "chapter_endnotes",
    "book_endnote_bound": "book_endnotes",
    "no_notes": "body_only",
}

# DB / 展示别名 → Canonical（反向）
DB_ALIAS_TO_MODE: dict[str, NoteMode] = {
    "footnote_primary": "footnote_primary",
    "chapter_endnotes": "chapter_endnote_primary",
    "book_endnotes": "book_endnote_bound",
    "body_only": "no_notes",
}

# Status summary 的 5 个固定 bucket
_SUMMARY_BUCKETS: tuple[str, ...] = (
    "footnote_primary",
    "chapter_endnotes",
    "book_endnotes",
    "body_only",
    "mixed_or_unclear",
)


def to_db_alias(canonical_mode: str) -> str:
    """Canonical NoteMode → DB / 展示别名。

    未知 mode 落到 'mixed_or_unclear'（包括 review_required 与空串）。
    """
    return MODE_TO_DB_ALIAS.get(str(canonical_mode or "").strip(), "mixed_or_unclear")


def from_db_alias(alias: str) -> str:
    """DB / 展示别名 → Canonical NoteMode。

    未知 alias 原样返回（用于向后兼容旧数据）。
    """
    key = str(alias or "").strip()
    return DB_ALIAS_TO_MODE.get(key, key)


def new_chapter_mode_summary() -> dict[str, int]:
    """生成空的 chapter mode summary（5 个 bucket 全 0）。"""
    return {bucket: 0 for bucket in _SUMMARY_BUCKETS}


def increment_chapter_mode_summary(summary: dict[str, int], canonical_mode: str) -> None:
    """按 canonical mode 把 summary 对应 bucket +1。"""
    bucket = to_db_alias(canonical_mode)
    if bucket not in summary:
        bucket = "mixed_or_unclear"
    summary[bucket] = int(summary.get(bucket, 0)) + 1
