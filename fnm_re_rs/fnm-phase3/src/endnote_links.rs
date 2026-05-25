//! ←→ FNM_RE/stages/endnote_links.py
//!
//! 尾注 link 匹配：anchor → note_item 配对、orphan repair、正文搜索恢复。

use fnm_core::records::{BodyAnchorRecord, NoteItemRecord, NoteRegionRecord};
use fnm_core::text::byte_index_to_char_index;
use fnm_core::types::{AnchorKind, LinkResolver, LinkStatus, NoteKind, RegionScope};
use regex::Regex;
use std::collections::{HashMap, HashSet};

/// marker → 6 个动态构建的正则。
/// 由 `build_endnote_links` 在 orphan recovery 阶段一次性预构建后传入
/// `find_marker_in_body`——避免 hot loop 内 `Regex::new`（AGENTS.md §2），
/// 同时不引入静态 `Mutex<HashMap>`（AGENTS.md §10）。
type MarkerPatterns = HashMap<String, Vec<Regex>>;

/// 为指定 marker 构建 6 个正则（动态 prefix）。
fn build_patterns_for_marker(marker: &str) -> Vec<Regex> {
    let escaped = regex::escape(marker);
    vec![
        Regex::new(&format!("\\$\\s*\\^\\s*\\{{\\s*{}\\s*\\}}\\s*\\$", escaped)).unwrap(),
        Regex::new(&format!(r"(?i)<sup>\s*{escaped}\s*</sup>")).unwrap(),
        Regex::new(&format!("\\^\\s*\\{{\\s*{}\\s*\\}}", escaped)).unwrap(),
        Regex::new(&format!("\\$\\^\\{{\\s*{}\\s*\\}}\\$", escaped)).unwrap(),
        Regex::new(&format!(r"\^\s*{escaped}\b")).unwrap(),
        Regex::new(&format!(r"»\s*{escaped}\b")).unwrap(),
    ]
}

