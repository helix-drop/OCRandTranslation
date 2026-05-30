//! Post-Phase3 视觉锚点恢复（批次 B3 / 接入点 S2）。
//!
//! Phase 3 产出 `body_anchors` 后，对比 Phase 2 的 expected note markers，
//! 找出每章缺失的 marker → 调 vision LLM 恢复（`run_visual_anchor_recovery`）
//! → 物化为 anchor `create` override 行。override 经 `batch_save` 落 DB，
//! 由「重建 Phase 3」消费，note_links 随之自动重链。
//!
//! 红线（CLAUDE.md §8/§12）：本模块只产 synthetic anchor，经 anchor override
//! 通道注入，**不碰 note_kind**（note_kind 唯一来源是 Phase 2）。

use fnm_core::records::{BodyAnchorRecord, ChapterRecord, NoteItemRecord};
use fnm_phase1::input::RawPage;
use fnm_phase2::visual_anchor_recovery::materialize::ChapterAnchorGap;
use fnm_phase2::visual_anchor_recovery::run_visual_anchor_recovery;
use fnm_phase3::body_anchors::chapter_marker_sets::build_chapter_note_items_set;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

/// 对比 Phase 2 expected markers 与 Phase 3 已命中 anchors，聚合每章缺口。
///
/// - expected：`build_chapter_note_items_set`（chapter_id → 正整数 marker 集）
/// - found：body_anchors 中 `normalized_marker` 可解析为整数的部分
/// - missing = expected − found；仅保留非空者
pub fn build_chapter_anchor_gaps(
    chapters: &[ChapterRecord],
    note_items: &[NoteItemRecord],
    body_anchors: &[BodyAnchorRecord],
) -> Vec<ChapterAnchorGap> {
    let expected = build_chapter_note_items_set(note_items);
    if expected.is_empty() {
        return Vec::new();
    }

    let mut found: HashMap<String, HashSet<i64>> = HashMap::new();
    for anchor in body_anchors {
        if let Ok(marker) = anchor.normalized_marker.parse::<i64>() {
            found
                .entry(anchor.chapter_id.clone())
                .or_default()
                .insert(marker);
        }
    }

    let page_range: HashMap<&str, (i64, i64)> = chapters
        .iter()
        .map(|c| (c.chapter_id.as_str(), (c.start_page, c.end_page)))
        .collect();

    let mut gaps: Vec<ChapterAnchorGap> = Vec::new();
    for (chapter_id, expected_markers) in &expected {
        let found_set = found.get(chapter_id);
        let missing: HashSet<i64> = expected_markers
            .iter()
            .filter(|m| found_set.map(|f| !f.contains(*m)).unwrap_or(true))
            .copied()
            .collect();
        if missing.is_empty() {
            continue;
        }
        let body_page_range = page_range
            .get(chapter_id.as_str())
            .copied()
            .unwrap_or((0, 0));
        gaps.push(ChapterAnchorGap {
            chapter_id: chapter_id.clone(),
            missing_markers: missing,
            body_page_range,
        });
    }
    // 确定性顺序，便于测试与日志稳定
    gaps.sort_by(|a, b| a.chapter_id.cmp(&b.chapter_id));
    gaps
}

/// 把恢复的 anchor 转成 anchor `create` override 三元组 `(scope, target_id, payload)`。
/// scope=`"anchor"` 使其经 `group_review_overrides` 路由到 anchor 处理器。
fn anchor_to_create_override(anchor: &BodyAnchorRecord) -> (String, String, Value) {
    let payload = json!({
        "action": "create",
        "anchor_id": anchor.anchor_id,
        "chapter_id": anchor.chapter_id,
        "page_no": anchor.page_no,
        "char_start": anchor.char_start,
        "char_end": anchor.char_end,
        "normalized_marker": anchor.normalized_marker,
        "source_text": anchor.source_text,
        "source": "visual_recovery",
        "synthetic": true,
    });
    ("anchor".to_string(), anchor.anchor_id.clone(), payload)
}

