//! Phase 2 输入类型。

use fnm_core::records::{ChapterRecord, PagePartitionRecord, SectionHeadRecord};
use fnm_phase1::input::RawPage;

/// Phase 2 输入：Phase 1 结构 + 原始页面 + 配置。
pub struct Phase2Input<'a> {
    pub phase1_chapters: &'a [ChapterRecord],
    pub phase1_pages: &'a [PagePartitionRecord],
    pub phase1_section_heads: &'a [SectionHeadRecord],
    pub raw_pages: &'a [RawPage],
    pub pdf_path: Option<&'a str>,
    pub config: Phase2Config,
}

#[derive(Default)]
pub struct Phase2Config {
    pub skip_sup_recovery: bool,
    pub skip_llm_verify: bool,
}
