//! ←→ Python `FNM_RE/stages/units.py`（L509-687）
//!
//! ref 物化上下文 + 章级 ref 注入。
//!
//! 与 `ref_freeze/inject.rs` 的 `inject_token_once` 接口相似但语义不同：
//! 本模块版本在已 split/trim 后的 structured page text 上注入，且不维护 conflict 状态。

use fnm_core::note_marker::normalize_note_marker;
use fnm_core::records::{BodyAnchorRecord, NoteLinkRecord};
use fnm_core::refs::{cleanup_nested_note_refs, frozen_note_ref};
use fnm_core::types::LinkStatus;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::{HashMap, HashSet};

use super::body_pages::StructuredBodyPage;

// ── 类型 ──────────────────────────────────────────────────────

/// ref 物化上下文。
#[derive(Debug, Clone, Default)]
pub struct RefMaterializationContext {
    pub anchors_by_id: HashMap<String, BodyAnchorRecord>,
    pub conflict_anchor_ids: HashSet<String>,
    pub unresolved_marker_keys: HashSet<(String, String, String)>,
    pub matched_link_count: usize,
    pub ignored_skipped_count: usize,
    pub ambiguous_skipped_count: usize,
}

/// ref 注入摘要。
#[derive(Debug, Clone, Default)]
pub struct RefInjectionSummary {
    pub injected_link_count: usize,
    pub synthetic_skipped_count: usize,
}

// ── 公开函数 ──────────────────────────────────────────────────────

/// ←→ Python `_ref_materialization_context` (units.py:509-559)
///
/// 构建 ref 物化上下文：anchor 索引、conflict anchor、unresolved marker keys。
pub fn ref_materialization_context(
    body_anchors: &[BodyAnchorRecord],
    effective_note_links: &[NoteLinkRecord],
) -> RefMaterializationContext {
    // 构建 anchor 索引
    let anchors_by_id: HashMap<String, BodyAnchorRecord> = body_anchors
        .iter()
        .filter(|a| !a.anchor_id.trim().is_empty())
        .map(|a| (a.anchor_id.trim().to_string(), a.clone()))
        .collect();

    // 收集 matched links
    let matched_links: Vec<&NoteLinkRecord> = effective_note_links
        .iter()
        .filter(|l| l.status == LinkStatus::Matched)
        .collect();

    // 构建 anchor → note_ids 映射，找出 conflict anchors
    let mut anchor_to_note_ids: HashMap<String, HashSet<String>> = HashMap::new();
    for link in &matched_links {
        let anchor_id = link.anchor_id.trim().to_string();
        let note_item_id = link.note_item_id.trim().to_string();
        if anchor_id.is_empty() || note_item_id.is_empty() {
            continue;
        }
        anchor_to_note_ids
            .entry(anchor_id)
            .or_default()
            .insert(note_item_id);
    }
    let conflict_anchor_ids: HashSet<String> = anchor_to_note_ids
        .iter()
        .filter(|(_, note_ids)| note_ids.len() > 1)
        .map(|(anchor_id, _)| anchor_id.clone())
        .collect();

    // 收集 unresolved marker keys
    let mut unresolved_marker_keys: HashSet<(String, String, String)> = effective_note_links
        .iter()
        .filter(|l| l.status == LinkStatus::Ambiguous || l.status == LinkStatus::OrphanAnchor)
        .filter_map(|l| {
            let marker = normalize_note_marker(&l.marker);
            if marker.is_empty() {
                None
            } else {
                Some((
                    l.chapter_id.clone(),
                    l.note_kind.as_str().to_string(),
                    marker,
                ))
            }
        })
        .collect();

    // 检查 anchor marker 重复
    let mut anchor_marker_counts: HashMap<(String, String, String), usize> = HashMap::new();
    for anchor in body_anchors {
        if anchor.synthetic {
            continue;
        }
        let kind_str = anchor.anchor_kind.as_str();
        if kind_str != "endnote" && kind_str != "footnote" {
            continue;
        }
        let marker = normalize_note_marker(if !anchor.normalized_marker.is_empty() {
            &anchor.normalized_marker
        } else {
            &anchor.source_marker
        });
        if marker.is_empty() {
            continue;
        }
        let key = (anchor.chapter_id.clone(), kind_str.to_string(), marker);
        *anchor_marker_counts.entry(key).or_default() += 1;
    }
    for (key, count) in anchor_marker_counts {
        if count > 1 {
            unresolved_marker_keys.insert(key);
        }
    }

    let matched_link_count = matched_links.len();
    let ignored_skipped_count = effective_note_links
        .iter()
        .filter(|l| l.status == LinkStatus::Ignored)
        .count();
    let ambiguous_skipped_count = effective_note_links
        .iter()
        .filter(|l| l.status == LinkStatus::Ambiguous)
        .count();

    RefMaterializationContext {
        anchors_by_id,
        conflict_anchor_ids,
        unresolved_marker_keys,
        matched_link_count,
        ignored_skipped_count,
        ambiguous_skipped_count,
    }
}

