//! ←→ FNM_RE/stages/chapter_anchor_alignment.py
//!
//! Needleman-Wunsch 全局序列对齐：body anchor 标记序列 vs 尾注条目标记序列。

use fnm_core::records::{BodyAnchorRecord, ChapterAnchorAlignmentRecord, ChapterEndnoteRecord};
use serde_json::Value;
use std::collections::HashMap;

// ── 公开 API ────────────────────────────────────────────────────

/// 构建 chapter anchor alignment 记录。
///
/// ←→ Python `build_chapter_anchor_alignment`
pub fn build_chapter_anchor_alignment(
    body_anchors: &[BodyAnchorRecord],
    paragraph_endnotes: &[ChapterEndnoteRecord],
    doc_id: &str,
) -> (Vec<ChapterAnchorAlignmentRecord>, AlignmentSummary) {
    let body_by_chapter = body_markers_by_chapter(body_anchors);
    let endnote_by_chapter = endnote_markers_by_chapter(paragraph_endnotes);

    let mut all_chapter_ids: Vec<String> = body_by_chapter
        .keys()
        .chain(endnote_by_chapter.keys())
        .cloned()
        .collect();
    all_chapter_ids.sort();
    all_chapter_ids.dedup();

    let mut records: Vec<ChapterAnchorAlignmentRecord> = Vec::new();
    let mut chapter_status_map: HashMap<String, ChapterStatus> = HashMap::new();

    for cid in &all_chapter_ids {
        let bm = body_by_chapter
            .get(cid)
            .map(|v| v.as_slice())
            .unwrap_or(&[]);
        let em = endnote_by_chapter
            .get(cid)
            .map(|v| v.as_slice())
            .unwrap_or(&[]);

        let (alignment_status, mismatch) = per_chapter_alignment(bm, em);

        records.push(ChapterAnchorAlignmentRecord {
            doc_id: doc_id.to_string(),
            chapter_id: cid.clone(),
            alignment_status: alignment_status.to_string(),
            body_anchor_count: bm.len() as i64,
            endnote_count: em.len() as i64,
            mismatch: mismatch.map(Value::Object),
        });

        chapter_status_map.insert(
            cid.clone(),
            ChapterStatus {
                alignment_status: alignment_status.to_string(),
                body_anchor_count: bm.len(),
                endnote_count: em.len(),
            },
        );
    }

    let total = records.len();
    let clean = records
        .iter()
        .filter(|r| r.alignment_status == "clean")
        .count();
    let mismatches_count = records
        .iter()
        .filter(|r| r.alignment_status == "mismatches")
        .count();
    let misaligned_count = records
        .iter()
        .filter(|r| r.alignment_status == "misaligned")
        .count();
    let total_body: i64 = records.iter().map(|r| r.body_anchor_count).sum();
    let total_endnote: i64 = records.iter().map(|r| r.endnote_count).sum();

    let summary = AlignmentSummary {
        total_chapters: total,
        clean,
        mismatches: mismatches_count,
        misaligned: misaligned_count,
        total_body_anchors: total_body,
        total_endnote_items: total_endnote,
        chapter_status: chapter_status_map,
    };

    (records, summary)
}

