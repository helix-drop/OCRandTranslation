//! 章节 Markdown 渲染模块。
//! 承担 Phase6 此前提供的 build_export_chapters / build_section_markdown 职责。
//!
//! ←→ fnm-phase6/src/export/ 对应文件：
//!   merge             → export/contract.rs (build_export_chapters)
//!   section_render    → export/section_render.rs
//!   body_render       → export/body_render.rs
//!   note_lookup       → export/note_lookup.rs
//!   section_head      → export/section_head.rs
//!   title             → export/title.rs
//!   chapter_pages     → export/chapter_pages.rs
//!   markdown_clean    → export/markdown_clean.rs
//!   diagnostic_text   → export/diagnostic_text.rs
//!   filename          → export/filename.rs
//!   book_type         → export/book_type.rs
//!   paragraph_key     → export/paragraph_key.rs
//!   footnote          → export/footnote.rs
//!   section_builder   → section_render 子步骤
//!
//! 本模块不依赖 fnm-phase6，由 fnm-phase5 直接使用。

pub mod body_render;
pub mod book_type;
pub mod chapter_pages;
pub mod diagnostic_text;
pub mod filename;
pub mod footnote;
pub mod markdown_clean;
pub mod merge;
pub mod note_lookup;
mod section_builder;
pub mod section_head;
pub mod section_render;
pub mod title;
