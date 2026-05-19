//! ←→ FNM_RE/stages/export.py `_build_section_markdown()`
//!
//! 单章 markdown 构建：正文 + section heads + endnote definitions + contract_summary。

use std::collections::{HashMap, HashSet};

use anyhow::Result;
use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::export_constants::{ANY_NOTE_REF_RE, LOCAL_FOOTNOTE_DEF_RE, LOCAL_FOOTNOTE_REF_RE};
use fnm_core::marker_seq::build_raw_marker_note_sequences;
use fnm_core::records::{
    BodyAnchorRecord, NoteItemRecord, NoteLinkRecord, SectionHeadRecord, TranslationUnitRecord,
};
use fnm_core::types::NoteKind;

use super::body_render;
use super::chapter_pages;
use super::markdown_clean;
use super::note_lookup;
use super::section_head;
use super::title;

// ── 正则（从 Python 内联提取） ──────────────────────────────────

/// 匹配 [footnote] 行。
static INLINE_FOOTNOTE_LINE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)^\[footnote\] ").unwrap());

/// 空白压缩（用于 span 标题清洗）。
static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

// ── 输入/输出结构 ──────────────────────────────────────────────

/// 章节导出所需的字段（解耦自具体 record 类型）。
pub struct ChapterExportInput {
    pub chapter_id: String,
    pub title: String,
    pub pages: Vec<i64>,
    pub start_page: i64,
    pub end_page: i64,
}

/// `build_section_markdown` 的输入参数。
pub struct SectionMarkdownInput<'a> {
    pub chapter: &'a ChapterExportInput,
    pub section_heads: &'a [SectionHeadRecord],
    pub body_units: &'a [TranslationUnitRecord],
    pub note_units: &'a [TranslationUnitRecord],
    pub matched_links: &'a [NoteLinkRecord],
    pub note_items_by_id: &'a HashMap<String, NoteItemRecord>,
    pub body_anchors_by_id: &'a HashMap<String, BodyAnchorRecord>,
    pub include_diagnostic_entries: bool,
    pub diagnostic_machine_by_page: &'a HashMap<i64, String>,
    pub book_type: &'a str,
    pub chapter_note_mode: &'a str,
    pub skipped_note_ids: Option<&'a HashSet<String>>,
}

/// `build_section_markdown` 的输出。
#[derive(Debug)]
pub struct SectionMarkdownResult {
    pub content: String,
    pub contract_summary: HashMap<String, i64>,
}

// ── 辅助函数 ───────────────────────────────────────────────────

/// 安全字符串 → i64 转换，失败返回 0。
/// ←→ Python `_safe_int()` (FNM_RE/shared/notes.py)
fn safe_int(s: &str) -> i64 {
    s.trim().parse::<i64>().unwrap_or(0)
}

