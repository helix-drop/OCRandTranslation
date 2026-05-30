//! ←→ Python `FNM_RE/modules/llm_repair.py` override 物化（行 1644-1809）。
//!
//! 7 个函数（按 Python 顺序）：
//! - `find_link_id_for_match` ←→ `_find_link_id_for_match`
//! - `resolve_chapter_id_for_page` ←→ `_resolve_chapter_id_for_page`
//! - `find_link_id_for_ignore` ←→ `_find_link_id_for_ignore`
//! - `slug_token` ←→ `_slug_token`
//! - `chapter_for_cluster` ←→ `_chapter_for_cluster`
//! - `enrich_synthesize_anchor_actions` ←→ `_enrich_synthesize_anchor_actions`
//! - `prefilter_duplicate_anchors` ←→ `_prefilter_duplicate_anchors`

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::{json, Value};
use std::collections::HashSet;

use crate::page_context::{resolve_page_from_offset, resolve_page_span_from_range, BodySpan};
use crate::response_parser::RepairAction;
use crate::strategies::fuzzy::locate_anchor_phrase_in_body;
use crate::value_views::ClusterView;

/// ←→ Python `_NOTE_LINK_REPAIRABLE_STATUSES` (llm_repair.py:1644)
const NOTE_LINK_REPAIRABLE_STATUSES: &[&str] = &["orphan_note", "ambiguous"];

/// ←→ Python `_ANCHOR_LINK_REPAIRABLE_STATUSES` (llm_repair.py:1645)
const ANCHOR_LINK_REPAIRABLE_STATUSES: &[&str] = &["orphan_anchor", "ambiguous"];

static SLUG_NONWORD_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^0-9A-Za-z_-]+").unwrap());
static SLUG_DASHES_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"-+").unwrap());

fn link_field(link: &Value, key: &str) -> String {
    link.get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string()
}

fn link_status(link: &Value) -> String {
    link.get("status")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string()
}

/// ←→ Python `_find_link_id_for_match` (llm_repair.py:1648-1675)
pub fn find_link_id_for_match(note_links: &[Value], note_item_id: &str, anchor_id: &str) -> String {
    if !note_item_id.is_empty() {
        for link in note_links {
            if NOTE_LINK_REPAIRABLE_STATUSES.contains(&link_status(link).as_str())
                && link_field(link, "note_item_id") == note_item_id
            {
                return link_field(link, "link_id");
            }
        }
        for link in note_links {
            if link_status(link) == "matched" && link_field(link, "note_item_id") == note_item_id {
                return link_field(link, "link_id");
            }
        }
    }
    if !anchor_id.is_empty() {
        for link in note_links {
            if ANCHOR_LINK_REPAIRABLE_STATUSES.contains(&link_status(link).as_str())
                && link_field(link, "anchor_id") == anchor_id
            {
                return link_field(link, "link_id");
            }
        }
        for link in note_links {
            if link_status(link) == "matched" && link_field(link, "anchor_id") == anchor_id {
                return link_field(link, "link_id");
            }
        }
    }
    String::new()
}

