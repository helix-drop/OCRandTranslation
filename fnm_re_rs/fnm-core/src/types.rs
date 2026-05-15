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
    pub enum NoteKind {
        Footnote => "footnote",
        Endnote => "endnote",
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
    pub enum RegionSource {
        HeadingScan => "heading_scan",
        FootnoteBand => "footnote_band",
        ContinuationMerge => "continuation_merge",
        ManualRebind => "manual_rebind",
        ExplorerTocMatch => "explorer_toc_match",
        ExplorerSignalMatch => "explorer_signal_match",
        FallbackNearestPrior => "fallback_nearest_prior",
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
    /// 与 Python `Literal["rule", "fallback", "repair"]` 对应。
    pub enum LinkResolver {
        Rule => "rule",
        Fallback => "fallback",
        Repair => "repair",
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
        assert_eq!(NoteKind::ALL.len(), 2);
        assert_eq!(RegionScope::ALL.len(), 2);
        assert_eq!(RegionSource::ALL.len(), 7);
        assert_eq!(NoteMode::ALL.len(), 5);
        assert_eq!(AnchorKind::ALL.len(), 3);
        assert_eq!(LinkStatus::ALL.len(), 5);
        assert_eq!(LinkResolver::ALL.len(), 3);
        assert_eq!(PipelineState::ALL.len(), 4);
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
    }
}
