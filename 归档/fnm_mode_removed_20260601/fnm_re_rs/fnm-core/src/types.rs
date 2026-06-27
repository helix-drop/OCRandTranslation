//! ←→ FNM_RE/constants.py
//! 所有 Literal 类型翻译为 Rust enum。

use serde::{Deserialize, Serialize};
use std::str::FromStr;

macro_rules! enum_with_str {
    (
        $(#[doc = $doc:literal])*
        $vis:vis enum $name:ident {
            $($variant:ident => $s:literal),+ $(,)?
        }
    ) => {
        $(#[doc = $doc])*
        #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
        #[serde(rename_all = "snake_case")]
        $vis enum $name {
            $($variant),+
        }

        impl $name {
            pub fn as_str(self) -> &'static str {
                match self {
                    $(Self::$variant => $s),+
                }
            }

            pub const ALL: &[$name] = &[$(Self::$variant),+];
        }

        impl FromStr for $name {
            type Err = String;
            fn from_str(s: &str) -> Result<Self, Self::Err> {
                match s.trim() {
                    $($s => Ok(Self::$variant)),+,
                    other => Err(format!("unknown {}: {other}", stringify!($name))),
                }
            }
        }
    };
}

enum_with_str! {
    /// 与 Python `Literal["noise", "front_matter", "body", "note", "other"]` 对应。
    pub enum PageRole {
        Noise => "noise",
        FrontMatter => "front_matter",
        Body => "body",
        Note => "note",
        Other => "other",
    }
}

enum_with_str! {
    /// 与 Python `Literal["visual_toc", "fallback"]` 对应。
    pub enum ChapterSource {
        VisualToc => "visual_toc",
        Fallback => "fallback",
    }
}

enum_with_str! {
    /// 与 Python `Literal["ready", "review_required"]` 对应。
    pub enum BoundaryState {
        Ready => "ready",
        ReviewRequired => "review_required",
    }
}

enum_with_str! {
    /// 与 Python `Literal["footnote", "endnote"]` 对应。
    /// `Unknown` 为 Rust 增设，用于 DB 读回非法值或未初始化的安全兜底。
    pub enum NoteKind {
        Footnote => "footnote",
        Endnote => "endnote",
        Unknown => "unknown",
    }
}

enum_with_str! {
    /// 与 Python `Literal["chapter", "book"]` 对应。
    pub enum RegionScope {
        Chapter => "chapter",
        Book => "book",
    }
}

enum_with_str! {
    /// 与 Python `RegionSource` Literal 对应。
    /// `Llm` 对应 Phase 3 LLM override 注入（Python 端运行期写 "llm" 字符串突破 Literal）。
    pub enum RegionSource {
        HeadingScan => "heading_scan",
        FootnoteBand => "footnote_band",
        ContinuationMerge => "continuation_merge",
        ManualRebind => "manual_rebind",
        ExplorerTocMatch => "explorer_toc_match",
        ExplorerSignalMatch => "explorer_signal_match",
        FallbackNearestPrior => "fallback_nearest_prior",
        ChapterBoundaryFallback => "chapter_boundary_fallback",
        Llm => "llm",
    }
}

enum_with_str! {
    /// 与 Python `NoteMode` Literal 对应。
    pub enum NoteMode {
        FootnotePrimary => "footnote_primary",
        ChapterEndnotePrimary => "chapter_endnote_primary",
        BookEndnoteBound => "book_endnote_bound",
        NoNotes => "no_notes",
        ReviewRequired => "review_required",
    }
}

enum_with_str! {
    /// 与 Python `Literal["footnote", "endnote", "unknown"]` 对应。
    pub enum AnchorKind {
        Footnote => "footnote",
        Endnote => "endnote",
        Unknown => "unknown",
    }
}

enum_with_str! {
    /// 与 Python `LinkStatus` Literal 对应。
    pub enum LinkStatus {
        Matched => "matched",
        OrphanNote => "orphan_note",
        OrphanAnchor => "orphan_anchor",
        Ambiguous => "ambiguous",
        Ignored => "ignored",
    }
}

enum_with_str! {
    /// 与 Python `Literal["rule", "fallback", "repair", "orphan_recovery"]` 对应。
    pub enum LinkResolver {
        Rule => "rule",
        Fallback => "fallback",
        Repair => "repair",
        OrphanRecovery => "orphan_recovery",
    }
}

enum_with_str! {
    /// 与 Python `Literal["idle", "running", "error", "done"]` 对应。
    pub enum PipelineState {
        Idle => "idle",
        Running => "running",
        Error => "error",
        Done => "done",
    }
}

enum_with_str! {
    /// 全书 note 类型分类（phase1 决策、phase2/3 透传）。
    ///
    /// 与 Python `Literal["mixed", "endnote_only", "footnote_only", "no_notes"]` 对应。
    /// 用 enum 替代字符串字面量传递，避免下游 `if book_type == "endnote_only"`
    /// 拼写错误的 silent fallthrough（CLAUDE.md §12 分类源头唯一）。
    pub enum BookType {
        Mixed => "mixed",
        EndnoteOnly => "endnote_only",
        FootnoteOnly => "footnote_only",
        NoNotes => "no_notes",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_role_serialize_matches_python() {
        assert_eq!(
            serde_json::to_string(&PageRole::FrontMatter).unwrap(),
            "\"front_matter\""
        );
    }

    #[test]
    fn page_role_parse_strips_whitespace() {
        assert_eq!(PageRole::from_str("  body  ").ok(), Some(PageRole::Body));
    }

    #[test]
    fn page_role_from_str_none_for_junk() {
        assert!(PageRole::from_str("garbage").is_err());
        assert!(PageRole::from_str("").is_err());
    }

    #[test]
    fn all_enums_have_all_const() {
        assert_eq!(PageRole::ALL.len(), 5);
        assert_eq!(ChapterSource::ALL.len(), 2);
        assert_eq!(BoundaryState::ALL.len(), 2);
        assert_eq!(NoteKind::ALL.len(), 3);
        assert_eq!(RegionScope::ALL.len(), 2);
        assert_eq!(RegionSource::ALL.len(), 9);
        assert_eq!(NoteMode::ALL.len(), 5);
        assert_eq!(AnchorKind::ALL.len(), 3);
        assert_eq!(LinkStatus::ALL.len(), 5);
        assert_eq!(LinkResolver::ALL.len(), 4);
        assert_eq!(PipelineState::ALL.len(), 4);
        assert_eq!(BookType::ALL.len(), 4);
    }

    #[test]
    fn all_enums_roundtrip() {
        for v in PageRole::ALL {
            assert_eq!(PageRole::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in ChapterSource::ALL {
            assert_eq!(ChapterSource::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in BoundaryState::ALL {
            assert_eq!(BoundaryState::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in NoteKind::ALL {
            assert_eq!(NoteKind::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in RegionScope::ALL {
            assert_eq!(RegionScope::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in RegionSource::ALL {
            assert_eq!(RegionSource::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in NoteMode::ALL {
            assert_eq!(NoteMode::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in AnchorKind::ALL {
            assert_eq!(AnchorKind::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in LinkStatus::ALL {
            assert_eq!(LinkStatus::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in LinkResolver::ALL {
            assert_eq!(LinkResolver::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in PipelineState::ALL {
            assert_eq!(PipelineState::from_str(v.as_str()).ok(), Some(*v));
        }
        for v in BookType::ALL {
            assert_eq!(BookType::from_str(v.as_str()).ok(), Some(*v));
        }
    }
}