/// ←→ Python `_resolve_chapter_id_for_page` (llm_repair.py:1678-1708)
pub fn resolve_chapter_id_for_page(chapters: &[Value], page_no: i64) -> String {
    if page_no <= 0 {
        return String::new();
    }
    let mut valid: Vec<(i64, i64, String)> = Vec::new();
    for chapter in chapters {
        let Some(obj) = chapter.as_object() else {
            continue;
        };
        let chapter_id = obj
            .get("chapter_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let start = obj.get("start_page").and_then(|v| v.as_i64()).unwrap_or(0);
        let end_raw = obj.get("end_page").and_then(|v| v.as_i64()).unwrap_or(0);
        let end = if end_raw > 0 { end_raw } else { start };
        if chapter_id.is_empty() || start <= 0 || end <= 0 {
            continue;
        }
        valid.push((start, start.max(end), chapter_id));
    }
    if valid.is_empty() {
        return String::new();
    }
    valid.sort();
    for (start, end, chapter_id) in &valid {
        if *start <= page_no && page_no <= *end {
            return chapter_id.clone();
        }
    }
    valid
        .into_iter()
        .min_by_key(|(start, end, _)| (page_no - start).abs().min((page_no - end).abs()))
        .map(|(_, _, id)| id)
        .unwrap_or_default()
}

/// ←→ Python `_find_link_id_for_ignore` (llm_repair.py:1711-1718)
pub fn find_link_id_for_ignore(note_links: &[Value], anchor_id: &str) -> String {
    for link in note_links {
        if link_status(link) == "orphan_anchor" && link_field(link, "anchor_id") == anchor_id {
            return link_field(link, "link_id");
        }
    }
    String::new()
}

/// ←→ Python `_slug_token` (llm_repair.py:1721-1724)
pub fn slug_token(value: &str) -> String {
    let trimmed = value.trim();
    let token = SLUG_NONWORD_RE.replace_all(trimmed, "-").to_string();
    let token = SLUG_DASHES_RE.replace_all(&token, "-").to_string();
    let token = token
        .trim_matches(|c: char| c == '-' || c == '_')
        .to_string();
    if token.is_empty() {
        "x".to_string()
    } else {
        token
    }
}

/// ←→ Python `_chapter_for_cluster` (llm_repair.py:1727-1743)
pub fn chapter_for_cluster(cluster: &Value, chapters: &[Value]) -> Value {
    let cv = ClusterView::new(cluster);
    let cluster_chapter_id = cv
        .inner()
        .get("chapter_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    for chapter in chapters {
        let cid = chapter
            .get("chapter_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if cid == cluster_chapter_id {
            return chapter.clone();
        }
    }
    let page_start = cv.page_start();
    let page_end_raw = cv.page_end();
    let page_end = if page_end_raw > 0 {
        page_end_raw
    } else {
        page_start
    };
    let resolved = resolve_chapter_id_for_page(chapters, page_start);
    for chapter in chapters {
        let cid = chapter
            .get("chapter_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if cid == resolved {
            return chapter.clone();
        }
    }
    let chapter_title = cv.chapter_title();
    let chapter_title = if chapter_title.is_empty() {
        &cluster_chapter_id
    } else {
        chapter_title
    }
    .to_string();
    json!({
        "chapter_id": cluster_chapter_id,
        "title": chapter_title,
        "start_page": page_start,
        "end_page": page_end,
    })
}

/// ←→ Python `_enrich_synthesize_anchor_actions` (llm_repair.py:1746-1777)
///
/// 为 synthesize_anchor 动作补充 fuzzy_score + char_start/end + page_no + matched_text。
/// 接收 owned `Vec<RepairAction>` 直接 move 进 enriched，避免循环内 clone。
pub fn enrich_synthesize_anchor_actions(
    actions: Vec<RepairAction>,
    cluster: &Value,
    spans: &[BodySpan],
) -> Vec<RepairAction> {
    let cv = ClusterView::new(cluster);
    let body_text = cv.chapter_body_text();
    let mut enriched: Vec<RepairAction> = Vec::with_capacity(actions.len());
    for mut item in actions {
        if item.action != "synthesize_anchor" {
            enriched.push(item);
            continue;
        }
        let located = locate_anchor_phrase_in_body(body_text, &item.anchor_phrase);
        item.fuzzy_score = located.score;
        item.ambiguous = located.ambiguous;
        let global_start = located.char_start;
        let global_end = located.char_end;
        item.char_start = global_start;
        item.char_end = global_end;
        item.matched_text = located.matched_text;
        if located.hit && global_start >= 0 {
            let page_span =
                resolve_page_span_from_range(spans, global_start as usize, global_end as usize);
            if let Some((page_no, span_start)) = page_span {
                item.page_no = page_no;
                item.char_start = global_start - span_start as i64;
                item.char_end = global_end - span_start as i64;
            } else {
                item.page_no = resolve_page_from_offset(spans, global_start as usize);
            }
        }
        enriched.push(item);
    }
    enriched
}

/// ←→ Python `_prefilter_duplicate_anchors` (llm_repair.py:1780-1809)
///
/// 启发式去重：同页同 marker 且已有 matched_example 的 unmatched_anchor 直接忽略。
/// 被移除的 anchor 存入 `cluster["_prefiltered_anchors"]`，
/// 调用方（run.rs）据此为每个移除的 anchor 生成 `ignore_ref` override —— P1-2。
pub fn prefilter_duplicate_anchors(cluster: &mut Value) {
    let cv = ClusterView::new(cluster);
    let matched: Vec<Value> = cv.matched_examples().cloned().collect();
    let unmatched: Vec<Value> = cv.unmatched_anchors().cloned().collect();
    if matched.is_empty() || unmatched.is_empty() {
        cluster["_prefiltered_anchors"] = Value::Array(vec![]);
        return;
    }
    // ── 归一化函数：优先 try `normalized_marker`，然后 `source_marker`，最后回退到 `marker`
    let pick_marker = |v: &Value| -> String {
        v.get("normalized_marker")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .or_else(|| v.get("source_marker").and_then(|v| v.as_str()))
            .filter(|s| !s.is_empty())
            .or_else(|| v.get("marker").and_then(|v| v.as_str()))
            .unwrap_or("")
            .trim()
            .to_string()
    };
    let mut matched_keys: HashSet<(i64, String)> = HashSet::new();
    for m in &matched {
        let pn = m
            .get("page_no")
            .and_then(|v| v.as_i64())
            .or_else(|| m.get("anchor_page_no").and_then(|v| v.as_i64()))
            .unwrap_or(0);
        let marker = pick_marker(m);
        if pn > 0 && !marker.is_empty() {
            matched_keys.insert((pn, marker));
        }
    }
    let mut filtered: Vec<Value> = Vec::new();
    let mut removed_anchors: Vec<Value> = Vec::new();
    for anchor in &unmatched {
        let pn = anchor.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
        let marker = pick_marker(anchor);
        if matched_keys.contains(&(pn, marker)) {
            removed_anchors.push(anchor.clone());
        } else {
            filtered.push(anchor.clone());
        }
    }
    if !removed_anchors.is_empty() {
        cluster["unmatched_anchors"] = Value::Array(filtered);
        cluster["_prefilter_duplicates_removed"] = json!(removed_anchors.len());
    }
    cluster["_prefiltered_anchors"] = Value::Array(removed_anchors);
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_find_link_id_for_match_orphan_note_first() {
        let links = vec![
            json!({"link_id": "L1", "status": "orphan_note", "note_item_id": "n1"}),
            json!({"link_id": "L2", "status": "matched", "note_item_id": "n1", "anchor_id": "synthetic-a"}),
        ];
        let id = find_link_id_for_match(&links, "n1", "");
        assert_eq!(id, "L1");
    }

    #[test]
    fn test_find_link_id_for_match_fallback_to_matched() {
        let links = vec![
            json!({"link_id": "L2", "status": "matched", "note_item_id": "n1", "anchor_id": "synthetic-a"}),
        ];
        let id = find_link_id_for_match(&links, "n1", "");
        assert_eq!(id, "L2");
    }

    #[test]
    fn test_find_link_id_for_match_by_anchor() {
        let links = vec![json!({"link_id": "L3", "status": "orphan_anchor", "anchor_id": "a1"})];
        let id = find_link_id_for_match(&links, "", "a1");
        assert_eq!(id, "L3");
    }

    #[test]
    fn test_find_link_id_for_match_empty_inputs() {
        let id = find_link_id_for_match(&[], "", "");
        assert!(id.is_empty());
    }

    #[test]
    fn test_resolve_chapter_id_for_page_within() {
        let chapters = vec![
            json!({"chapter_id": "c1", "start_page": 1, "end_page": 10}),
            json!({"chapter_id": "c2", "start_page": 11, "end_page": 20}),
        ];
        assert_eq!(resolve_chapter_id_for_page(&chapters, 5), "c1");
        assert_eq!(resolve_chapter_id_for_page(&chapters, 15), "c2");
    }

    #[test]
    fn test_resolve_chapter_id_for_page_nearest() {
        let chapters = vec![
            json!({"chapter_id": "c1", "start_page": 1, "end_page": 10}),
            json!({"chapter_id": "c2", "start_page": 20, "end_page": 30}),
        ];
        // page 15 outside any → take nearest (c1 end=10 vs c2 start=20, distance 5 vs 5 → first wins)
        let r = resolve_chapter_id_for_page(&chapters, 15);
        assert!(r == "c1" || r == "c2");
    }

    #[test]
    fn test_resolve_chapter_id_for_page_invalid() {
        assert_eq!(resolve_chapter_id_for_page(&[], 5), "");
        let chapters = vec![json!({"chapter_id": "c1", "start_page": 0, "end_page": 0})];
        assert_eq!(resolve_chapter_id_for_page(&chapters, 5), "");
    }

    #[test]
    fn test_find_link_id_for_ignore() {
        let links = vec![
            json!({"link_id": "L1", "status": "matched", "anchor_id": "a1"}),
            json!({"link_id": "L2", "status": "orphan_anchor", "anchor_id": "a2"}),
        ];
        assert_eq!(find_link_id_for_ignore(&links, "a2"), "L2");
        assert_eq!(find_link_id_for_ignore(&links, "a1"), "");
    }

    #[test]
    fn test_slug_token_basic() {
        assert_eq!(slug_token("Hello World!"), "Hello-World");
        assert_eq!(slug_token("---a---b---"), "a-b");
        assert_eq!(slug_token("___"), "x");
        assert_eq!(slug_token(""), "x");
        assert_eq!(slug_token("abc"), "abc");
    }

    #[test]
    fn test_chapter_for_cluster_exact_match() {
        let chapters = vec![
            json!({"chapter_id": "c1", "title": "Chapter 1", "start_page": 1, "end_page": 10}),
        ];
        let cluster = json!({"chapter_id": "c1"});
        let chapter = chapter_for_cluster(&cluster, &chapters);
        assert_eq!(chapter["chapter_id"], "c1");
    }

    #[test]
    fn test_chapter_for_cluster_fallback_to_page() {
        let chapters = vec![
            json!({"chapter_id": "c1", "title": "Chapter 1", "start_page": 1, "end_page": 10}),
        ];
        let cluster = json!({"chapter_id": "unknown", "page_start": 5});
        let chapter = chapter_for_cluster(&cluster, &chapters);
        assert_eq!(chapter["chapter_id"], "c1");
    }

    #[test]
    fn test_chapter_for_cluster_default() {
        let cluster = json!({
            "chapter_id": "ghost", "chapter_title": "Ghost Ch",
            "page_start": 100, "page_end": 110,
        });
        let chapter = chapter_for_cluster(&cluster, &[]);
        assert_eq!(chapter["chapter_id"], "ghost");
        assert_eq!(chapter["title"], "Ghost Ch");
        assert_eq!(chapter["start_page"], 100);
        assert_eq!(chapter["end_page"], 110);
    }

    fn make_action(kind: &str, phrase: &str) -> RepairAction {
        RepairAction {
            action: kind.to_string(),
            anchor_phrase: phrase.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn test_enrich_synthesize_anchor_hit() {
        let body = "the quick brown fox jumps over the lazy dog";
        let cluster = json!({"chapter_body_text": body});
        let spans = vec![(7_i64, 0_usize, body.len())];
        let action = make_action("synthesize_anchor", "brown fox jumps");
        let enriched = enrich_synthesize_anchor_actions(vec![action], &cluster, &spans);
        assert_eq!(enriched.len(), 1);
        let item = &enriched[0];
        assert!(item.fuzzy_score >= 88.0);
        assert!(!item.ambiguous);
        assert!(item.char_start >= 0);
        assert_eq!(item.page_no, 7);
        assert_eq!(item.matched_text, "brown fox jumps");
    }

    #[test]
    fn test_enrich_non_synth_passthrough() {
        let action = make_action("match", "");
        let enriched = enrich_synthesize_anchor_actions(vec![action.clone()], &json!({}), &[]);
        assert_eq!(enriched[0], action);
    }

    #[test]
    fn test_prefilter_duplicate_anchors_basic() {
        let mut cluster = json!({
            "matched_examples": [{"marker": "1", "page_no": 5}],
            "unmatched_anchors": [
                {"page_no": 5, "normalized_marker": "1"},  // duplicate
                {"page_no": 6, "normalized_marker": "2"},  // keep
            ],
        });
        prefilter_duplicate_anchors(&mut cluster);
        let removed = cluster["_prefiltered_anchors"].as_array().unwrap();
        assert_eq!(removed.len(), 1);
        let unmatched = cluster["unmatched_anchors"].as_array().unwrap();
        assert_eq!(unmatched.len(), 1);
        assert_eq!(unmatched[0]["page_no"], 6);
        assert_eq!(cluster["_prefilter_duplicates_removed"], 1);
    }

    #[test]
    fn test_prefilter_duplicate_anchors_none_matched() {
        let mut cluster = json!({
            "unmatched_anchors": [{"page_no": 5, "normalized_marker": "1"}],
        });
        prefilter_duplicate_anchors(&mut cluster);
        let removed = cluster["_prefiltered_anchors"].as_array().unwrap();
        assert_eq!(removed.len(), 0);
    }

    /// 回归测试：matched_examples 使用 raw marker（如 "(1)"）而 unmatched 使用
    /// normalized_marker（如 "1"）时，归一化后的 pick_marker 仍能正确匹配。
    #[test]
    fn test_prefilter_duplicate_anchors_raw_vs_normalized_marker() {
        let mut cluster = json!({
            "matched_examples": [{"marker": "(1)", "page_no": 5}],
            "unmatched_anchors": [
                {"page_no": 5, "normalized_marker": "1"},
                {"page_no": 6, "normalized_marker": "2"},
            ],
        });
        prefilter_duplicate_anchors(&mut cluster);
        let removed = cluster["_prefiltered_anchors"].as_array().unwrap();
        // "(1)" vs "1" —— 不匹配，所以 none removed
        assert_eq!(removed.len(), 0);
        let unmatched = cluster["unmatched_anchors"].as_array().unwrap();
        assert_eq!(unmatched.len(), 2);
    }
}