/// ←→ Python `_inject_token_once` (units.py:562-590)
///
/// 在文本中注入 NOTE_REF token。与 ref_freeze 版本接口相似但语义不同：
/// 此版本在已 split/trim 后的 structured page text 上注入。
pub fn inject_token_once(
    text: &str,
    anchor: &BodyAnchorRecord,
    marker: &str,
    note_id: &str,
) -> (String, bool) {
    let payload = text;
    if payload.is_empty() {
        return (payload.to_string(), false);
    }
    let token = frozen_note_ref(note_id);
    if token.is_empty() {
        return (payload.to_string(), false);
    }

    // 候选 1：anchor.source_marker
    let source_marker = anchor.source_marker.trim();
    if !source_marker.is_empty() && payload.contains(source_marker) {
        return (payload.replacen(source_marker, &token, 1), true);
    }

    // 候选 2：[{marker}]
    let bracket_marker = format!("[{}]", marker.trim());
    if !marker.trim().is_empty() && payload.contains(&bracket_marker) {
        return (payload.replacen(&bracket_marker, &token, 1), true);
    }

    // 候选 3：正则 fallback
    let normalized_marker = marker.trim();
    if !normalized_marker.is_empty() {
        static BRACKET_RE_CACHE: Lazy<std::sync::Mutex<HashMap<String, Regex>>> =
            Lazy::new(|| std::sync::Mutex::new(HashMap::new()));

        let re = {
            let mut cache = BRACKET_RE_CACHE.lock().unwrap();
            cache
                .entry(normalized_marker.to_string())
                .or_insert_with(|| {
                    Regex::new(&format!(
                        r"\[\s*(?:\^)?\s*{}\s*\]",
                        regex::escape(normalized_marker)
                    ))
                    .unwrap()
                })
                .clone()
        };
        let mut replaced = false;
        let result = re
            .replace(payload, |_: &regex::Captures| {
                replaced = true;
                token.as_str()
            })
            .to_string();
        if replaced {
            return (result, true);
        }
    }

    (payload.to_string(), false)
}

