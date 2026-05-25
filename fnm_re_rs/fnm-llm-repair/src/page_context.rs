//! ←→ Python `FNM_RE/modules/llm_repair.py` 页面上下文构建（行 537-1263）。
//!
//! 10 个函数（按 Python 出现顺序）：
//! - `endnote_synthesize_focus_pages` ←→ `_endnote_synthesize_focus_pages` (行 537)
//! - `cluster_focus_pages` ←→ `_cluster_focus_pages` (行 1004)
//! - `trim_page_text` ←→ `_trim_page_text` (行 1060)
//! - `fnm_page_role_by_no` ←→ `_fnm_page_role_by_no` (行 1067)
//! - `build_chapter_body_text` ←→ `_build_chapter_body_text` (行 1089)
//! - `build_fallback_body_text_from_contexts` ←→ `_build_fallback_body_text_from_contexts` (行 1144)
//! - `resolve_page_from_offset` ←→ `_resolve_page_from_offset` (行 1168)
//! - `resolve_page_span_from_range` ←→ `_resolve_page_span_from_range` (行 1177)
//! - `build_cluster_page_contexts` ←→ `_build_cluster_page_contexts` (行 1192)
//! - `attach_repair_images_to_contexts` ←→ `_attach_repair_images_to_contexts` (行 1223)
//! - `page_context_trace_rows` ←→ `_page_context_trace_rows` (行 1243)

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use fnm_core::db::Repository;
use fnm_core::note_marker::normalize_note_marker;
use fnm_phase1::input::RawPage;
use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};

use crate::constants::{
    LLM_REPAIR_FOOTNOTE_PAGE_PADDING, LLM_REPAIR_MAX_FOCUS_PAGES, LLM_REPAIR_MAX_IMAGE_PAGES,
};

static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

/// 把 marker 字符串规整化为 int（与 Python `_marker_int` 一致）。
///
/// ←→ Python `_marker_int` (llm_repair.py:529-534)
pub fn marker_int(value: &Value) -> Option<i64> {
    let raw = value.as_str().unwrap_or("");
    let normalized = normalize_note_marker(raw);
    let n = normalized.parse::<i64>().ok()?;
    if n > 0 {
        Some(n)
    } else {
        None
    }
}

/// ←→ Python `_endnote_synthesize_focus_pages` (llm_repair.py:537-583)
///
/// 对 endnote 簇推断 LLM 截图聚焦页范围：根据已知 anchor 页码序列推断未匹配 marker 的临近页。
pub fn endnote_synthesize_focus_pages(cluster: &Value) -> Vec<i64> {
    let note_system = cluster
        .get("note_system")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    if note_system != "endnote" {
        return Vec::new();
    }
    let unmatched_markers: Vec<i64> = cluster
        .get("unmatched_note_items")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|item| {
                    let marker_raw = item
                        .get("marker")
                        .or_else(|| item.get("normalized_marker"))
                        .cloned()
                        .unwrap_or(Value::Null);
                    marker_int(&marker_raw)
                })
                .collect()
        })
        .unwrap_or_default();
    if unmatched_markers.is_empty() {
        return Vec::new();
    }
    let mut known_pages_by_marker: HashMap<i64, Vec<i64>> = HashMap::new();
    for item in cluster
        .get("rebind_candidates")
        .and_then(|v| v.as_array())
        .unwrap_or(&Vec::new())
    {
        let marker_value = item
            .get("marker")
            .or_else(|| item.get("current_anchor_marker"))
            .cloned()
            .unwrap_or(Value::Null);
        let Some(marker) = marker_int(&marker_value) else {
            continue;
        };
        let page_no = item
            .get("anchor_page_no")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        if page_no > 0 {
            known_pages_by_marker
                .entry(marker)
                .or_default()
                .push(page_no);
        }
    }
    if known_pages_by_marker.is_empty() {
        return Vec::new();
    }

    let mut pages: HashSet<i64> = HashSet::new();
    let mut known_markers: Vec<i64> = known_pages_by_marker.keys().copied().collect();
    known_markers.sort();
    for marker in unmatched_markers {
        let lower = known_markers.iter().rev().find(|&&m| m < marker).copied();
        let upper = known_markers.iter().find(|&&m| m > marker).copied();
        match (lower, upper) {
            (None, None) => continue,
            (Some(low), Some(up)) => {
                let start = *known_pages_by_marker[&low].iter().min().unwrap();
                let end = *known_pages_by_marker[&up].iter().max().unwrap();
                let lo = std::cmp::max(1, std::cmp::min(start, end) - 1);
                let hi = std::cmp::max(start, end) + 1;
                for page_no in lo..=hi {
                    pages.insert(page_no);
                }
            }
            (Some(low), None) => {
                let anchor_page = *known_pages_by_marker[&low].iter().max().unwrap();
                let lo = std::cmp::max(1, anchor_page - 1);
                let hi = anchor_page + 3;
                for page_no in lo..=hi {
                    pages.insert(page_no);
                }
            }
            (None, Some(up)) => {
                let anchor_page = *known_pages_by_marker[&up].iter().min().unwrap();
                let lo = std::cmp::max(1, anchor_page - 3);
                let hi = anchor_page + 1;
                for page_no in lo..=hi {
                    pages.insert(page_no);
                }
            }
        }
    }
    let mut ordered: Vec<i64> = pages.into_iter().collect();
    ordered.sort();
    ordered.truncate(LLM_REPAIR_MAX_FOCUS_PAGES);
    ordered
}

