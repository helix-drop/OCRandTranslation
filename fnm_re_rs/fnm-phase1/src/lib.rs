//! `fnm-phase1` — FNM_RE Phase 1: 从原始 OCR 页面构建章节骨架。
//!
//! ## 模块对应
//!
//! | 模块 | Python 源 |
//! |---|---|
//! | `input` | Input types (RawPage, TocItem) |
//! | `page_partition` | `FNM_RE/stages/page_partition.py` |
//! | `section_heads` | `FNM_RE/stages/section_heads.py` |
//! | `heading_graph` | `FNM_RE/stages/heading_graph.py` |
//! | `chapter_skeleton` | `FNM_RE/stages/chapter_skeleton/` |
//! | `book_note_type` | `FNM_RE/modules/book_note_type.py` |
//! | `llm_book_type_verify` | `FNM_RE/modules/llm_book_type_verify.py` |
//! | `toc_structure` | `FNM_RE/modules/toc_structure.py` |

pub mod book_note_type;
pub mod chapter_skeleton;
pub mod heading_graph;
pub mod input;
pub mod llm_book_type_verify;
pub mod page_partition;
pub mod section_heads;
pub mod toc_structure;