/// 发射尾注定义段（提取自 _build_section_markdown 的内部闭包）。
///
/// ←→ Python `_emit_definitions()` (export.py:581)
#[allow(clippy::too_many_arguments)]
fn emit_definitions(
    ids: &[String],
    note_text_by_id: &HashMap<String, String>,
    global_note_text_by_id: &HashMap<String, String>,
    note_items_by_id: &HashMap<String, NoteItemRecord>,
    local_ref_numbers: &HashMap<String, i64>,
    skipped_note_ids: Option<&HashSet<String>>,
) -> (Vec<String>, i64) {
    let skip_ids: HashSet<&str> = match skipped_note_ids {
        Some(set) => set.iter().map(|s| s.as_str()).collect(),
        None => HashSet::new(),
    };

    let mut sorted_ids: Vec<&String> = ids.iter().collect();
    sorted_ids.sort_by(|a, b| {
        let a_item = note_items_by_id.get(*a);
        let b_item = note_items_by_id.get(*b);
        let a_val = a_item
            .and_then(|item| {
                let m = item.marker.trim();
                if m.is_empty() {
                    None
                } else {
                    let v = safe_int(m);
                    if v > 0 {
                        Some(v)
                    } else {
                        None
                    }
                }
            })
            .unwrap_or(999999);
        let b_val = b_item
            .and_then(|item| {
                let m = item.marker.trim();
                if m.is_empty() {
                    None
                } else {
                    let v = safe_int(m);
                    if v > 0 {
                        Some(v)
                    } else {
                        None
                    }
                }
            })
            .unwrap_or(999999);
        a_val.cmp(&b_val).then_with(|| (*a).cmp(b))
    });

    let mut rendered: Vec<String> = Vec::new();
    let mut known_unlinked_count: i64 = 0;

    for note_id in &sorted_ids {
        let text = note_text_by_id
            .get(note_id.as_str())
            .or_else(|| global_note_text_by_id.get(note_id.as_str()))
            .map(|t| t.trim().to_string())
            .unwrap_or_default();
        if text.is_empty() {
            continue;
        }
        if skip_ids.contains(note_id.as_str()) {
            known_unlinked_count += 1;
            let display_marker = note_items_by_id
                .get(note_id.as_str())
                .map(|item| item.marker.trim().to_string())
                .unwrap_or_default();
            if display_marker.is_empty() {
                rendered.push(format!("> {text}"));
            } else {
                rendered.push(format!("> {display_marker}. {text}"));
            }
        } else {
            let number = local_ref_numbers
                .get(note_id.as_str())
                .copied()
                .unwrap_or(0);
            if number <= 0 {
                continue;
            }
            rendered.push(format!("[{number}]: {text}"));
        }
    }

    if rendered.is_empty() {
        return (vec![], known_unlinked_count);
    }

    let mut lines = vec!["### NOTES".to_string(), String::new()];
    lines.extend(rendered);
    (lines, known_unlinked_count)
}

// ── 主函数 ─────────────────────────────────────────────────────