/// 构建 endnote links。
///
/// ←→ Python `build_endnote_links`
pub fn build_endnote_links(
    anchors: &mut Vec<BodyAnchorRecord>,
    note_items: &[NoteItemRecord],
    used_anchor_ids: &mut HashSet<String>,
    page_text_by_no: &HashMap<i64, String>,
    link_serial_start: usize,
    regions_by_id: &HashMap<String, &NoteRegionRecord>,
    chapter_body_pages: &HashMap<String, HashSet<i64>>,
) -> (Vec<fnm_core::records::NoteLinkRecord>, Vec<usize>) {
    let mut links: Vec<fnm_core::records::NoteLinkRecord> = Vec::new();
    let mut link_serial = link_serial_start;
    let mut orphan_endnote_indexes: Vec<usize> = Vec::new();

    // --- endnote_resolver: 逐 item 匹配 anchor ---
    for note_item in note_items {
        if note_item.note_kind.as_str() != "endnote" {
            continue;
        }
        let marker = note_item.marker.trim();
        let chapter_id = note_item.chapter_id.trim();
        if marker.is_empty() {
            links.push(crate::link_utils::link_new_link(
                &crate::link_utils::NewLinkParams {
                    serial: link_serial,
                    chapter_id,
                    region_id: &note_item.region_id,
                    note_item_id: &note_item.note_item_id,
                    anchor_id: "",
                    status: LinkStatus::Ignored,
                    resolver: LinkResolver::Rule,
                    confidence: 0.0,
                    note_kind: NoteKind::Endnote,
                    marker: "",
                    page_no_start: note_item.page_no,
                    page_no_end: note_item.page_no,
                },
            ));
            link_serial += 1;
            continue;
        }

        let mut candidates = crate::link_utils::link_candidate_anchors(
            anchors,
            &crate::link_utils::CandidateFilter {
                chapter_id,
                marker,
                expected_kinds: &[AnchorKind::Endnote],
                used_anchor_ids,
                page_no: Some(note_item.page_no),
                footnote_window: false,
                include_synthetic: false,
                allow_cross_chapter: false,
            },
        );

        let is_direct_match = !candidates.is_empty();

        // book-scope region 在 Phase 2 后仍可能未分配到真实章。
        // Phase 3 不得只凭 marker 跨章重新分配；这里只接受同章 evidence。
        if candidates.is_empty() {
            let scope = regions_by_id
                .get(&note_item.region_id)
                .map(|r| r.scope)
                .unwrap_or(RegionScope::Chapter);
            if scope == RegionScope::Book && !chapter_id.is_empty() {
                candidates = crate::link_utils::link_candidate_anchors(
                    anchors,
                    &crate::link_utils::CandidateFilter {
                        chapter_id,
                        marker,
                        expected_kinds: &[AnchorKind::Endnote],
                        used_anchor_ids,
                        page_no: Some(note_item.page_no),
                        footnote_window: false,
                        include_synthetic: false,
                        allow_cross_chapter: false,
                    },
                );
            }
        }

        // synthetic anchor 搜索
        if candidates.is_empty() {
            candidates = crate::link_utils::link_candidate_anchors(
                anchors,
                &crate::link_utils::CandidateFilter {
                    chapter_id,
                    marker,
                    expected_kinds: &[AnchorKind::Endnote],
                    used_anchor_ids,
                    page_no: Some(note_item.page_no),
                    footnote_window: false,
                    include_synthetic: true,
                    allow_cross_chapter: false,
                },
            );
        }

        if candidates.len() == 1 {
            let selected = candidates[0];
            used_anchor_ids.insert(selected.anchor_id.clone());
            links.push(crate::link_utils::link_new_link(
                &crate::link_utils::NewLinkParams {
                    serial: link_serial,
                    chapter_id,
                    region_id: &note_item.region_id,
                    note_item_id: &note_item.note_item_id,
                    anchor_id: &selected.anchor_id,
                    status: LinkStatus::Matched,
                    resolver: if is_direct_match {
                        LinkResolver::Rule
                    } else {
                        LinkResolver::Fallback
                    },
                    confidence: selected.certainty.clamp(0.0, 1.0),
                    note_kind: NoteKind::Endnote,
                    marker,
                    page_no_start: note_item.page_no,
                    page_no_end: note_item.page_no,
                },
            ));
            link_serial += 1;
            continue;
        }

        if candidates.len() > 1 {
            let selected = candidates[0]; // 已按 page_no/paragraph_index/char_start 排序
            used_anchor_ids.insert(selected.anchor_id.clone());
            links.push(crate::link_utils::link_new_link(
                &crate::link_utils::NewLinkParams {
                    serial: link_serial,
                    chapter_id,
                    region_id: &note_item.region_id,
                    note_item_id: &note_item.note_item_id,
                    anchor_id: &selected.anchor_id,
                    status: LinkStatus::Matched,
                    resolver: LinkResolver::Repair,
                    confidence: selected.certainty.clamp(0.0, 1.0),
                    note_kind: NoteKind::Endnote,
                    marker,
                    page_no_start: note_item.page_no,
                    page_no_end: note_item.page_no,
                },
            ));
            link_serial += 1;
            continue;
        }

        // orphan_note
        links.push(crate::link_utils::link_new_link(
            &crate::link_utils::NewLinkParams {
                serial: link_serial,
                chapter_id,
                region_id: &note_item.region_id,
                note_item_id: &note_item.note_item_id,
                anchor_id: "",
                status: LinkStatus::OrphanNote,
                resolver: LinkResolver::Rule,
                confidence: 0.0,
                note_kind: NoteKind::Endnote,
                marker,
                page_no_start: note_item.page_no,
                page_no_end: note_item.page_no,
            },
        ));
        orphan_endnote_indexes.push(links.len() - 1);
        link_serial += 1;
    }

    // --- endnote orphan repair: 同章内搜索未用 anchor ---
    for idx in orphan_endnote_indexes.clone() {
        let link = &links[idx];
        if link.status != LinkStatus::OrphanNote || link.note_kind != NoteKind::Endnote {
            continue;
        }
        let candidates = crate::link_utils::link_candidate_anchors(
            anchors,
            &crate::link_utils::CandidateFilter {
                chapter_id: &link.chapter_id,
                marker: &link.marker,
                expected_kinds: &[AnchorKind::Endnote],
                used_anchor_ids,
                page_no: None,
                footnote_window: false,
                include_synthetic: false,
                allow_cross_chapter: false,
            },
        );
        if !candidates.is_empty() {
            let selected = candidates[0];
            used_anchor_ids.insert(selected.anchor_id.clone());
            let mut updated = links[idx].clone();
            updated.anchor_id = selected.anchor_id.clone();
            updated.status = LinkStatus::Matched;
            updated.resolver = LinkResolver::Repair;
            updated.confidence = selected.certainty.clamp(0.0, 1.0);
            links[idx] = updated;
        }
    }

    // --- orphan endnote 正文搜索恢复 ---
    let remaining_orphans: Vec<(usize, String, String, String)> = orphan_endnote_indexes
        .iter()
        .filter_map(|&idx| {
            let link = &links[idx];
            if link.status == LinkStatus::OrphanNote
                && link.note_kind == NoteKind::Endnote
                && !link.marker.is_empty()
            {
                Some((
                    idx,
                    link.marker.clone(),
                    link.chapter_id.clone(),
                    link.note_item_id.clone(),
                ))
            } else {
                None
            }
        })
        .collect();

    if !remaining_orphans.is_empty() {
        // 预构建 marker → patterns 缓存（避免 hot loop 内 `Regex::new`，
        // 也避免静态 `Mutex<HashMap>`——caller-owned 局部 cache）。
        let mut marker_cache: MarkerPatterns = HashMap::new();
        for (_, marker, _, _) in &remaining_orphans {
            if !marker.is_empty() && !marker_cache.contains_key(marker) {
                marker_cache.insert(marker.clone(), build_patterns_for_marker(marker));
            }
        }

        for (idx, marker, chapter_id, note_item_id) in remaining_orphans {
            let page_nos: Vec<i64> = chapter_body_pages
                .get(&chapter_id)
                .map(|s| {
                    let mut v: Vec<i64> = s.iter().copied().collect();
                    v.sort();
                    v
                })
                .unwrap_or_default();

            let patterns = match marker_cache.get(&marker) {
                Some(p) => p.as_slice(),
                None => continue, // 空 marker 已经在 cache 构建时过滤
            };

            let mut recovered = false;
            for pno in &page_nos {
                if let Some(body_text) = page_text_by_no.get(pno) {
                    if let Some(hit) = find_marker_in_body(body_text, &marker, patterns) {
                        let anchor_id = format!("orphan-recovery-{note_item_id}");
                        anchors.push(BodyAnchorRecord {
                            anchor_id: anchor_id.clone(),
                            chapter_id: chapter_id.clone(),
                            page_no: *pno,
                            paragraph_index: 0,
                            char_start: byte_index_to_char_index(body_text, hit.start)
                                .expect("regex boundary")
                                as i64,
                            char_end: byte_index_to_char_index(body_text, hit.end)
                                .expect("regex boundary")
                                as i64,
                            source_marker: hit.matched_text.clone(),
                            normalized_marker: marker.clone(),
                            anchor_kind: AnchorKind::Endnote,
                            certainty: 0.7,
                            source_text: hit.source_text.clone(),
                            source: "orphan_recovery".to_string(),
                            synthetic: true,
                            ocr_repaired_from_marker: String::new(),
                        });
                        used_anchor_ids.insert(anchor_id.clone());
                        let mut updated = links[idx].clone();
                        updated.anchor_id = anchor_id;
                        updated.status = LinkStatus::Matched;
                        updated.resolver = LinkResolver::OrphanRecovery;
                        updated.confidence = 0.7;
                        links[idx] = updated;
                        recovered = true;
                        break;
                    }
                }
            }

            if !recovered && !page_nos.is_empty() {
                let combined: String = page_nos
                    .iter()
                    .filter_map(|pno| page_text_by_no.get(pno).map(|s| s.as_str()))
                    .collect::<Vec<_>>()
                    .join("\n");
                if let Some(hit) = find_marker_in_body(&combined, &marker, patterns) {
                    let anchor_id = format!("orphan-recovery-{note_item_id}");
                    anchors.push(BodyAnchorRecord {
                        anchor_id: anchor_id.clone(),
                        chapter_id: chapter_id.clone(),
                        page_no: page_nos[0],
                        paragraph_index: 0,
                        char_start: byte_index_to_char_index(&combined, hit.start)
                            .expect("regex boundary") as i64,
                        char_end: byte_index_to_char_index(&combined, hit.end)
                            .expect("regex boundary") as i64,
                        source_marker: hit.matched_text.clone(),
                        normalized_marker: marker.clone(),
                        anchor_kind: AnchorKind::Endnote,
                        certainty: 0.5,
                        source_text: hit.source_text.clone(),
                        source: "orphan_recovery".to_string(),
                        synthetic: true,
                        ocr_repaired_from_marker: String::new(),
                    });
                    used_anchor_ids.insert(anchor_id.clone());
                    let mut updated = links[idx].clone();
                    updated.anchor_id = anchor_id;
                    updated.status = LinkStatus::Matched;
                    updated.resolver = LinkResolver::OrphanRecovery;
                    updated.confidence = 0.5;
                    links[idx] = updated;
                }
            }
        }
    }

    (links, orphan_endnote_indexes)
}