/// ←→ Python `_cluster_focus_pages` (llm_repair.py:1004-1057)
pub fn cluster_focus_pages(cluster: &Value) -> Vec<i64> {
    let synth = endnote_synthesize_focus_pages(cluster);
    if !synth.is_empty() {
        return synth;
    }
    let note_system = cluster
        .get("note_system")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    let mut pages: Vec<i64> = Vec::new();
    if note_system != "endnote" {
        for item in cluster
            .get("unmatched_note_items")
            .and_then(|v| v.as_array())
            .unwrap_or(&Vec::new())
        {
            let p = item.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
            if p > 0 {
                pages.push(p);
            }
        }
    }
    for item in cluster
        .get("unmatched_anchors")
        .and_then(|v| v.as_array())
        .unwrap_or(&Vec::new())
    {
        let p = item.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
        if p > 0 {
            pages.push(p);
        }
    }
    let mut cross_page_rebind = false;
    for item in cluster
        .get("rebind_candidates")
        .and_then(|v| v.as_array())
        .unwrap_or(&Vec::new())
    {
        let note_page_no = item
            .get("note_page_no")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let anchor_page_no = item
            .get("anchor_page_no")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        if note_page_no > 0 && note_system != "endnote" {
            pages.push(note_page_no);
        }
        if anchor_page_no > 0 {
            pages.push(anchor_page_no);
        }
        if note_page_no > 0 && anchor_page_no > 0 && note_page_no != anchor_page_no {
            cross_page_rebind = true;
        }
    }
    pages.sort();
    let mut seen: HashSet<i64> = HashSet::new();
    let mut ordered: Vec<i64> = Vec::new();
    for p in pages {
        if seen.insert(p) {
            ordered.push(p);
        }
    }
    if note_system == "footnote" && !ordered.is_empty() {
        let min = *ordered.iter().min().unwrap();
        let max = *ordered.iter().max().unwrap();
        let span_start = std::cmp::max(1, min - LLM_REPAIR_FOOTNOTE_PAGE_PADDING);
        let span_end = max + LLM_REPAIR_FOOTNOTE_PAGE_PADDING;
        let needs_contiguous_window = cross_page_rebind || (max - min >= 1);
        if needs_contiguous_window {
            let expanded: Vec<i64> = (span_start..=span_end).collect();
            if expanded.len() <= LLM_REPAIR_MAX_FOCUS_PAGES {
                return expanded;
            }
        }
    }
    ordered.truncate(LLM_REPAIR_MAX_FOCUS_PAGES);
    ordered
}