/// 构建单章完整 markdown（正文 + section heads + 尾注定义 + 契约统计）。
///
/// ←→ Python `_build_section_markdown()` (export.py:402)
#[allow(clippy::too_many_arguments)]
pub fn build_section_markdown(input: &SectionMarkdownInput) -> Result<SectionMarkdownResult> {
    let chapter_id = &input.chapter.chapter_id;
    let chapter_title = title::format_chapter_title(&input.chapter.title, chapter_id);
    let chapter_pages_set: HashSet<i64> = chapter_pages::chapter_page_numbers(
        &input.chapter.pages,
        input.chapter.start_page,
        input.chapter.end_page,
    )
    .into_iter()
    .collect();

    // ── footnote_primary 章 → 转给 export_footnote ──
    if input.book_type == "mixed" && input.chapter_note_mode == "footnote_primary" {
        let (content, contract_summary) = super::footnote::build_inline_footnote_section_markdown(
            input.chapter,
            input.section_heads,
            input.body_units,
            input.note_units,
            input.matched_links,
            input.note_items_by_id,
            input.body_anchors_by_id,
            input.include_diagnostic_entries,
            input.diagnostic_machine_by_page,
            input.skipped_note_ids,
        );
        return Ok(SectionMarkdownResult {
            content,
            contract_summary,
        });
    }

    // ── 上下文构建 ──
    let note_text_by_id =
        note_lookup::build_note_text_by_id_for_chapter(Some(chapter_id), input.note_units);
    let note_kind_by_id =
        note_lookup::build_note_kind_by_id_for_chapter(Some(chapter_id), input.note_units);
    let marker_note_sequences = build_raw_marker_note_sequences(
        chapter_id,
        input.matched_links,
        input.note_items_by_id,
        input.body_anchors_by_id,
        &note_text_by_id,
    );
    let section_heads_by_page = section_head::build_section_heads_by_page(
        chapter_id,
        input.section_heads,
        &chapter_pages_set,
    );

    let mut lines: Vec<String> = vec![format!("## {chapter_title}"), String::new()];
    let mut seen_section_heads: HashSet<(i64, String)> = HashSet::new();
    let mut local_ref_numbers: HashMap<String, i64> = HashMap::new();
    let mut ordered_note_ids: Vec<String> = Vec::new();
    let mut footnote_ids_written: Vec<String> = Vec::new();
    let mut chapter_has_body = false;

    // ── note_marker_by_id：仅当前章的纯数字 marker ──
    let note_marker_by_id: HashMap<String, String> = input
        .note_items_by_id
        .iter()
        .filter(|(_, item)| item.chapter_id == *chapter_id)
        .filter(|(_, item)| {
            let marker = item.marker.trim();
            !marker.is_empty() && marker.chars().all(|c| c.is_ascii_digit())
        })
        .map(|(nid, item)| (nid.clone(), item.marker.trim().to_string()))
        .collect();

    // ── 预占 skipped note 的原始编号（仅 endnote） ──
    if let Some(skipped) = input.skipped_note_ids {
        for nid in skipped {
            if let Some(item) = input.note_items_by_id.get(nid) {
                if item.note_kind != NoteKind::Endnote {
                    continue;
                }
                if item.chapter_id != *chapter_id {
                    continue;
                }
                let marker = item.marker.trim();
                if marker.chars().all(|c| c.is_ascii_digit()) {
                    let reserved: i64 = safe_int(marker);
                    if reserved > 0 && !local_ref_numbers.contains_key(nid) {
                        local_ref_numbers.insert(nid.clone(), reserved);
                        ordered_note_ids.push(nid.clone());
                    }
                }
            }
        }
    }

    // ── 正文段落迭代 ──
    let mut sorted_units: Vec<&TranslationUnitRecord> = input
        .body_units
        .iter()
        .filter(|u| u.section_id == *chapter_id)
        .collect();
    sorted_units.sort_by(|a, b| {
        a.page_start
            .cmp(&b.page_start)
            .then(
                a.page_end
                    .max(a.page_start)
                    .cmp(&b.page_end.max(b.page_start)),
            )
            .then(a.unit_id.cmp(&b.unit_id))
    });

    for unit in &sorted_units {
        // 当前 unit 的 page_numbers
        let page_numbers: Vec<i64> = {
            let mut nums: Vec<i64> = unit
                .page_segments
                .iter()
                .map(|s| s.page_no)
                .filter(|p| *p > 0)
                .collect();
            if nums.is_empty() && unit.page_start > 0 {
                let start = unit.page_start;
                let end = unit.page_end.max(start);
                nums = (start..=end).collect();
            }
            nums.sort();
            nums.dedup();
            nums
        };

        // 插入 section heads
        for page_no in &page_numbers {
            if let Some(titles) = section_heads_by_page.get(page_no) {
                for t in titles {
                    let dedupe_key = (*page_no, t.to_lowercase());
                    if seen_section_heads.contains(&dedupe_key) {
                        continue;
                    }
                    seen_section_heads.insert(dedupe_key);
                    lines.push(format!("### {t}"));
                    lines.push(String::new());
                }
            }
        }

        // 解析 & 重写正文
        let body_text = body_render::resolve_body_unit_text(
            unit,
            input.include_diagnostic_entries,
            input.diagnostic_machine_by_page,
        );
        let prev_footnote_count = footnote_ids_written.len();
        let body_text = body_render::rewrite_body_text_with_local_refs(
            &body_text,
            &note_text_by_id,
            &note_kind_by_id,
            &marker_note_sequences,
            &mut local_ref_numbers,
            &mut ordered_note_ids,
            Some(&mut footnote_ids_written),
            Some(&note_marker_by_id),
        );

        // PENDING_TRANSLATION_TEXT fallback
        let body_text = if unit.translated_text.trim().is_empty()
            && !input.include_diagnostic_entries
            && note_text_by_id.is_empty()
            && ANY_NOTE_REF_RE.is_match(&body_text)
        {
            fnm_core::export_constants::PENDING_TRANSLATION_TEXT.to_string()
        } else {
            body_text
        };

        let body_text = body_text.trim().to_string();
        if body_text.is_empty() {
            continue;
        }
        chapter_has_body = true;
        lines.push(body_text);

        // 新发现的 footnote 定义
        let new_footnotes: Vec<String> = footnote_ids_written[prev_footnote_count..]
            .iter()
            .filter_map(|fn_id| {
                let fn_text = note_text_by_id
                    .get(fn_id)
                    .map(|t| t.trim().to_string())
                    .unwrap_or_default();
                if fn_text.is_empty() {
                    None
                } else {
                    Some(format!("[footnote] \\* {fn_text}"))
                }
            })
            .collect();
        for fn_line in &new_footnotes {
            lines.push(fn_line.clone());
        }
        lines.push(String::new());
    }

    // 无正文时的 fallback
    if !chapter_has_body {
        lines.push(fnm_core::export_constants::PENDING_TRANSLATION_TEXT.to_string());
        lines.push(String::new());
    }

    // ── 未渲染的 section heads（第二阶段） ──
    for head in input.section_heads {
        if head.chapter_id != *chapter_id {
            continue;
        }
        if !section_head::is_exportable_section_head(head) {
            continue;
        }
        let title = WHITESPACE_RE
            .replace_all(head.title.trim(), " ")
            .trim()
            .to_string();
        if title.is_empty() {
            continue;
        }
        let page_no = head.page_no;
        if page_no <= 0 || (!chapter_pages_set.is_empty() && !chapter_pages_set.contains(&page_no))
        {
            continue;
        }
        let dedupe_key = (page_no, title.to_lowercase());
        if seen_section_heads.contains(&dedupe_key) {
            continue;
        }
        seen_section_heads.insert(dedupe_key);
        lines.push(format!("### {title}"));
        lines.push(String::new());
    }

    // ── 尾注定义 ──
    let endnote_ids: Vec<String> = ordered_note_ids
        .iter()
        .filter(|nid| note_kind_by_id.get(*nid).map(|k| k.as_str()) == Some("endnote"))
        .cloned()
        .collect();

    let global_note_text_by_id =
        note_lookup::build_note_text_by_id_for_chapter(None, input.note_units);

    let (definition_lines, known_unlinked_count) = emit_definitions(
        &endnote_ids,
        &note_text_by_id,
        &global_note_text_by_id,
        input.note_items_by_id,
        &local_ref_numbers,
        input.skipped_note_ids,
    );
    lines.extend(definition_lines);

    // ── 后处理：strip → clean → contract_summary ──
    let joined = lines.join("\n").trim().to_string();
    let content = markdown_clean::strip_trailing_image_only_block(&joined);
    let content = markdown_clean::clean_export_html(&content);

    let body_part = if let Some(pos) = content.find("### NOTES") {
        &content[..pos]
    } else {
        &content
    };

    let ref_nums: HashSet<i64> = LOCAL_FOOTNOTE_REF_RE
        .captures_iter(body_part)
        .filter_map(|c| c.get(1)?.as_str().parse::<i64>().ok())
        .collect();
    let def_nums: HashSet<i64> = LOCAL_FOOTNOTE_DEF_RE
        .captures_iter(&content)
        .filter_map(|c| c.get(1)?.as_str().parse::<i64>().ok())
        .collect();
    let footnote_def_count = INLINE_FOOTNOTE_LINE_RE.captures_iter(&content).count() as i64;

    let ref_count = ref_nums.len() as i64;
    let def_count = def_nums.len() as i64;
    let missing = ref_nums.difference(&def_nums).count() as i64;
    let effective_missing = (missing - footnote_def_count - known_unlinked_count).max(0);
    let orphan_def_count = def_nums.difference(&ref_nums).count() as i64;

    let mut contract_summary = HashMap::new();
    contract_summary.insert("local_ref_count".to_string(), ref_count);
    contract_summary.insert(
        "local_definition_count".to_string(),
        def_count + footnote_def_count,
    );
    contract_summary.insert("missing_definition_count".to_string(), effective_missing);
    contract_summary.insert("orphan_definition_count".to_string(), orphan_def_count);
    contract_summary.insert(
        "known_unlinked_definition_count".to_string(),
        known_unlinked_count,
    );
    contract_summary.insert("inline_footnote_paragraph_attach_count".to_string(), 0);
    contract_summary.insert("inline_footnote_page_fallback_count".to_string(), 0);
    contract_summary.insert(
        "chapter_end_footnote_definition_count".to_string(),
        def_count + footnote_def_count,
    );

    Ok(SectionMarkdownResult {
        content,
        contract_summary,
    })
}