/// Post-Phase 3 视觉锚点恢复主流程（同步签名，内部局部 `block_on`）。
///
/// 返回待写入 DB 的 anchor override 三元组；空表示无 gap / 无 PDF / 无 vision spec /
/// 全部失败。**调用方负责** `skip_llm_verify` 守卫、`batch_save` 与重建 Phase 3。
pub fn run_post_phase3_visual_recovery(
    chapters: &[ChapterRecord],
    note_items: &[NoteItemRecord],
    body_anchors: &[BodyAnchorRecord],
    raw_pages: &[RawPage],
    pdf_path: &str,
) -> Vec<(String, String, Value)> {
    if pdf_path.is_empty() {
        return Vec::new();
    }
    let gaps = build_chapter_anchor_gaps(chapters, note_items, body_anchors);
    if gaps.is_empty() {
        return Vec::new();
    }

    let page_by_no: HashMap<i64, &RawPage> =
        raw_pages.iter().map(|p| (p.book_page, p)).collect();

    let rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => {
            tracing::warn!("visual_recovery: 无法创建 runtime（跳过）: {e}");
            return Vec::new();
        }
    };

    let mut rows: Vec<(String, String, Value)> = Vec::new();
    for gap in &gaps {
        match rt.block_on(run_visual_anchor_recovery(gap, &page_by_no, pdf_path)) {
            Ok((anchors, _diag)) => {
                if !anchors.is_empty() {
                    tracing::info!(
                        "visual_recovery chapter={} 恢复 {} 个 anchor",
                        gap.chapter_id,
                        anchors.len()
                    );
                }
                for anchor in &anchors {
                    rows.push(anchor_to_create_override(anchor));
                }
            }
            Err(e) => {
                tracing::warn!(
                    "visual_recovery chapter={} 失败（降级跳过）: {e}",
                    gap.chapter_id
                );
            }
        }
    }
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{BoundaryState, ChapterSource};

    fn chapter(id: &str, start: i64, end: i64) -> ChapterRecord {
        ChapterRecord {
            chapter_id: id.to_string(),
            title: String::new(),
            start_page: start,
            end_page: end,
            pages: Vec::new(),
            source: ChapterSource::VisualToc,
            boundary_state: BoundaryState::Ready,
        }
    }

    fn note_item(chapter_id: &str, marker: &str) -> NoteItemRecord {
        NoteItemRecord {
            chapter_id: chapter_id.to_string(),
            marker: marker.to_string(),
            ..Default::default()
        }
    }

    fn anchor(chapter_id: &str, marker: &str) -> BodyAnchorRecord {
        BodyAnchorRecord {
            chapter_id: chapter_id.to_string(),
            normalized_marker: marker.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn gaps_detect_missing_marker() {
        let chapters = vec![chapter("ch-1", 10, 20)];
        let note_items = vec![
            note_item("ch-1", "1"),
            note_item("ch-1", "2"),
            note_item("ch-1", "3"),
        ];
        let anchors = vec![anchor("ch-1", "1"), anchor("ch-1", "2")];
        let gaps = build_chapter_anchor_gaps(&chapters, &note_items, &anchors);
        assert_eq!(gaps.len(), 1);
        assert_eq!(gaps[0].chapter_id, "ch-1");
        assert_eq!(gaps[0].missing_markers, HashSet::from([3]));
        assert_eq!(gaps[0].body_page_range, (10, 20));
    }

    #[test]
    fn gaps_empty_when_all_found() {
        let chapters = vec![chapter("ch-1", 10, 20)];
        let note_items = vec![note_item("ch-1", "1"), note_item("ch-1", "2")];
        let anchors = vec![anchor("ch-1", "1"), anchor("ch-1", "2")];
        let gaps = build_chapter_anchor_gaps(&chapters, &note_items, &anchors);
        assert!(gaps.is_empty());
    }

    #[test]
    fn gaps_empty_when_no_note_items() {
        let chapters = vec![chapter("ch-1", 10, 20)];
        let gaps = build_chapter_anchor_gaps(&chapters, &[], &[]);
        assert!(gaps.is_empty());
    }

    #[test]
    fn create_override_shape() {
        let a = anchor("ch-1", "5");
        let (scope, target_id, payload) = anchor_to_create_override(&a);
        assert_eq!(scope, "anchor");
        assert_eq!(target_id, a.anchor_id);
        assert_eq!(payload["action"], "create");
        assert_eq!(payload["synthetic"], true);
        assert_eq!(payload["normalized_marker"], "5");
        assert_eq!(payload["source"], "visual_recovery");
    }

    #[test]
    fn recovery_skips_without_pdf() {
        let chapters = vec![chapter("ch-1", 10, 20)];
        let note_items = vec![note_item("ch-1", "3")];
        let rows = run_post_phase3_visual_recovery(&chapters, &note_items, &[], &[], "");
        assert!(rows.is_empty());
    }

    /// 红线守卫（CLAUDE.md §8/§12）：视觉锚点恢复只产 anchor override，
    /// **绝不**路由到 note_item/note_region，payload **绝不**含 note_kind。
    /// note_kind 的唯一来源是 Phase 2。
    #[test]
    fn redline_override_never_touches_note_kind() {
        let a = anchor("ch-1", "7");
        let (scope, _id, payload) = anchor_to_create_override(&a);
        // scope 必须是 anchor，绝不路由到 note 处理器
        assert_eq!(scope, "anchor");
        assert_ne!(scope, "note_item");
        assert_ne!(scope, "note_region");
        // payload 绝不携带 note 分类字段
        assert!(payload.get("note_kind").is_none());
        assert!(payload.get("note_item_id").is_none());
        assert!(payload.get("note_mode").is_none());
    }
}