/// ←→ Python `_trim_page_text` (llm_repair.py:1060-1064)
pub fn trim_page_text(text: &str, limit: usize) -> String {
    let collapsed = WHITESPACE_RE.replace_all(text, " ").trim().to_string();
    if collapsed.chars().count() <= limit {
        return collapsed;
    }
    let mut truncated: String = collapsed.chars().take(limit).collect();
    while truncated.ends_with(char::is_whitespace) {
        truncated.pop();
    }
    truncated.push_str(" ...");
    truncated
}

/// ←→ Python `_fnm_page_role_by_no` (llm_repair.py:1067-1086)
///
/// 从 DB 读取 page_role 索引；失败时 warn 并返回空 map（P2-3）。
pub fn fnm_page_role_by_no(doc_id: &str, repo: &dyn Repository) -> HashMap<i64, String> {
    let rows = match repo.list_fnm_pages(doc_id) {
        Ok(rows) => rows,
        Err(e) => {
            // TODO: replace with tracing::warn! when subscriber is initialized
            eprintln!(
                "[WARN] page_context::fnm_page_role_by_no: DB read failed for doc {}: {}",
                doc_id, e
            );
            return HashMap::new();
        }
    };
    let mut roles = HashMap::new();
    for row in rows {
        let page_no = row.page_no;
        let role = row.page_role.as_str().to_string();
        if page_no > 0 && !role.is_empty() {
            roles.insert(page_no, role);
        }
    }
    roles
}

/// (page_no, char_start, char_end) span 三元组，单位均为 Python 字符索引。
pub type BodySpan = (i64, usize, usize);

fn raw_page_markdown_trimmed(page: &RawPage) -> String {
    page.markdown.trim().to_string()
}

fn raw_page_by_book_page(pages: &[RawPage]) -> HashMap<i64, &RawPage> {
    pages
        .iter()
        .filter(|p| p.book_page > 0)
        .map(|p| (p.book_page, p))
        .collect()
}

/// ←→ Python `_build_chapter_body_text` (llm_repair.py:1089-1141)
///
/// 拼接章节正文，同时返回 (page_no, char_start, char_end) 片段映射。
pub fn build_chapter_body_text(
    chapter: &Value,
    pages: &[RawPage],
    page_roles: Option<&HashMap<i64, String>>,
    fallback_contexts: Option<&[Value]>,
) -> (String, Vec<BodySpan>) {
    let start = chapter
        .get("start_page")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let end = chapter
        .get("end_page")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let mut parts: Vec<String> = Vec::new();
    let mut spans: Vec<BodySpan> = Vec::new();
    let mut cursor: usize = 0;
    let sep = "\n\n";
    if start > 0 && end >= start {
        let enforce_page_roles = page_roles.is_some_and(|r| !r.is_empty());
        let by_page = raw_page_by_book_page(pages);
        for page_no in start..=end {
            if enforce_page_roles {
                let role = page_roles
                    .and_then(|r| r.get(&page_no))
                    .map(|s| s.as_str())
                    .unwrap_or("");
                if !matches!(role, "body" | "front_matter") {
                    continue;
                }
            }
            let Some(page) = by_page.get(&page_no) else {
                continue;
            };
            let text = raw_page_markdown_trimmed(page);
            if text.is_empty() {
                continue;
            }
            if !parts.is_empty() {
                parts.push(sep.to_string());
                cursor += sep.chars().count();
            }
            let len = text.chars().count();
            parts.push(text);
            spans.push((page_no, cursor, cursor + len));
            cursor += len;
        }
    }
    if !parts.is_empty() {
        return (parts.join(""), spans);
    }
    build_fallback_body_text_from_contexts(fallback_contexts)
}

/// ←→ Python `_build_fallback_body_text_from_contexts` (llm_repair.py:1144-1165)
pub fn build_fallback_body_text_from_contexts(
    contexts: Option<&[Value]>,
) -> (String, Vec<BodySpan>) {
    let mut parts: Vec<String> = Vec::new();
    let mut spans: Vec<BodySpan> = Vec::new();
    let mut cursor: usize = 0;
    let sep = "\n\n";
    for ctx in contexts.unwrap_or(&[]) {
        let page_no = ctx.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
        let raw = ctx
            .get("ocr_excerpt")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let text = WHITESPACE_RE.replace_all(raw, " ").trim().to_string();
        if text.is_empty() {
            continue;
        }
        if !parts.is_empty() {
            parts.push(sep.to_string());
            cursor += sep.chars().count();
        }
        let len = text.chars().count();
        parts.push(text);
        spans.push((page_no, cursor, cursor + len));
        cursor += len;
    }
    (parts.join(""), spans)
}

