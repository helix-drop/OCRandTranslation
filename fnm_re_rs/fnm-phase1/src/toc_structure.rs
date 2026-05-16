//! ←→ FNM_RE/modules/toc_structure.py
//! Phase1 顶层编排：组装所有子模块输出为 Phase1Structure。

use crate::chapter_skeleton::builder::build_chapter_skeleton;
use crate::heading_graph::build_heading_graph;
use crate::input::{ManualPageOverride, RawPage, TocItem};
use crate::page_partition::build_page_partitions;
use crate::section_heads::build_section_heads;
use fnm_core::db::Repository;
use fnm_core::records::{HeadingCandidate, Phase1Structure};
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct Phase1Config {
    pub manual_page_overrides: Option<HashMap<String, ManualPageOverride>>,
    pub pdf_path: Option<String>,
    pub doc_id: Option<String>,
    /// LLM book-type 校验开关。当前 Rust 端 LLM 客户端尚未接入 phase1
    /// 主入口，默认 `true`（跳过）；传 `false` 触发 `anyhow::bail!`。
    pub skip_llm_verify: bool,
}

impl Default for Phase1Config {
    fn default() -> Self {
        Self {
            manual_page_overrides: None,
            pdf_path: None,
            doc_id: None,
            skip_llm_verify: true,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Phase1Output {
    pub structure: Phase1Structure,
    pub diagnostics: serde_json::Value,
}

/// Phase1 主入口：从原始页面构建章节骨架。
pub fn build_phase1_structure(
    pages: &[RawPage],
    toc_items: Option<&[TocItem]>,
    config: &Phase1Config,
) -> anyhow::Result<Phase1Output> {
    let total_pages = pages.len() as i64;

    // 1. LLM book-type 校验：Rust 端 LLM 客户端尚未接入主入口（FNM_PHASE12_AUDIT G5）。
    //    config.skip_llm_verify=false 时显式 bail 防误用（AGENTS.md §9）。
    if !config.skip_llm_verify {
        anyhow::bail!(
            "Phase1Config::skip_llm_verify=false 暂不支持——\
             LLM book-type 校验需 vision client 接入主入口（FNM_PHASE12_AUDIT G5）"
        );
    }

    // 2. build_page_partitions —— 把 manual_page_overrides 真传下去（原 None 静默忽略 F7）
    let partitions_result =
        build_page_partitions(pages, config.manual_page_overrides.as_ref(), None);
    let page_partitions = partitions_result.partitions;

    // 3. 构建 heading candidates（page_rows → collect → normalize）
    let page_rows = crate::chapter_skeleton::heading_candidates::page_rows::legacy_page_rows(
        &page_partitions,
        Some(pages),
    );
    let heading_candidates: Vec<HeadingCandidate> =
        crate::chapter_skeleton::heading_candidates::collect_heading_candidate_rows(
            &page_rows,
            toc_items,
            0,
            &config.pdf_path.clone().unwrap_or_default(),
            None,
            Some(&partitions_result.file_idx_map),
            &config.doc_id.clone().unwrap_or_default(),
        );

    // 4. build_section_heads
    let (section_heads, _) = build_section_heads(&[], &heading_candidates, &page_partitions, None);

    // 5. build_heading_graph（完整版：local_exact + expanded_exact 锚点解析）
    let toc_exportable: Vec<(String, i64, String)> = toc_items
        .map(|items| {
            items
                .iter()
                .filter(|item| item.export_candidate.unwrap_or(true))
                .map(|item| {
                    (
                        item.title.clone(),
                        item.target_pdf_page.unwrap_or(0),
                        item.role_hint.clone(),
                    )
                })
                .collect()
        })
        .unwrap_or_default();
    let page_role_pairs: Vec<(i64, String)> = page_partitions
        .iter()
        .map(|p| (p.page_no, p.page_role.as_str().to_string()))
        .collect();
    let heading_graph = build_heading_graph(&toc_exportable, &heading_candidates, &page_role_pairs);

    // 6. build_chapter_skeleton
    let skeleton = build_chapter_skeleton(
        pages,
        toc_items,
        &page_partitions,
        &heading_graph,
        heading_candidates,
    );

    // 注：`build_book_note_profile` 不在主入口调用——
    // 它推断的 `chapter_modes` 在 phase2 `chapter_split` 内会重新生成
    // （CLAUDE.md §12 分类源头唯一：note_mode 是 phase2 决策权）。
    // phase1 的 book_note_type 模块保留给 LLM book-type verify 用作 prior
    // （FNM_PHASE12_AUDIT G5）。

    // 7. 组装 Phase1Structure（page_partitions 已 owned，零 clone）
    let structure = Phase1Structure {
        pages: page_partitions,
        heading_candidates: skeleton.heading_candidates,
        chapters: skeleton.chapters,
        section_heads,
        endnote_explorer_hints: Default::default(),
        summary: Default::default(),
    };

    Ok(Phase1Output {
        structure,
        diagnostics: serde_json::json!({
            "total_pages": total_pages,
            "source": "Rust fnm-phase1",
        }),
    })
}

/// 把 Phase1Output 持久化到 DB（消耗 ownership，零 clone）。
pub fn persist_phase1(
    repo: &dyn Repository,
    doc_id: &str,
    output: Phase1Output,
) -> anyhow::Result<()> {
    repo.replace_fnm_phase1_products(
        doc_id,
        &fnm_core::db::Phase1Products {
            pages: output.structure.pages,
            chapters: output.structure.chapters,
            heading_candidates: output.structure.heading_candidates,
            section_heads: output.structure.section_heads,
        },
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::input::RawPage;

    #[test]
    fn build_structure_empty_pages() {
        let config = Phase1Config::default();
        let output = build_phase1_structure(&[], None, &config).unwrap();
        assert!(output.structure.pages.is_empty());
        assert!(output.structure.chapters.is_empty());
    }

    #[test]
    fn build_structure_single_page() {
        let pages = vec![RawPage {
            book_page: 1,
            markdown: "# Test\nContent".into(),
            ..Default::default()
        }];
        let config = Phase1Config::default();
        let output = build_phase1_structure(&pages, None, &config).unwrap();
        assert_eq!(output.structure.pages.len(), 1);
        assert_eq!(output.structure.pages[0].page_no, 1);
    }
}