/// ←→ Python `_materialize_refs_for_chapter` (units.py:593-687)
///
/// 章级 ref 物化：在 body pages 上注入 NOTE_REF token。
pub fn materialize_refs_for_chapter(
    chapter_id: &str,
    body_pages: &[StructuredBodyPage],
    effective_note_links: &[NoteLinkRecord],
    ref_ctx: &RefMaterializationContext,
) -> (Vec<StructuredBodyPage>, RefInjectionSummary) {
    let mut page_payload_by_no: HashMap<i64, StructuredBodyPage> = body_pages
        .iter()
        .filter(|p| p.page_no > 0)
        .cloned()
        .map(|p| (p.page_no, p))
        .collect();

    let mut synthetic_skipped = 0;
    let mut injected_count = 0;

    // 收集本章的 matched links
    let mut chapter_links: Vec<&NoteLinkRecord> = effective_note_links
        .iter()
        .filter(|l| l.status == LinkStatus::Matched && l.chapter_id == chapter_id)
        .collect();

    // 按 anchor 排序：(page_no, -char_start, link_id)
    chapter_links.sort_by(|a, b| {
        let anchor_a = ref_ctx
            .anchors_by_id
            .get(a.anchor_id.trim())
            .map(|a| (a.page_no, a.char_start))
            .unwrap_or((0, 0));
        let anchor_b = ref_ctx
            .anchors_by_id
            .get(b.anchor_id.trim())
            .map(|a| (a.page_no, a.char_start))
            .unwrap_or((0, 0));
        anchor_a
            .0
            .cmp(&anchor_b.0)
            .then(anchor_b.1.cmp(&anchor_a.1)) // char_start 降序
            .then(a.link_id.cmp(&b.link_id))
    });

    let mut injected_anchor_ids: HashSet<String> = HashSet::new();

    for link in chapter_links {
        let anchor_id = link.anchor_id.trim().to_string();
        let note_id = link.note_item_id.trim().to_string();
        if anchor_id.is_empty() || note_id.is_empty() {
            continue;
        }
        if injected_anchor_ids.contains(&anchor_id) {
            continue;
        }

        // 检查 unresolved marker key
        let marker_key = (
            link.chapter_id.clone(),
            link.note_kind.as_str().to_string(),
            normalize_note_marker(&link.marker),
        );
        if ref_ctx.unresolved_marker_keys.contains(&marker_key) {
            continue;
        }

        // 检查 conflict anchor
        if ref_ctx.conflict_anchor_ids.contains(&anchor_id) {
            continue;
        }

        let anchor = match ref_ctx.anchors_by_id.get(&anchor_id) {
            Some(a) => a,
            None => continue,
        };

        // 检查 synthetic anchor
        if anchor.synthetic {
            let sm = anchor.source_marker.trim();
            if sm.is_empty() {
                synthetic_skipped += 1;
                continue;
            }
            let nm = anchor.normalized_marker.trim();
            if sm == nm {
                synthetic_skipped += 1;
                continue;
            }
        }

        let page_no = anchor.page_no;
        let payload = match page_payload_by_no.get_mut(&page_no) {
            Some(p) => p,
            None => continue,
        };

        let (updated_text, replaced) =
            inject_token_once(&payload.text, anchor, &link.marker, &note_id);
        if replaced {
            payload.text = updated_text;
            injected_count += 1;
            injected_anchor_ids.insert(anchor_id);
        }
    }

    // cleanup nested note refs
    for payload in page_payload_by_no.values_mut() {
        let cleaned = cleanup_nested_note_refs(&payload.text);
        if cleaned != payload.text {
            payload.text = cleaned;
        }
    }

    // 保持原始顺序
    let normalized_pages: Vec<StructuredBodyPage> = body_pages
        .iter()
        .filter_map(|p| page_payload_by_no.get(&p.page_no).cloned())
        .collect();

    (
        normalized_pages,
        RefInjectionSummary {
            injected_link_count: injected_count,
            synthetic_skipped_count: synthetic_skipped,
        },
    )
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{AnchorKind, NoteKind};

    fn make_anchor(
        anchor_id: &str,
        chapter_id: &str,
        page_no: i64,
        source_marker: &str,
    ) -> BodyAnchorRecord {
        BodyAnchorRecord {
            anchor_id: anchor_id.to_string(),
            chapter_id: chapter_id.to_string(),
            page_no,
            char_start: 0,
            char_end: 0,
            source_text: String::new(),
            source_marker: source_marker.to_string(),
            normalized_marker: source_marker.to_string(),
            anchor_kind: AnchorKind::Footnote,
            synthetic: false,
            certainty: 1.0,
            ..Default::default()
        }
    }

    fn make_link(
        link_id: &str,
        anchor_id: &str,
        note_item_id: &str,
        chapter_id: &str,
        status: LinkStatus,
    ) -> NoteLinkRecord {
        NoteLinkRecord {
            link_id: link_id.to_string(),
            anchor_id: anchor_id.to_string(),
            note_item_id: note_item_id.to_string(),
            chapter_id: chapter_id.to_string(),
            note_kind: NoteKind::Footnote,
            marker: "1".to_string(),
            status,
            ..Default::default()
        }
    }

    #[test]
    fn test_ref_materialization_context_basic() {
        let anchors = vec![
            make_anchor("a1", "ch1", 10, "[1]"),
            make_anchor("a2", "ch1", 11, "[2]"),
        ];
        let links = vec![
            make_link("l1", "a1", "n1", "ch1", LinkStatus::Matched),
            make_link("l2", "a2", "n2", "ch1", LinkStatus::Matched),
        ];
        let ctx = ref_materialization_context(&anchors, &links);
        assert_eq!(ctx.matched_link_count, 2);
        assert_eq!(ctx.anchors_by_id.len(), 2);
        assert!(ctx.conflict_anchor_ids.is_empty());
    }

    #[test]
    fn test_ref_materialization_context_conflict() {
        let anchors = vec![make_anchor("a1", "ch1", 10, "[1]")];
        let links = vec![
            make_link("l1", "a1", "n1", "ch1", LinkStatus::Matched),
            make_link("l2", "a1", "n2", "ch1", LinkStatus::Matched), // 同一 anchor 多个 note
        ];
        let ctx = ref_materialization_context(&anchors, &links);
        assert!(ctx.conflict_anchor_ids.contains("a1"));
    }

    #[test]
    fn test_inject_token_once_basic() {
        let anchor = make_anchor("a1", "ch1", 10, "[1]");
        let (result, injected) = inject_token_once("Text [1] more", &anchor, "1", "n1");
        assert!(injected);
        assert!(result.contains("{{NOTE_REF:n1}}"));
    }

    #[test]
    fn test_inject_token_once_not_found() {
        let anchor = make_anchor("a1", "ch1", 10, "[1]");
        let (result, injected) = inject_token_once("No marker here", &anchor, "1", "n1");
        assert!(!injected);
        assert_eq!(result, "No marker here");
    }

    #[test]
    fn test_materialize_refs_for_chapter_basic() {
        let pages = vec![StructuredBodyPage {
            page_no: 10,
            text: "Text [1] and [2]".to_string(),
        }];
        let links = vec![
            make_link("l1", "a1", "n1", "ch1", LinkStatus::Matched),
            make_link("l2", "a2", "n2", "ch1", LinkStatus::Matched),
        ];
        let mut anchors = HashMap::new();
        anchors.insert("a1".to_string(), make_anchor("a1", "ch1", 10, "[1]"));
        anchors.insert("a2".to_string(), make_anchor("a2", "ch1", 10, "[2]"));

        let ctx = RefMaterializationContext {
            anchors_by_id: anchors,
            ..Default::default()
        };

        let (result, summary) = materialize_refs_for_chapter("ch1", &pages, &links, &ctx);
        assert_eq!(summary.injected_link_count, 2);
        assert!(result[0].text.contains("{{NOTE_REF:n1}}"));
        assert!(result[0].text.contains("{{NOTE_REF:n2}}"));
    }
}