// ── 正文 marker 搜索 ────────────────────────────────────────────

struct BodyHit {
    start: usize,
    end: usize,
    matched_text: String,
    source_text: String,
}

/// 在正文文本中搜索已知 marker 的各种表示形式。
///
/// `patterns` 由 caller 预先按 marker 构建并缓存——避免 hot loop 内
/// 重复 `Regex::new`（AGENTS.md §2），也避免静态 `Mutex<HashMap>`（§10）。
fn find_marker_in_body(body_text: &str, marker: &str, patterns: &[Regex]) -> Option<BodyHit> {
    // Unicode 上标映射
    fn unicode_superscript_pattern(num_str: &str) -> Option<String> {
        let mut result = String::new();
        for c in num_str.chars() {
            let sup = match c {
                '0' => '⁰',
                '1' => '¹',
                '2' => '²',
                '3' => '³',
                '4' => '⁴',
                '5' => '⁵',
                '6' => '⁶',
                '7' => '⁷',
                '8' => '⁸',
                '9' => '⁹',
                _ => return None,
            };
            result.push(sup);
        }
        Some(result)
    }

    for re in patterns.iter() {
        if let Some(m) = re.find(body_text) {
            let start = m.start();
            let end = m.end();
            return Some(BodyHit {
                start,
                end,
                matched_text: m.as_str().to_string(),
                source_text: extract_context(body_text, start, end),
            });
        }
    }

    // Unicode 上标搜索（带负前瞻：不匹配多位数上标的前缀）
    // ←→ Python 有负前瞻 `(?![\d⁰¹²³⁴⁵⁶⁷⁸⁹])` 防止 "1" 匹配 "¹²"。
    // Rust regex crate 不支持 lookahead，用字符边界手动验证。
    if let Some(unicode_pat) = unicode_superscript_pattern(marker) {
        let body_chars: Vec<char> = body_text.chars().collect();
        let pat_chars: Vec<char> = unicode_pat.chars().collect();
        for start_idx in 0..body_chars
            .len()
            .saturating_sub(pat_chars.len().saturating_sub(1))
        {
            if body_chars[start_idx..].starts_with(&pat_chars) {
                let end_idx = start_idx + pat_chars.len();
                // 负后顾：前一个字符不是上标数字
                if start_idx > 0 && "⁰¹²³⁴⁵⁶⁷⁸⁹".contains(body_chars[start_idx - 1])
                {
                    continue;
                }
                // 负前瞻：后一个字符不是上标数字
                if end_idx < body_chars.len() && "⁰¹²³⁴⁵⁶⁷⁸⁹".contains(body_chars[end_idx])
                {
                    continue;
                }
                // 转换回字节偏移
                let byte_start = body_text[..]
                    .char_indices()
                    .nth(start_idx)
                    .map(|(i, _)| i)
                    .unwrap_or(0);
                let byte_end = byte_start + unicode_pat.len();
                return Some(BodyHit {
                    start: byte_start,
                    end: byte_end,
                    matched_text: unicode_pat.clone(),
                    source_text: extract_context(body_text, byte_start, byte_end),
                });
            }
        }
    }

    None
}

fn extract_context(text: &str, start: usize, end: usize) -> String {
    let ctx_start = start.saturating_sub(30);
    let ctx_end = (end + 30).min(text.len());
    text.char_indices()
        .skip_while(|(i, _)| *i < ctx_start)
        .take_while(|(i, _)| *i < ctx_end)
        .map(|(_, ch)| ch)
        .collect()
}
