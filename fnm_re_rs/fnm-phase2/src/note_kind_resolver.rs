//! ←→ stages/note_items.py:_resolve_note_kind + note_regions.py 区域分类逻辑
//!
//! **这是 Phase 2 的核心设计点**：note_kind 的唯一权威来源。
//! Phase 3+ 严禁覆盖 note_kind，只能透传。
//!
//! ## 决策树（按优先级）
//!
//! ```text
//! resolve_note_kind(ctx)
//! ├─ 1. 显式 "Endnotes" / "Notes to Pages" heading → endnote
//! ├─ 2. 显式 "Footnotes" / "Notes" heading → footnote
//! ├─ 3. footnote_band 检测命中 → footnote
//! ├─ 4. 章后隐式尾注区 (is_post_body_region) → endnote
//! ├─ 5. book-scope endnote 区 (is_book_scope) → endnote
//! └─ 6. 兜底 → review_required = true
//! ```

use fnm_core::types::NoteKind;

pub struct NoteRegionContext<'a> {
    pub heading_text: &'a str,
    pub has_footnote_band: bool,
    pub is_post_body_region: bool,
    pub is_book_scope: bool,
    pub explicit_markers: &'a [&'a str],
}

pub struct NoteKindResolution {
    pub note_kind: NoteKind,
    pub confidence: f64,
    pub reason: String,
    pub review_required: bool,
}

/// 单一权威函数：给定 region 上下文，决定 note_kind。
pub fn resolve_note_kind(ctx: &NoteRegionContext) -> NoteKindResolution {
    let heading_lower = ctx.heading_text.to_lowercase();

    // 1. 显式 endnote heading
    if heading_lower.contains("endnote")
        || heading_lower.contains("notes to pages")
        || heading_lower.contains("notes to chapter")
    {
        return NoteKindResolution {
            note_kind: NoteKind::Endnote,
            confidence: 0.98,
            reason: "explicit_heading_endnote".into(),
            review_required: false,
        };
    }

    // 2. 显式 footnote heading
    if heading_lower.contains("footnote") || heading_lower == "notes" {
        return NoteKindResolution {
            note_kind: NoteKind::Footnote,
            confidence: 0.95,
            reason: "explicit_heading_footnote".into(),
            review_required: false,
        };
    }

    // 3. footnote band 检测命中
    if ctx.has_footnote_band {
        return NoteKindResolution {
            note_kind: NoteKind::Footnote,
            confidence: 0.85,
            reason: "footnote_band".into(),
            review_required: false,
        };
    }

    // 4. 章后隐式尾注区
    if ctx.is_post_body_region {
        return NoteKindResolution {
            note_kind: NoteKind::Endnote,
            confidence: 0.75,
            reason: "post_body_endnote".into(),
            review_required: false,
        };
    }

    // 5. book-scope endnote
    if ctx.is_book_scope {
        return NoteKindResolution {
            note_kind: NoteKind::Endnote,
            confidence: 0.90,
            reason: "book_scope_endnote".into(),
            review_required: false,
        };
    }

    // 6. 兜底 — 不要默认 footnote
    NoteKindResolution {
        note_kind: NoteKind::Footnote,
        confidence: 0.40,
        reason: "fallback_review_required".into(),
        review_required: true,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_endnote_heading() {
        let ctx = NoteRegionContext {
            heading_text: "Endnotes",
            has_footnote_band: false,
            is_post_body_region: false,
            is_book_scope: false,
            explicit_markers: &[],
        };
        let r = resolve_note_kind(&ctx);
        assert_eq!(r.note_kind, NoteKind::Endnote);
        assert!(!r.review_required);
    }

    #[test]
    fn explicit_footnote_heading() {
        let ctx = NoteRegionContext {
            heading_text: "Footnotes",
            has_footnote_band: false,
            is_post_body_region: false,
            is_book_scope: false,
            explicit_markers: &[],
        };
        let r = resolve_note_kind(&ctx);
        assert_eq!(r.note_kind, NoteKind::Footnote);
    }

    #[test]
    fn footnote_band_priority() {
        let ctx = NoteRegionContext {
            heading_text: "",
            has_footnote_band: true,
            is_post_body_region: false,
            is_book_scope: false,
            explicit_markers: &[],
        };
        let r = resolve_note_kind(&ctx);
        assert_eq!(r.note_kind, NoteKind::Footnote);
    }

    #[test]
    fn post_body_endnote() {
        let ctx = NoteRegionContext {
            heading_text: "",
            has_footnote_band: false,
            is_post_body_region: true,
            is_book_scope: false,
            explicit_markers: &[],
        };
        let r = resolve_note_kind(&ctx);
        assert_eq!(r.note_kind, NoteKind::Endnote);
    }

    #[test]
    fn fallback_review_required() {
        let ctx = NoteRegionContext {
            heading_text: "",
            has_footnote_band: false,
            is_post_body_region: false,
            is_book_scope: false,
            explicit_markers: &[],
        };
        let r = resolve_note_kind(&ctx);
        assert!(r.review_required);
    }
}