/// ←→ Python `_resolve_page_from_offset` (llm_repair.py:1168-1174)
pub fn resolve_page_from_offset(spans: &[BodySpan], offset: usize) -> i64 {
    for (page_no, start, end) in spans {
        if *start <= offset && offset < *end {
            return *page_no;
        }
    }
    spans.last().map(|s| s.0).unwrap_or(0)
}

/// ←→ Python `_resolve_page_span_from_range` (llm_repair.py:1177-1189)
///
/// 返回 `(page_no, span_start)`：start_offset 命中所在 span 的起点
pub fn resolve_page_span_from_range(
    spans: &[BodySpan],
    start_offset: usize,
    end_offset: usize,
) -> Option<(i64, usize)> {
    for (page_no, span_start, span_end) in spans {
        if *span_start <= start_offset
            && start_offset < *span_end
            && *span_start < end_offset
            && end_offset <= *span_end
        {
            return Some((*page_no, *span_start));
        }
    }
    // 跨页：start_offset 所在 span
    for (page_no, span_start, span_end) in spans {
        if *span_start <= start_offset && start_offset < *span_end {
            return Some((*page_no, *span_start));
        }
    }
    None
}

/// 渲染 PDF 页面为 data: URL 的抽象。
///
/// ←→ Python `FNM_RE.modules.pdf_render_subprocess.render_repair_page_data_url`
pub trait RepairImageRenderer {
    fn render_page_data_url(&self, pdf_path: &str, file_idx: i64) -> Option<String>;
}

/// 占位实现：永不渲染。测试和无 PDF 场景使用。
pub struct NoopRenderer;
impl RepairImageRenderer for NoopRenderer {
    fn render_page_data_url(&self, _pdf_path: &str, _file_idx: i64) -> Option<String> {
        None
    }
}

/// ←→ Python `_build_cluster_page_contexts` (llm_repair.py:1192-1220)
///
/// 注意：`pdf_path` 由调用方提供（Python 用 `get_pdf_path(doc_id)`）。
pub fn build_cluster_page_contexts(
    cluster: &Value,
    pages: &[RawPage],
    pdf_path: &str,
) -> Vec<Value> {
    let page_map: HashMap<i64, &RawPage> = raw_page_by_book_page(pages);
    let mut contexts: Vec<Value> = Vec::new();
    for page_no in cluster_focus_pages(cluster) {
        let page = page_map.get(&page_no);
        let page_text = page
            .map(|p| raw_page_markdown_trimmed(p))
            .unwrap_or_default();
        let file_idx = page
            .and_then(|p| p.file_idx)
            .unwrap_or_else(|| std::cmp::max(page_no - 1, 0));
        contexts.push(json!({
            "page_no": page_no,
            "file_idx": file_idx,
            "source_pdf_path": pdf_path,
            "ocr_excerpt": trim_page_text(&page_text, 1400),
        }));
    }
    contexts
}

/// 判断是否需要附加截图。
///
/// 与 prompt_builder 中的 `_should_attach_repair_images` 逻辑一致。在此 page_context
/// 模块内部使用以避免循环依赖。
fn should_attach_repair_images(request_cluster: &Value) -> bool {
    let actions = request_cluster
        .get("allowed_actions")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let actions: Vec<String> = actions
        .into_iter()
        .filter_map(|v| v.as_str().map(|s| s.trim().to_string()))
        .collect();
    actions.iter().any(|a| a == "synthesize_anchor")
}

