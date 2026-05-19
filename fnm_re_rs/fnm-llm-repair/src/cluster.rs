//! ←→ Python `FNM_RE/modules/llm_repair.py` cluster 构建（行 197-415）。
//!
//! 4 个函数：
//! - `chapter_title_by_id` ←→ `_chapter_title_by_id`
//! - `index_by_key` ←→ `_index_by_key`
//! - `cluster_page_range` ←→ `_cluster_page_range`
//! - `build_unresolved_clusters` ←→ `build_unresolved_clusters`
//!
//! 数据结构与 Python dict 保持字段对齐——以 `serde_json::Value` 持有 cluster
//! 让上下游不重新定义 schema、便于 trace JSON 直出。

use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

/// ←→ Python `_chapter_title_by_id` (llm_repair.py:197-201)
pub fn chapter_title_by_id(chapters: &[Value]) -> HashMap<String, String> {
    chapters
        .iter()
        .map(|chapter| {
            let id = chapter
                .get("chapter_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let title = chapter
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string();
            (id, title)
        })
        .collect()
}

/// ←→ Python `_index_by_key` (llm_repair.py:204-209)
///
/// 按指定字段把 items 索引成 `key -> dict` 映射（key 为空时跳过）。
///
/// # 关于 clone
///
/// 返回 owned `HashMap<String, Value>` 而非 `HashMap<String, &Value>`，与 Python
/// 端 `{... : dict(item)}` 的 dict copy 语义对齐：下游 `build_unresolved_clusters`
/// 多处 push 索引出的 record 进 cluster 的 JSON array，需要 owned 值。改借用版本
/// 仅省一次构造时 clone，但会传染 lifetime 标注到 `build_unresolved_clusters`、
/// `run_llm_repair` 与所有 spec 测试，得不偿失。
pub fn index_by_key(items: &[Value], key: &str) -> HashMap<String, Value> {
    items
        .iter()
        .filter_map(|item| {
            let k = item.get(key).and_then(|v| v.as_str()).unwrap_or("").trim();
            if k.is_empty() {
                None
            } else {
                Some((k.to_string(), item.clone()))
            }
        })
        .collect()
}

/// ←→ Python `_cluster_page_range` (llm_repair.py:212-230)
pub fn cluster_page_range(cluster: &Value) -> (Option<i64>, Option<i64>) {
    let mut pages: Vec<i64> = Vec::new();
    for note_item in cluster
        .get("unmatched_note_items")
        .and_then(|v| v.as_array())
        .unwrap_or(&Vec::new())
    {
        let value = page_no_of(note_item);
        if value > 0 {
            pages.push(value);
        }
    }
    for anchor in cluster
        .get("unmatched_anchors")
        .and_then(|v| v.as_array())
        .unwrap_or(&Vec::new())
    {
        let value = page_no_of(anchor);
        if value > 0 {
            pages.push(value);
        }
    }
    if pages.is_empty() {
        return (None, None);
    }
    let min = *pages.iter().min().unwrap();
    let max = *pages.iter().max().unwrap();
    (Some(min), Some(max))
}

fn page_no_of(item: &Value) -> i64 {
    match item.get("page_no") {
        Some(v) => v
            .as_i64()
            .or_else(|| v.as_str().and_then(|s| s.parse::<i64>().ok()))
            .unwrap_or(0),
        None => 0,
    }
}

fn str_field(value: &Value, key: &str) -> String {
    value
        .get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string()
}

fn marker_field(value: &Value) -> String {
    value
        .get("marker")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string()
}

/// 判断 anchor 是否合成（synthetic）：
/// - anchor.synthetic == true，或 anchor_id 以 "synthetic-" 开头
fn anchor_is_synthetic(anchor: Option<&Value>, anchor_id: &str) -> bool {
    let flag = anchor
        .and_then(|v| v.get("synthetic"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    flag || anchor_id.starts_with("synthetic-")
}

/// ←→ Python `build_unresolved_clusters` (llm_repair.py:233-415)
///
/// 按 (chapter_id, region_id, note_system) 聚类 note_links，生成 unresolved cluster 列表。
///
/// 每个 cluster 含字段：
/// - cluster_id, chapter_id, chapter_title, region_id, note_system
/// - matched_examples（最多 3 个）, unmatched_note_items, unmatched_anchors
/// - rebind_candidates（最多 8 个）
/// - page_start, page_end
///
/// 排序：(unmatched 总数倒序, page_start, cluster_id)
pub fn build_unresolved_clusters(
    chapters: &[Value],
    note_items: &[Value],
    body_anchors: &[Value],
    note_links: &[Value],
) -> Vec<Value> {
    let chapter_titles = chapter_title_by_id(chapters);
    let note_items_by_id = index_by_key(note_items, "note_item_id");
    let anchors_by_id = index_by_key(body_anchors, "anchor_id");

    // (chapter_id, region_id, note_system) -> cluster value
    let mut grouped: HashMap<(String, String, String), Value> = HashMap::new();
    let mut group_order: Vec<(String, String, String)> = Vec::new();

    for link in note_links {
        let note_system = str_field(link, "note_kind");
        let status = str_field(link, "status");
        if !matches!(note_system.as_str(), "endnote" | "footnote") {
            continue;
        }
        if !matches!(
            status.as_str(),
            "matched" | "orphan_note" | "orphan_anchor" | "ambiguous"
        ) {
            continue;
        }
        let chapter_id = str_field(link, "chapter_id");
        let anchor_id_for_key = str_field(link, "anchor_id");
        let anchor_for_key = anchors_by_id.get(&anchor_id_for_key);
        let matched_synthetic_for_key =
            status == "matched" && anchor_is_synthetic(anchor_for_key, &anchor_id_for_key);
        let region_id = if matched_synthetic_for_key {
            chapter_id.clone()
        } else {
            let r = str_field(link, "region_id");
            if r.is_empty() {
                chapter_id.clone()
            } else {
                r
            }
        };
        let key = (chapter_id.clone(), region_id.clone(), note_system.clone());

        let cluster = grouped.entry(key.clone()).or_insert_with(|| {
            group_order.push(key.clone());
            json!({
                "cluster_id": format!("{}:{}:{}", chapter_id, region_id, note_system),
                "chapter_id": chapter_id,
                "chapter_title": chapter_titles.get(&chapter_id).cloned().unwrap_or_else(|| chapter_id.clone()),
                "region_id": region_id,
                "note_system": note_system,
                "matched_examples": [],
                "unmatched_note_items": [],
                "unmatched_anchors": [],
            })
        });

        if status == "matched" {
            let note_item_id = str_field(link, "note_item_id");
            let anchor_id = str_field(link, "anchor_id");
            let note_item = note_items_by_id.get(&note_item_id);
            let anchor = anchors_by_id.get(&anchor_id);
            let current_anchor_is_synthetic = anchor_is_synthetic(anchor, &anchor_id);
            if let Some(note_item) = note_item {
                if current_anchor_is_synthetic {
                    cluster["unmatched_note_items"]
                        .as_array_mut()
                        .unwrap()
                        .push(note_item.clone());
                    let rebind = json!({
                        "link_id": str_field(link, "link_id"),
                        "note_item_id": str_field(note_item, "note_item_id"),
                        "current_anchor_id": anchor_id.clone(),
                        "marker": pick_marker(note_item, link),
                        "note_page_no": page_no_of(note_item),
                        "anchor_page_no": anchor.map(page_no_of).unwrap_or(0),
                        "current_anchor_marker": anchor
                            .map(pick_anchor_marker)
                            .unwrap_or_default(),
                        "note_excerpt": str_field(note_item, "source_text"),
                        "anchor_excerpt": anchor.map(|a| str_field(a, "source_text")).unwrap_or_default(),
                        "current_anchor_synthetic": true,
                    });
                    let arr = cluster
                        .as_object_mut()
                        .unwrap()
                        .entry("rebind_candidates".to_string())
                        .or_insert_with(|| json!([]));
                    arr.as_array_mut().unwrap().push(rebind);
                    continue;
                }
                if let Some(anchor) = anchor {
                    cluster["matched_examples"]
                        .as_array_mut()
                        .unwrap()
                        .push(json!({
                            "link_id": str_field(link, "link_id"),
                            "note_item_id": str_field(note_item, "note_item_id"),
                            "anchor_id": str_field(anchor, "anchor_id"),
                            "marker": pick_marker(note_item, link),
                            "note_excerpt": str_field(note_item, "source_text"),
                            "anchor_excerpt": str_field(anchor, "source_text"),
                        }));
                }
            }
            continue;
        }

        if status == "orphan_note" || status == "ambiguous" {
            let nid = str_field(link, "note_item_id");
            if let Some(note_item) = note_items_by_id.get(&nid) {
                cluster["unmatched_note_items"]
                    .as_array_mut()
                    .unwrap()
                    .push(note_item.clone());
            }
        }
        if status == "orphan_anchor" || status == "ambiguous" {
            let aid = str_field(link, "anchor_id");
            if let Some(anchor) = anchors_by_id.get(&aid) {
                cluster["unmatched_anchors"]
                    .as_array_mut()
                    .unwrap()
                    .push(anchor.clone());
            }
        }
    }

    // 后处理：去重 + 收集 cluster_pages + 扩充 rebind_candidates + 收成最终列表
    let mut clusters: Vec<Value> = Vec::new();
    for key in group_order.iter() {
        let mut cluster = grouped.remove(key).unwrap();

        // matched_examples 上限 3
        if let Some(arr) = cluster
            .get_mut("matched_examples")
            .and_then(|v| v.as_array_mut())
        {
            arr.truncate(3);
        }

        // unmatched_note_items 按 note_item_id 去重
        let unmatched_notes = cluster
            .get("unmatched_note_items")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let mut seen_notes: HashSet<String> = HashSet::new();
        let dedup_notes: Vec<Value> = unmatched_notes
            .into_iter()
            .filter(|item| {
                let id = str_field(item, "note_item_id");
                if id.is_empty() {
                    return false;
                }
                seen_notes.insert(id)
            })
            .collect();
        cluster["unmatched_note_items"] = Value::Array(dedup_notes);

        // unmatched_anchors 按 anchor_id 去重
        let unmatched_anchors = cluster
            .get("unmatched_anchors")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let mut seen_anchors: HashSet<String> = HashSet::new();
        let dedup_anchors: Vec<Value> = unmatched_anchors
            .into_iter()
            .filter(|item| {
                let id = str_field(item, "anchor_id");
                if id.is_empty() {
                    return false;
                }
                seen_anchors.insert(id)
            })
            .collect();
        cluster["unmatched_anchors"] = Value::Array(dedup_anchors);

        // 空簇丢弃
        if cluster["unmatched_note_items"]
            .as_array()
            .is_none_or(|a| a.is_empty())
            && cluster["unmatched_anchors"]
                .as_array()
                .is_none_or(|a| a.is_empty())
        {
            continue;
        }

        let (page_start, page_end) = cluster_page_range(&cluster);
        cluster["page_start"] = json!(page_start);
        cluster["page_end"] = json!(page_end);

        // cluster_pages 用于后续 rebind 过滤
        let mut cluster_pages: HashSet<i64> = HashSet::new();
        for item in cluster["unmatched_note_items"]
            .as_array()
            .unwrap_or(&Vec::new())
        {
            let p = page_no_of(item);
            if p > 0 {
                cluster_pages.insert(p);
            }
        }
        for item in cluster["unmatched_anchors"]
            .as_array()
            .unwrap_or(&Vec::new())
        {
            let p = page_no_of(item);
            if p > 0 {
                cluster_pages.insert(p);
            }
        }

        // 扩充 rebind_candidates：扫所有 matched link 找跨页/合成绑定
        let mut rebind_candidates = cluster
            .get("rebind_candidates")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let mut seen_note_item_ids: HashSet<String> = rebind_candidates
            .iter()
            .map(|r| str_field(r, "note_item_id"))
            .filter(|s| !s.is_empty())
            .collect();

        for link in note_links {
            if str_field(link, "status") != "matched" {
                continue;
            }
            if str_field(link, "chapter_id") != str_field(&cluster, "chapter_id") {
                continue;
            }
            if str_field(link, "note_kind") != str_field(&cluster, "note_system") {
                continue;
            }
            let note_item_id = str_field(link, "note_item_id");
            let anchor_id = str_field(link, "anchor_id");
            let note_item = note_items_by_id.get(&note_item_id);
            let anchor = anchors_by_id.get(&anchor_id);
            let (Some(note_item), Some(anchor)) = (note_item, anchor) else {
                continue;
            };
            let note_page_no = page_no_of(note_item);
            let anchor_page_no = page_no_of(anchor);
            if !cluster_pages.is_empty()
                && !cluster_pages.contains(&note_page_no)
                && !cluster_pages.contains(&anchor_page_no)
            {
                continue;
            }
            let current_anchor_is_synthetic = anchor_is_synthetic(Some(anchor), &anchor_id);
            if !(current_anchor_is_synthetic || note_page_no != anchor_page_no) {
                continue;
            }
            let note_item_id_clean = str_field(note_item, "note_item_id");
            if note_item_id_clean.is_empty() || seen_note_item_ids.contains(&note_item_id_clean) {
                continue;
            }
            seen_note_item_ids.insert(note_item_id_clean.clone());
            rebind_candidates.push(json!({
                "link_id": str_field(link, "link_id"),
                "note_item_id": note_item_id_clean,
                "current_anchor_id": anchor_id,
                "marker": pick_marker(note_item, link),
                "note_page_no": note_page_no,
                "anchor_page_no": anchor_page_no,
                "current_anchor_marker": pick_anchor_marker(anchor),
                "note_excerpt": str_field(note_item, "source_text"),
                "anchor_excerpt": str_field(anchor, "source_text"),
                "current_anchor_synthetic": current_anchor_is_synthetic,
            }));
        }
        if !rebind_candidates.is_empty() {
            rebind_candidates.truncate(8);
            cluster["rebind_candidates"] = Value::Array(rebind_candidates);
        }

        clusters.push(cluster);
    }

    // 排序：unmatched 总数倒序、page_start 升序、cluster_id 字典序
    clusters.sort_by(|a, b| {
        let a_count = a["unmatched_note_items"].as_array().map_or(0, |x| x.len())
            + a["unmatched_anchors"].as_array().map_or(0, |x| x.len());
        let b_count = b["unmatched_note_items"].as_array().map_or(0, |x| x.len())
            + b["unmatched_anchors"].as_array().map_or(0, |x| x.len());
        b_count.cmp(&a_count).then_with(|| {
            let a_page = a["page_start"].as_i64().unwrap_or(0);
            let b_page = b["page_start"].as_i64().unwrap_or(0);
            a_page.cmp(&b_page).then_with(|| {
                let a_id = str_field(a, "cluster_id");
                let b_id = str_field(b, "cluster_id");
                a_id.cmp(&b_id)
            })
        })
    });

    clusters
}

fn pick_marker(note_item: &Value, link: &Value) -> String {
    let from_note = marker_field(note_item);
    if !from_note.is_empty() {
        return from_note;
    }
    marker_field(link)
}

fn pick_anchor_marker(anchor: &Value) -> String {
    let normalized = str_field(anchor, "normalized_marker");
    if !normalized.is_empty() {
        return normalized;
    }
    str_field(anchor, "source_marker")
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn ch(id: &str, title: &str) -> Value {
        json!({"chapter_id": id, "title": title})
    }
    fn note(id: &str, chapter_id: &str, page_no: i64, marker: &str, text: &str) -> Value {
        json!({
            "note_item_id": id,
            "chapter_id": chapter_id,
            "page_no": page_no,
            "marker": marker,
            "source_text": text,
        })
    }
    fn anchor(id: &str, page_no: i64, marker: &str, text: &str, synthetic: bool) -> Value {
        json!({
            "anchor_id": id,
            "page_no": page_no,
            "normalized_marker": marker,
            "source_text": text,
            "synthetic": synthetic,
        })
    }
    fn link(
        link_id: &str,
        chapter_id: &str,
        region_id: &str,
        note_kind: &str,
        status: &str,
        note_item_id: &str,
        anchor_id: &str,
    ) -> Value {
        json!({
            "link_id": link_id,
            "chapter_id": chapter_id,
            "region_id": region_id,
            "note_kind": note_kind,
            "status": status,
            "note_item_id": note_item_id,
            "anchor_id": anchor_id,
        })
    }

    #[test]
    fn test_chapter_title_by_id() {
        let chapters = vec![ch("c1", "Chapter One"), ch("c2", "  Two  ")];
        let map = chapter_title_by_id(&chapters);
        assert_eq!(map["c1"], "Chapter One");
        assert_eq!(map["c2"], "Two");
    }

    #[test]
    fn test_index_by_key_skips_empty() {
        let items = vec![note("n1", "c1", 5, "1", ""), note("", "c1", 6, "2", "")];
        let map = index_by_key(&items, "note_item_id");
        assert!(map.contains_key("n1"));
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn test_cluster_page_range() {
        let cluster = json!({
            "unmatched_note_items": [{"page_no": 12}, {"page_no": 5}],
            "unmatched_anchors": [{"page_no": 8}],
        });
        let (s, e) = cluster_page_range(&cluster);
        assert_eq!(s, Some(5));
        assert_eq!(e, Some(12));
    }

    #[test]
    fn test_cluster_page_range_empty() {
        let cluster = json!({});
        let (s, e) = cluster_page_range(&cluster);
        assert!(s.is_none() && e.is_none());
    }

    #[test]
    fn test_build_unresolved_clusters_orphan_pair() {
        let chapters = vec![ch("c1", "Ch1")];
        let notes = vec![note("n1", "c1", 10, "1", "note text")];
        let anchors = vec![anchor("a1", 5, "2", "anchor ctx", false)];
        let links = vec![
            link("L1", "c1", "r1", "endnote", "orphan_note", "n1", ""),
            link("L2", "c1", "r1", "endnote", "orphan_anchor", "", "a1"),
        ];
        let clusters = build_unresolved_clusters(&chapters, &notes, &anchors, &links);
        assert_eq!(clusters.len(), 1);
        let c = &clusters[0];
        assert_eq!(c["note_system"], "endnote");
        assert_eq!(c["unmatched_note_items"].as_array().unwrap().len(), 1);
        assert_eq!(c["unmatched_anchors"].as_array().unwrap().len(), 1);
        assert_eq!(c["page_start"], 5);
        assert_eq!(c["page_end"], 10);
    }

    #[test]
    fn test_build_unresolved_clusters_synthetic_matched_promoted() {
        // 已 matched 但 anchor 是合成的 → 应进入 unmatched_note_items + rebind_candidates
        let chapters = vec![ch("c1", "Ch1")];
        let notes = vec![note("n1", "c1", 7, "1", "note")];
        let anchors = vec![anchor("synthetic-1", 7, "1", "", true)];
        let links = vec![link(
            "L1",
            "c1",
            "r1",
            "endnote",
            "matched",
            "n1",
            "synthetic-1",
        )];
        let clusters = build_unresolved_clusters(&chapters, &notes, &anchors, &links);
        assert_eq!(clusters.len(), 1);
        let c = &clusters[0];
        assert_eq!(c["unmatched_note_items"].as_array().unwrap().len(), 1);
        let rebinds = c["rebind_candidates"].as_array().unwrap();
        assert_eq!(rebinds.len(), 1);
        assert!(rebinds[0]["current_anchor_synthetic"].as_bool().unwrap());
        // region_id 应被改写为 chapter_id（synthetic_for_key 分支）
        assert_eq!(c["region_id"], "c1");
    }

    #[test]
    fn test_build_unresolved_clusters_dedup_same_id() {
        let chapters = vec![ch("c1", "Ch1")];
        let notes = vec![note("n1", "c1", 5, "1", "")];
        let anchors: Vec<Value> = vec![];
        let links = vec![
            link("L1", "c1", "r1", "endnote", "orphan_note", "n1", ""),
            link("L2", "c1", "r1", "endnote", "orphan_note", "n1", ""),
        ];
        let clusters = build_unresolved_clusters(&chapters, &notes, &anchors, &links);
        assert_eq!(clusters.len(), 1);
        assert_eq!(
            clusters[0]["unmatched_note_items"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
    }

    #[test]
    fn test_build_unresolved_clusters_skip_empty() {
        // ambiguous link 没绑 note_item / anchor → 整 cluster 为空 → 丢弃
        let chapters = vec![ch("c1", "Ch1")];
        let links = vec![link("L1", "c1", "r1", "endnote", "ambiguous", "", "")];
        let clusters = build_unresolved_clusters(&chapters, &[], &[], &links);
        assert!(clusters.is_empty());
    }

    #[test]
    fn test_build_unresolved_clusters_sort_by_count_desc() {
        let chapters = vec![ch("c1", "Ch1"), ch("c2", "Ch2")];
        let notes = vec![
            note("n1", "c1", 5, "1", ""),
            note("n2", "c1", 6, "2", ""),
            note("n3", "c2", 5, "1", ""),
        ];
        let links = vec![
            link("L1", "c1", "r1", "endnote", "orphan_note", "n1", ""),
            link("L2", "c1", "r1", "endnote", "orphan_note", "n2", ""),
            link("L3", "c2", "r2", "endnote", "orphan_note", "n3", ""),
        ];
        let clusters = build_unresolved_clusters(&chapters, &notes, &[], &links);
        assert_eq!(clusters.len(), 2);
        // c1 has 2 unmatched, c2 has 1 → c1 first
        assert_eq!(clusters[0]["chapter_id"], "c1");
        assert_eq!(clusters[1]["chapter_id"], "c2");
    }
}