// ── Summary 结构 ────────────────────────────────────────────────

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct AlignmentSummary {
    pub total_chapters: usize,
    pub clean: usize,
    pub mismatches: usize,
    pub misaligned: usize,
    pub total_body_anchors: i64,
    pub total_endnote_items: i64,
    pub chapter_status: HashMap<String, ChapterStatus>,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct ChapterStatus {
    pub alignment_status: String,
    pub body_anchor_count: usize,
    pub endnote_count: usize,
}

// ── 内部辅助 ────────────────────────────────────────────────────

/// 按章分组 body anchor 标记（仅 endnote anchor，排除 footnote/unknown）。
/// 铁律 §3：禁止广播——脚注锚点不应出现在尾注对齐序列中。
///
/// ←→ Python `_body_markers_by_chapter`（但 Python 端也无此过滤——这是 Rust 端的独立修复）
fn body_markers_by_chapter(body_anchors: &[BodyAnchorRecord]) -> HashMap<String, Vec<String>> {
    let mut result: HashMap<String, Vec<String>> = HashMap::new();
    for anchor in body_anchors {
        if anchor.anchor_kind.as_str() != "endnote" {
            continue;
        }
        result
            .entry(anchor.chapter_id.clone())
            .or_default()
            .push(anchor.normalized_marker.clone());
    }
    result
}

fn endnote_markers_by_chapter(
    paragraph_endnotes: &[ChapterEndnoteRecord],
) -> HashMap<String, Vec<String>> {
    let mut result: HashMap<String, Vec<String>> = HashMap::new();
    for en in paragraph_endnotes {
        result
            .entry(en.chapter_id.clone())
            .or_default()
            .push(en.marker.clone());
    }
    result
}

fn per_chapter_alignment(
    body_markers: &[String],
    endnote_markers: &[String],
) -> (&'static str, Option<serde_json::Map<String, Value>>) {
    if body_markers == endnote_markers {
        return ("clean", None);
    }

    let (score, aligned_a, aligned_b) = needleman_wunsch_align(body_markers, endnote_markers);

    if body_markers.len() == endnote_markers.len() {
        let mismatched: Vec<Vec<String>> = body_markers
            .iter()
            .zip(endnote_markers.iter())
            .filter(|(a, b)| a != b)
            .map(|(a, b)| vec![a.clone(), b.clone()])
            .collect();
        let mut map = serde_json::Map::new();
        map.insert(
            "type".to_string(),
            Value::String("mismatched_pairs".to_string()),
        );
        map.insert(
            "details".to_string(),
            Value::Array(
                mismatched
                    .into_iter()
                    .map(|pair| Value::Array(pair.into_iter().map(Value::String).collect()))
                    .collect(),
            ),
        );
        map.insert("dp_score".to_string(), Value::Number(score.into()));
        return ("mismatches", Some(map));
    }

    // 不等长 → misaligned：从对齐结果提取插入/删除
    let mut body_extra: Vec<String> = Vec::new();
    let mut endnote_extra: Vec<String> = Vec::new();
    for (a, b) in aligned_a.iter().zip(aligned_b.iter()) {
        match (a.as_ref(), b.as_ref()) {
            (Some(a_val), None) => body_extra.push(a_val.clone()),
            (None, Some(b_val)) => endnote_extra.push(b_val.clone()),
            _ => {}
        }
    }

    let mut map = serde_json::Map::new();
    map.insert(
        "body_count".to_string(),
        Value::Number(body_markers.len().into()),
    );
    map.insert(
        "endnote_count".to_string(),
        Value::Number(endnote_markers.len().into()),
    );
    map.insert("dp_score".to_string(), Value::Number(score.into()));
    map.insert(
        "body_extra_markers".to_string(),
        Value::Array(body_extra.into_iter().map(Value::String).collect()),
    );
    map.insert(
        "endnote_extra_markers".to_string(),
        Value::Array(endnote_extra.into_iter().map(Value::String).collect()),
    );
    ("misaligned", Some(map))
}

// ── Needleman-Wunsch ────────────────────────────────────────────

fn needleman_wunsch_align(
    seq_a: &[String],
    seq_b: &[String],
) -> (i64, Vec<Option<String>>, Vec<Option<String>>) {
    let match_score: i64 = 1;
    let mismatch_penalty: i64 = -1;
    let gap_penalty: i64 = -1;

    let m = seq_a.len();
    let n = seq_b.len();

    let mut dp: Vec<Vec<i64>> = vec![vec![0; n + 1]; m + 1];
    for i in 1..=m {
        dp[i][0] = dp[i - 1][0] + gap_penalty;
    }
    for j in 1..=n {
        dp[0][j] = dp[0][j - 1] + gap_penalty;
    }

    for i in 1..=m {
        for j in 1..=n {
            let score = if seq_a[i - 1] == seq_b[j - 1] {
                match_score
            } else {
                mismatch_penalty
            };
            let from_match = dp[i - 1][j - 1] + score;
            let from_delete = dp[i - 1][j] + gap_penalty;
            let from_insert = dp[i][j - 1] + gap_penalty;
            dp[i][j] = from_match.max(from_delete).max(from_insert);
        }
    }

    // Traceback
    let mut aligned_a: Vec<Option<String>> = Vec::new();
    let mut aligned_b: Vec<Option<String>> = Vec::new();
    let mut i = m;
    let mut j = n;
    while i > 0 || j > 0 {
        if i > 0 && j > 0 {
            let score = if seq_a[i - 1] == seq_b[j - 1] {
                match_score
            } else {
                mismatch_penalty
            };
            if dp[i][j] == dp[i - 1][j - 1] + score {
                aligned_a.push(Some(seq_a[i - 1].clone()));
                aligned_b.push(Some(seq_b[j - 1].clone()));
                i -= 1;
                j -= 1;
                continue;
            }
        }
        if i > 0 && dp[i][j] == dp[i - 1][j] + gap_penalty {
            aligned_a.push(Some(seq_a[i - 1].clone()));
            aligned_b.push(None);
            i -= 1;
        } else {
            aligned_a.push(None);
            aligned_b.push(Some(seq_b[j - 1].clone()));
            j -= 1;
        }
    }

    aligned_a.reverse();
    aligned_b.reverse();
    (dp[m][n], aligned_a, aligned_b)
}