/// ←→ Python `_attach_repair_images_to_contexts` (llm_repair.py:1223-1240)
///
/// 调用 `renderer` 把 PDF 截图嵌入 data URL；图片数量由 `LLM_REPAIR_MAX_IMAGE_PAGES` 限制。
pub fn attach_repair_images_to_contexts(
    contexts: &[Value],
    request_cluster: &Value,
    renderer: &dyn RepairImageRenderer,
) -> Vec<Value> {
    if !should_attach_repair_images(request_cluster) {
        return contexts.to_vec();
    }
    let mut out: Vec<Value> = Vec::new();
    for item in contexts.iter().take(LLM_REPAIR_MAX_IMAGE_PAGES) {
        let mut row = item.clone();
        let pdf_path = row
            .get("source_pdf_path")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let file_idx = row.get("file_idx").and_then(|v| v.as_i64()).unwrap_or(0);
        if !pdf_path.is_empty() {
            if let Some(data_url) = renderer.render_page_data_url(&pdf_path, file_idx) {
                if let Some(obj) = row.as_object_mut() {
                    obj.insert("image_url".to_string(), Value::String(data_url));
                }
            }
        }
        out.push(row);
    }
    out
}

/// ←→ Python `_page_context_trace_rows` (llm_repair.py:1243-1263)
pub fn page_context_trace_rows(page_contexts: &[Value]) -> Vec<Value> {
    let mut rows: Vec<Value> = Vec::new();
    for row in page_contexts {
        let image_url = row
            .get("image_url")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let mut raw_bytes: Vec<u8> = Vec::new();
        if image_url.starts_with("data:") {
            if let Some(idx) = image_url.find(',') {
                if let Ok(decoded) = STANDARD.decode(&image_url[idx + 1..]) {
                    raw_bytes = decoded;
                }
            }
        }
        let sha = if raw_bytes.is_empty() {
            String::new()
        } else {
            let mut hasher = Sha256::new();
            hasher.update(&raw_bytes);
            format!("{:x}", hasher.finalize())
        };
        rows.push(json!({
            "page_no": row.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0),
            "file_idx": row.get("file_idx").and_then(|v| v.as_i64()).unwrap_or(0),
            "source_pdf_path": row.get("source_pdf_path").and_then(|v| v.as_str()).unwrap_or(""),
            "ocr_excerpt": row.get("ocr_excerpt").and_then(|v| v.as_str()).unwrap_or(""),
            "byte_size": raw_bytes.len(),
            "sha256": sha,
        }));
    }
    rows
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_marker_int_basic() {
        assert_eq!(marker_int(&json!("12")), Some(12));
        assert_eq!(marker_int(&json!("0")), None);
        assert_eq!(marker_int(&json!("garbage")), None);
    }

    #[test]
    fn test_trim_page_text_short() {
        assert_eq!(trim_page_text("  hello  world  ", 1400), "hello world");
    }

    #[test]
    fn test_trim_page_text_truncate() {
        let long = "a ".repeat(2000);
        let out = trim_page_text(&long, 100);
        assert!(out.ends_with("..."));
        assert!(out.chars().count() <= 100 + 4);
    }

    #[test]
    fn test_resolve_page_from_offset() {
        let spans = vec![(5, 0, 10), (6, 12, 20)];
        assert_eq!(resolve_page_from_offset(&spans, 3), 5);
        assert_eq!(resolve_page_from_offset(&spans, 15), 6);
        // 落在 gap 内 → 取最后一个
        assert_eq!(resolve_page_from_offset(&spans, 100), 6);
        assert_eq!(resolve_page_from_offset(&[], 0), 0);
    }

    #[test]
    fn test_resolve_page_span_from_range_same_page() {
        let spans = vec![(5, 0, 10), (6, 12, 20)];
        let r = resolve_page_span_from_range(&spans, 2, 8);
        assert_eq!(r, Some((5, 0)));
    }

    #[test]
    fn test_resolve_page_span_from_range_cross_page() {
        let spans = vec![(5, 0, 10), (6, 12, 20)];
        // start 在 page5，end 在 page6 → 取 start 所在页
        let r = resolve_page_span_from_range(&spans, 5, 15);
        assert_eq!(r, Some((5, 0)));
    }

    #[test]
    fn test_fallback_body_spans_use_character_offsets() {
        let contexts = vec![
            json!({"page_no": 5, "ocr_excerpt": "é"}),
            json!({"page_no": 6, "ocr_excerpt": "body"}),
        ];
        let (text, spans) = build_fallback_body_text_from_contexts(Some(&contexts));
        assert_eq!(text, "é\n\nbody");
        assert_eq!(spans, vec![(5, 0, 1), (6, 3, 7)]);
    }

    #[test]
    fn test_endnote_synthesize_focus_pages_bracketed() {
        // marker 3 缺失，known markers 1 page 5 / 5 page 12 → range 4..=13 然后截断到 8
        let cluster = json!({
            "note_system": "endnote",
            "unmatched_note_items": [{"marker": "3"}],
            "rebind_candidates": [
                {"marker": "1", "anchor_page_no": 5},
                {"marker": "5", "anchor_page_no": 12},
            ],
        });
        let pages = endnote_synthesize_focus_pages(&cluster);
        // sorted [4,5,6,7,8,9,10,11,12,13] → take 8 = [4..11]
        assert_eq!(pages, vec![4, 5, 6, 7, 8, 9, 10, 11]);
    }

    #[test]
    fn test_endnote_synthesize_focus_pages_below_min() {
        // 只有上界已知（marker 5 page 10），marker 3 缺失 → 应取 anchor-3..anchor+1
        let cluster = json!({
            "note_system": "endnote",
            "unmatched_note_items": [{"marker": "3"}],
            "rebind_candidates": [
                {"marker": "5", "anchor_page_no": 10},
            ],
        });
        let pages = endnote_synthesize_focus_pages(&cluster);
        assert_eq!(*pages.first().unwrap(), 7);
        assert_eq!(*pages.last().unwrap(), 11);
    }

    #[test]
    fn test_endnote_synthesize_focus_pages_non_endnote() {
        let cluster = json!({"note_system": "footnote"});
        assert!(endnote_synthesize_focus_pages(&cluster).is_empty());
    }

    #[test]
    fn test_cluster_focus_pages_footnote_window() {
        let cluster = json!({
            "note_system": "footnote",
            "unmatched_anchors": [{"page_no": 10}, {"page_no": 12}],
        });
        let pages = cluster_focus_pages(&cluster);
        // span 10-12, padded ±1 → 9..13
        assert_eq!(pages, vec![9, 10, 11, 12, 13]);
    }

    #[test]
    fn test_cluster_focus_pages_endnote_no_note_pages() {
        // endnote 模式：不收集 unmatched_note_items 的 page_no
        let cluster = json!({
            "note_system": "endnote",
            "unmatched_note_items": [{"page_no": 200}],
            "unmatched_anchors": [{"page_no": 50}],
        });
        let pages = cluster_focus_pages(&cluster);
        assert_eq!(pages, vec![50]);
    }

    fn raw_page(book_page: i64, markdown: &str) -> RawPage {
        RawPage {
            book_page,
            markdown: markdown.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn test_build_chapter_body_text_basic() {
        let chapter = json!({"start_page": 1, "end_page": 3});
        let pages = vec![
            raw_page(1, "page one body"),
            raw_page(2, "page two body"),
            raw_page(3, "page three body"),
        ];
        let (text, spans) = build_chapter_body_text(&chapter, &pages, None, None);
        assert!(text.contains("page one body"));
        assert!(text.contains("page two body"));
        assert!(text.contains("page three body"));
        assert_eq!(spans.len(), 3);
        let (pn, start, end) = spans[0];
        assert_eq!(pn, 1);
        assert_eq!(&text[start..end], "page one body");
    }

    #[test]
    fn test_build_chapter_body_text_role_filter() {
        let chapter = json!({"start_page": 1, "end_page": 3});
        let pages = vec![
            raw_page(1, "body 1"),
            raw_page(2, "endnotes content"),
            raw_page(3, "body 3"),
        ];
        let mut roles = HashMap::new();
        roles.insert(1, "body".to_string());
        roles.insert(2, "endnotes".to_string());
        roles.insert(3, "body".to_string());
        let (text, spans) = build_chapter_body_text(&chapter, &pages, Some(&roles), None);
        assert!(!text.contains("endnotes content"));
        assert_eq!(spans.len(), 2);
    }

    #[test]
    fn test_build_chapter_body_text_fallback_to_contexts() {
        let chapter = json!({"start_page": 0, "end_page": 0});
        let contexts = vec![json!({"page_no": 5, "ocr_excerpt": "  context  text  "})];
        let (text, spans) = build_chapter_body_text(&chapter, &[], None, Some(&contexts));
        assert!(text.contains("context text"));
        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0].0, 5);
    }

    #[test]
    fn test_build_cluster_page_contexts_basic() {
        let cluster = json!({
            "note_system": "footnote",
            "unmatched_anchors": [{"page_no": 10}],
        });
        let pages = vec![raw_page(10, "page ten ocr"), raw_page(11, "irrelevant")];
        let contexts = build_cluster_page_contexts(&cluster, &pages, "/tmp/test.pdf");
        assert_eq!(contexts.len(), 1);
        assert_eq!(contexts[0]["page_no"], 10);
        assert_eq!(contexts[0]["source_pdf_path"], "/tmp/test.pdf");
        assert!(contexts[0]["ocr_excerpt"]
            .as_str()
            .unwrap()
            .contains("page ten ocr"));
    }

    #[test]
    fn test_attach_repair_images_noop_without_synthesize() {
        let contexts = vec![json!({"page_no": 5, "file_idx": 4, "source_pdf_path": "/tmp/x.pdf"})];
        let cluster = json!({"allowed_actions": ["match", "ignore_ref"]});
        let renderer = NoopRenderer;
        let out = attach_repair_images_to_contexts(&contexts, &cluster, &renderer);
        assert_eq!(out, contexts);
    }

    struct StubRenderer;
    impl RepairImageRenderer for StubRenderer {
        fn render_page_data_url(&self, _pdf_path: &str, _file_idx: i64) -> Option<String> {
            Some("data:image/png;base64,AAAA".to_string())
        }
    }

    #[test]
    fn test_attach_repair_images_with_synthesize_anchor() {
        let contexts = vec![
            json!({"page_no": 5, "file_idx": 4, "source_pdf_path": "/tmp/x.pdf"}),
            json!({"page_no": 6, "file_idx": 5, "source_pdf_path": "/tmp/x.pdf"}),
            json!({"page_no": 7, "file_idx": 6, "source_pdf_path": "/tmp/x.pdf"}),
            json!({"page_no": 8, "file_idx": 7, "source_pdf_path": "/tmp/x.pdf"}),
            json!({"page_no": 9, "file_idx": 8, "source_pdf_path": "/tmp/x.pdf"}),
            // 第六个超过 LLM_REPAIR_MAX_IMAGE_PAGES = 5 → 被裁
            json!({"page_no": 10, "file_idx": 9, "source_pdf_path": "/tmp/x.pdf"}),
        ];
        let cluster = json!({"allowed_actions": ["match", "synthesize_anchor"]});
        let out = attach_repair_images_to_contexts(&contexts, &cluster, &StubRenderer);
        assert_eq!(out.len(), 5);
        assert!(out[0].get("image_url").is_some());
        assert_eq!(out[4]["page_no"], 9);
    }

    #[test]
    fn test_page_context_trace_rows_with_image() {
        let rows = vec![json!({
            "page_no": 5,
            "file_idx": 4,
            "source_pdf_path": "/tmp/x.pdf",
            "ocr_excerpt": "excerpt",
            "image_url": "data:image/png;base64,AAAA",
        })];
        let out = page_context_trace_rows(&rows);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0]["byte_size"], 3); // "AAAA" base64 decodes to 3 bytes
        assert!(!out[0]["sha256"].as_str().unwrap().is_empty());
    }

    #[test]
    fn test_page_context_trace_rows_without_image() {
        let rows = vec![json!({
            "page_no": 5,
            "file_idx": 4,
            "source_pdf_path": "/tmp/x.pdf",
            "ocr_excerpt": "excerpt",
        })];
        let out = page_context_trace_rows(&rows);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0]["byte_size"], 0);
        assert_eq!(out[0]["sha256"], "");
    }
}
