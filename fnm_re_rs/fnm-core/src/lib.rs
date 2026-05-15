//! `fnm-core` — FNM_RE Rust 重写的基础设施层。
//!
//! 被后续所有 phase crate（fnm-phase1 到 fnm-phase6、fnm-llm-repair、fnm-orchestrator）依赖。
//!
//! ## 模块对应
//!
//! | 模块 | Python 源 |
//! |---|---|
//! | `types` | `FNM_RE/constants.py` |
//! | `records` | `FNM_RE/models.py` |
//! | `text` | `FNM_RE/shared/text.py` |
//! | `title` | `FNM_RE/shared/title.py` |
//! | `refs` | `FNM_RE/shared/refs.py` |
//! | `ref_rewriter` | `FNM_RE/shared/ref_rewriter.py` |
//! | `anchor_kind` | `FNM_RE/shared/anchors.py` (resolve_anchor_kind + regex) |
//! | `note_marker` | `FNM_RE/shared/notes.py` (normalize_note_marker, is_notes_heading_line) |
//! | `note_modes` | `FNM_RE/shared/note_modes.py` |
//! | `marker_seq` | `FNM_RE/shared/marker_sequences.py` |
//! | `chapters` | `FNM_RE/shared/chapters.py` |
//! | `note_lookup` | `FNM_RE/shared/note_lookup.py` |
//! | `review` | `FNM_RE/shared/review.py` |
//! | `review_overrides` | `FNM_RE/shared/review_overrides.py` |
//! | `segments` | `FNM_RE/shared/segments.py` |
//! | `segment_codec` | `FNM_RE/shared/segment_codec.py` |
//! | `token_counter` | `FNM_RE/shared/token_counter.py` |
//! | `export_constants` | `FNM_RE/shared/export_constants.py` |
//! | `db` | `persistence/sqlite_schema.py` + Repository trait |

pub mod anchor_kind;
pub mod chapters;
pub mod db;
pub mod export_constants;
pub mod marker_seq;
pub mod note_lookup;
pub mod note_marker;
pub mod note_modes;
pub mod records;
pub mod ref_rewriter;
pub mod refs;
pub mod review;
pub mod review_overrides;
pub mod segment_codec;
pub mod segments;
pub mod text;
pub mod title;
pub mod token_counter;
pub mod types;

#[cfg(test)]
pub mod testing;
