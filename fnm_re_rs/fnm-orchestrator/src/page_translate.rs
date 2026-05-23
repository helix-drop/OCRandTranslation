//! ←→ Python `FNM_RE/app/page_translate.py`
//!
//! 翻译函数：
//! - `build_unit_progress` → `build_unit_progress`
//! - `build_retry_summary` → `build_retry_summary`
//! - `prepare_page_translate_jobs` → `prepare_page_translate_jobs`
//! - `build_fnm_body_unit_jobs` → M2.A1
//! - `apply_body_unit_translations` → M2.A1
//! - `apply_body_unit_entry_result` → M2.A1

use fnm_core::db::Repository;
use fnm_core::records::{DiagnosticNoteRecord, TranslationUnitRecord};
use fnm_phase1::input::RawPage;
use serde_json::{json, Value};

/// ←→ Python `format_fnm_unit_label()` — TranslationUnitRecord 版
pub fn format_unit_label(unit: &TranslationUnitRecord) -> String {
    let kind_label = match unit.kind.as_str() {
        "body" => "正文",
        "footnote" => "脚注",
        "endnote" => "尾注",
        _ => {
            if unit.kind.is_empty() {
                "unit"
            } else {
                &unit.kind
            }
        }
    };
    let section = if unit.section_title.is_empty() {
        unit.section_id.clone()
    } else {
        unit.section_title.clone()
    };
    let section = section.trim().to_string();
    let pages_label = format_unit_pages(unit);
    if !section.is_empty() {
        format!("{kind_label} · {section} · p.{pages_label}")
    } else {
        format!("{kind_label} · p.{pages_label}")
    }
}

/// ←→ Python `unit_page_numbers()`
pub fn unit_page_numbers(unit: &TranslationUnitRecord) -> Vec<i64> {
    let mut pages: Vec<i64> = unit.page_segments.iter().map(|s| s.page_no).collect();
    pages.sort_unstable();
    pages.dedup();
    if !pages.is_empty() {
        return pages;
    }
    let start = unit.page_start;
    if start == 0 {
        return vec![];
    }
    let end = if unit.page_end >= start {
        unit.page_end
    } else {
        start
    };
    (start..=end).collect()
}

/// ←→ Python `format_fnm_unit_pages()` — TranslationUnitRecord 版
pub fn format_unit_pages(unit: &TranslationUnitRecord) -> String {
    let pages = unit_page_numbers(unit);
    if pages.is_empty() {
        return "-".to_string();
    }
    if pages.len() == 1 {
        return pages[0].to_string();
    }
    format!("{}-{}", pages[0], pages[pages.len() - 1])
}

/// ←→ Python `replace_frozen_refs()` — simplified: strip frozen ref tokens for preview.
/// Full implementation calls fnm-core regex patterns; this is sufficient for preview.
/// Uses char-based truncation (not byte) to avoid panicking on multi-byte UTF-8 (CJK).
fn preview_text(text: &str) -> String {
    let text = text.trim();
    if text.chars().count() <= 120 {
        text.to_string()
    } else {
        text.chars().take(120).collect()
    }
}

/// ←→ Python `format_fnm_unit_pages()` — Value 版（纯 dict）。
pub fn format_unit_pages_value(unit: &Value) -> String {
    let pages = unit_page_numbers_value(unit);
    if pages.is_empty() {
        return "-".to_string();
    }
    if pages.len() == 1 {
        return pages[0].to_string();
    }
    format!("{}-{}", pages[0], pages[pages.len() - 1])
}

/// ←→ Python `unit_page_numbers()` — Value 版
pub fn unit_page_numbers_value(unit: &Value) -> Vec<i64> {
    let mut pages: Vec<i64> = unit
        .get("page_segments")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|s| s.get("page_no").and_then(|v| v.as_i64()))
                .collect()
        })
        .unwrap_or_default();
    pages.sort_unstable();
    pages.dedup();
    if !pages.is_empty() {
        return pages;
    }
    let start = unit.get("page_start").and_then(|v| v.as_i64()).unwrap_or(0);
    if start == 0 {
        return vec![];
    }
    let end = unit
        .get("page_end")
        .and_then(|v| v.as_i64())
        .filter(|e| *e >= start)
        .unwrap_or(start);
    (start..=end).collect()
}

/// ←→ Python `format_fnm_unit_label()` — Value 版（纯 dict）。
pub fn format_unit_label_value(unit: &Value) -> String {
    let kind = unit
        .get("kind")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let kind_label = match kind {
        "body" => "正文",
        "footnote" => "脚注",
        "endnote" => "尾注",
        _ => {
            if kind.is_empty() {
                "unit"
            } else {
                kind
            }
        }
    };
    let section = unit
        .get("section_title")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .or_else(|| unit.get("section_id").and_then(|v| v.as_str()))
        .unwrap_or("")
        .trim()
        .to_string();
    let pages_label = format_unit_pages_value(unit);
    if !section.is_empty() {
        format!("{kind_label} · {section} · p.{pages_label}")
    } else {
        format!("{kind_label} · p.{pages_label}")
    }
}

/// ←→ Python `collect_fnm_unit_failed_locations()` — Value 版（纯 dict）。
pub fn collect_unit_failed_locations_value(unit: &Value) -> Vec<Value> {
    let section_title = unit
        .get("section_title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let mut locations: Vec<Value> = Vec::new();
    if let Some(segments) = unit.get("page_segments").and_then(|v| v.as_array()) {
        for segment in segments {
            let page_no = segment.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
            let mut visible_idx: i64 = 0;
            if let Some(paragraphs) = segment.get("paragraphs").and_then(|v| v.as_array()) {
                for para in paragraphs {
                    if para
                        .get("consumed_by_prev")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false)
                    {
                        visible_idx += 1;
                        continue;
                    }
                    let status = para
                        .get("translation_status")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .trim()
                        .to_string();
                    let is_failed = status == "error"
                        || status == "retry_pending"
                        || status == "retrying"
                        || status == "manual_required";
                    let manual_resolved = para
                        .get("manual_resolved")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);
                    if is_failed && !manual_resolved {
                        locations.push(json!({
                            "unit_id": unit.get("unit_id").and_then(|v| v.as_str()).unwrap_or(""),
                            "section_title": section_title,
                            "page_no": page_no,
                            "para_idx": visible_idx,
                            "error": para.get("last_error").and_then(|v| v.as_str()).unwrap_or(""),
                            "status": status,
                        }));
                    }
                    visible_idx += 1;
                }
            }
        }
    }
    locations
}

/// ←→ Python `list_fnm_units_with_indices()` — DB 驱动。
pub fn list_fnm_units_with_indices(
    repo: &dyn Repository,
    doc_id: &str,
) -> Result<Vec<Value>, anyhow::Error> {
    let units = repo.list_fnm_translation_units(doc_id)?;
    let result: Vec<Value> = units
        .into_iter()
        .enumerate()
        .map(|(idx, unit)| {
            let unit_id = unit.unit_id.clone();
            let kind = unit.kind.clone();
            let section_title = unit.section_title.clone();
            let status = unit.status.clone();
            let source_text = unit.source_text.clone();
            let translated_text = unit.translated_text.clone();
            let page_start = unit.page_start;
            let page_end = unit.page_end;
            let error_msg = unit.error_msg.clone();

            json!({
                "unit_id": unit_id,
                "unit_idx": (idx + 1) as i64,
                "kind": kind,
                "section_title": section_title,
                "status": status,
                "source_text": source_text,
                "translated_text": translated_text,
                "page_start": page_start,
                "page_end": page_end,
                "error_msg": error_msg,
                "page_segments": unit.page_segments,
            })
        })
        .collect();
    Ok(result)
}

/// ←→ Python `sync_fnm_retry_state()` — 返回 retry summary，Python wrapper 处理 translate state 持久化。
pub fn sync_fnm_retry_state(repo: &dyn Repository, doc_id: &str) -> Result<Value, anyhow::Error> {
    build_retry_summary(repo, doc_id)
}

/// ←→ Python `rebuild_fnm_diagnostic_page_entries()` — 从 DB 读取 diagnostic pages BPs。
pub fn rebuild_fnm_diagnostic_page_entries(
    repo: &dyn Repository,
    doc_id: &str,
) -> Result<Vec<i64>, anyhow::Error> {
    let entries = repo.list_fnm_diagnostic_pages(doc_id)?;
    let bps: Vec<i64> = entries.into_iter().map(|e| e._page_bp).collect();
    Ok(bps)
}

/// ←→ Python `collect_fnm_unit_failed_locations()`
fn collect_failed_locations(unit: &TranslationUnitRecord) -> Vec<Value> {
    let section_title = unit.section_title.trim().to_string();
    let mut locations: Vec<Value> = Vec::new();
    for segment in &unit.page_segments {
        let page_no = segment.page_no;
        let mut visible_idx: i64 = 0;
        for para in &segment.paragraphs {
            if para.consumed_by_prev {
                continue;
            }
            let status = para.translation_status.trim();
            let is_failed = status == "error"
                || status == "retry_pending"
                || status == "retrying"
                || status == "manual_required";
            if is_failed && !para.manual_resolved {
                locations.push(json!({
                    "unit_id": unit.unit_id,
                    "section_title": section_title,
                    "page_no": page_no,
                    "para_idx": visible_idx,
                    "error": para.last_error,
                    "status": status,
                }));
            }
            visible_idx += 1;
        }
    }
    locations
}

/// ←→ Python `build_retry_summary()` — 从 translation units 派生失败位置，
/// 不依赖 Python `_load_translate_state`（去掉 snapshot 分支）。
pub fn build_retry_summary(repo: &dyn Repository, doc_id: &str) -> Result<Value, anyhow::Error> {
    let units = repo.list_fnm_translation_units(doc_id)?;

    let mut failed_locations: Vec<Value> = Vec::new();
    let mut manual_required_locations: Vec<Value> = Vec::new();

    for unit in &units {
        if unit.kind != "body" {
            continue;
        }
        for loc in collect_failed_locations(unit) {
            let is_manual = loc.get("status").and_then(|s| s.as_str()) == Some("manual_required");
            if is_manual {
                manual_required_locations.push(loc.clone());
            }
            failed_locations.push(loc);
        }
    }

    let unresolved_count = failed_locations.len() as i64;
    let manual_required_count = manual_required_locations.len() as i64;

    let blocking_export = false; // Python 也硬编码 false（real 模式不阻塞）
    let reason = if manual_required_count > 0 {
        "manual_required"
    } else if unresolved_count > 0 {
        "unresolved"
    } else {
        ""
    };

    let next_failed_location = manual_required_locations
        .first()
        .or_else(|| failed_locations.first())
        .cloned();

    Ok(json!({
        "execution_mode": "test",
        "retry_progress": {
            "retry_round": 0,
            "unresolved_count": unresolved_count,
            "manual_required_count": manual_required_count,
        },
        "failed_locations": failed_locations,
        "manual_required_locations": manual_required_locations,
        "next_failed_location": next_failed_location,
        "blocking_export": blocking_export,
        "blocking_reason": reason,
    }))
}

/// ←→ Python `frozen_body_text_for_page()`
fn frozen_body_text_for_page(units: &[TranslationUnitRecord], bp: i64) -> String {
    let mut parts: Vec<&str> = Vec::new();
    for unit in units {
        if unit.kind != "body" {
            continue;
        }
        for seg in &unit.page_segments {
            if seg.page_no == bp {
                let t = seg.source_text.trim();
                if !t.is_empty() {
                    parts.push(t);
                }
            }
        }
    }
    parts.join("\n\n")
}

/// ←→ Python `split_fnm_paragraphs()`
fn split_fnm_paragraphs(text: &str) -> Vec<String> {
    text.split("\n\n")
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

/// 从 pages 数组中找 target_bp 页，构建翻译上下文。
fn build_page_context(pages: &[RawPage], target_bp: i64) -> Value {
    let cur = pages.iter().find(|p| p.book_page == target_bp);
    let prev = pages.iter().find(|p| p.book_page == target_bp - 1);
    let next = pages.iter().find(|p| p.book_page == target_bp + 1);

    let print_page_label = cur
        .and_then(|p| p.note_scan.as_ref())
        .and_then(|ns| ns.get("printPageLabel"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let print_page_display = format!("p.{}", target_bp);

    let prev_tail = prev
        .map(|p| {
            p.markdown
                .lines()
                .last()
                .map(|l| l.trim())
                .unwrap_or("")
                .to_string()
        })
        .unwrap_or_default();

    let next_head = next
        .map(|p| {
            p.markdown
                .lines()
                .next()
                .map(|l| l.trim())
                .unwrap_or("")
                .to_string()
        })
        .unwrap_or_default();

    json!({
        "print_page_label": print_page_label,
        "print_page_display": print_page_display,
        "prev_tail": prev_tail,
        "next_head": next_head,
        "page_num": target_bp,
    })
}

/// 解析页面 markdown 获段落元数据（heading_level、cross_page、printPageLabel）。
fn parse_page_meta(pages: &[RawPage], target_bp: i64) -> Vec<Value> {
    let cur = match pages.iter().find(|p| p.book_page == target_bp) {
        Some(p) => p,
        None => return vec![],
    };

    let mut paras: Vec<Value> = Vec::new();
    for line in cur.markdown.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let (hlevel, text) = if let Some(rest) = line.strip_prefix("###### ") {
            (6, rest)
        } else if let Some(rest) = line.strip_prefix("##### ") {
            (5, rest)
        } else if let Some(rest) = line.strip_prefix("#### ") {
            (4, rest)
        } else if let Some(rest) = line.strip_prefix("### ") {
            (3, rest)
        } else if let Some(rest) = line.strip_prefix("## ") {
            (2, rest)
        } else if let Some(rest) = line.strip_prefix("# ") {
            (1, rest)
        } else {
            (0, line)
        };
        paras.push(json!({
            "heading_level": hlevel,
            "text": text,
            "cross_page": Value::Null,
            "printPageLabel": "",
            "consumed_by_prev": false,
        }));
    }
    paras
}

/// ←→ Python `_body_job_from_parts()`
fn body_job(
    text: &str,
    target_bp: i64,
    print_page_label: &str,
    print_page_display: &str,
    para_idx: i64,
    heading_level: i64,
    cross_page: Option<&str>,
    prev_context: &str,
    next_context: &str,
    section_path: &[String],
) -> Value {
    json!({
        "para_idx": para_idx,
        "source_idx": para_idx,
        "bp": target_bp,
        "heading_level": heading_level,
        "text": text,
        "cross_page": cross_page,
        "start_bp": target_bp,
        "end_bp": target_bp,
        "print_page_label": print_page_label,
        "print_page_display": print_page_display,
        "bboxes": [],
        "footnotes": "",
        "prev_context": prev_context,
        "next_context": next_context,
        "section_path": section_path,
        "content_role": "body",
        "note_kind": "",
        "note_marker": "",
        "note_number": Value::Null,
        "note_section_title": "",
        "note_confidence": 0.0,
        "fnm_note_id": "",
        "para_total": 0,
    })
}

/// ←→ Python `_fnm_note_job()`
fn note_job(note: &DiagnosticNoteRecord, target_bp: i64, ctx: &Value, para_idx: i64) -> Value {
    let kind = &note.kind;
    let display = ctx
        .get("print_page_display")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    json!({
        "para_idx": para_idx,
        "source_idx": -1,
        "bp": target_bp,
        "heading_level": 0,
        "text": note.source_text,
        "cross_page": Value::Null,
        "start_bp": target_bp,
        "end_bp": target_bp,
        "print_page_label": ctx.get("print_page_label").and_then(|v| v.as_str()).unwrap_or(""),
        "print_page_display": display,
        "bboxes": [],
        "footnotes": "",
        "prev_context": "",
        "next_context": "",
        "section_path": [],
        "content_role": kind,
        "note_kind": kind,
        "note_marker": note.original_marker,
        "note_number": Value::Null,
        "note_section_title": note.section_title,
        "note_confidence": 0.0,
        "fnm_note_id": note.note_id,
        "para_total": 0,
    })
}

fn trim_context(s: &str, limit: usize) -> String {
    let s = s.trim();
    if s.len() <= limit {
        return s.to_string();
    }
    s.chars().take(limit).collect()
}

fn tail_context(s: &str, limit: usize) -> String {
    let s = s.trim();
    if s.len() <= limit {
        return s.to_string();
    }
    let n = s.chars().count();
    s.chars().skip(n.saturating_sub(limit)).collect()
}

/// ←→ Python `prepare_page_translate_jobs()`
pub fn prepare_page_translate_jobs(
    pages: &[RawPage],
    target_bp: i64,
    doc_id: &str,
    repo: &dyn Repository,
) -> Result<Value, anyhow::Error> {
    let ctx = build_page_context(pages, target_bp);
    let units = repo.list_fnm_translation_units(doc_id)?;
    let notes = repo.list_fnm_diagnostic_notes(doc_id)?;

    let frozen = frozen_body_text_for_page(&units, target_bp);
    let frozen_parts = split_fnm_paragraphs(&frozen);
    let md_meta = parse_page_meta(pages, target_bp);

    let n = std::cmp::max(frozen_parts.len(), md_meta.len());
    let context_window = 200usize;

    let mut para_jobs: Vec<Value> = Vec::new();
    let mut title_stack: Vec<String> = Vec::new();

    for i in 0..n {
        let text = frozen_parts.get(i).map(|s| s.as_str()).unwrap_or("");
        if text.is_empty() && i >= frozen_parts.len() {
            continue;
        }

        let (hlevel, cross, plab) = if let Some(m) = md_meta.get(i) {
            let hl = m.get("heading_level").and_then(|v| v.as_i64()).unwrap_or(0);
            let cr = m.get("cross_page").and_then(|v| v.as_str());
            let pl = m
                .get("printPageLabel")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            (hl, cr, pl)
        } else {
            (0i64, None, "")
        };

        let print_page_label = if plab.is_empty() {
            ctx.get("print_page_label")
                .and_then(|v| v.as_str())
                .unwrap_or("")
        } else {
            plab
        };
        let print_page_display = if !plab.is_empty() {
            format!("原书 p.{}", plab)
        } else {
            ctx.get("print_page_display")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string()
        };

        if hlevel > 0 {
            while title_stack.len() >= hlevel as usize {
                title_stack.pop();
            }
            title_stack.push(text.to_string());
        }

        let prev_frozen = frozen_parts
            .iter()
            .take(i)
            .rev()
            .find(|s| !s.is_empty())
            .map(|s| s.as_str())
            .unwrap_or("");
        let next_frozen = frozen_parts
            .iter()
            .skip(i + 1)
            .find(|s| !s.is_empty())
            .map(|s| s.as_str())
            .unwrap_or("");

        let prev_ctx_val = ctx.get("prev_tail").and_then(|v| v.as_str()).unwrap_or("");
        let next_ctx_val = ctx.get("next_head").and_then(|v| v.as_str()).unwrap_or("");

        let prev_raw = if prev_frozen.is_empty() {
            prev_ctx_val
        } else {
            prev_frozen
        };
        let next_raw = if next_frozen.is_empty() {
            next_ctx_val
        } else {
            next_frozen
        };

        let prev_context = if hlevel > 0 {
            String::new()
        } else {
            tail_context(prev_raw, context_window)
        };
        let next_context = if hlevel > 0 {
            String::new()
        } else {
            trim_context(next_raw, context_window)
        };

        let job = body_job(
            text,
            target_bp,
            print_page_label,
            &print_page_display,
            para_jobs.len() as i64,
            hlevel,
            cross,
            &prev_context,
            &next_context,
            &title_stack,
        );
        para_jobs.push(job);
    }

    for note in &notes {
        let is_footnote = note.kind == "footnote" && note.start_page == target_bp;
        let is_endnote = note.kind == "endnote" && note.start_page == target_bp;
        if is_footnote || is_endnote {
            para_jobs.push(note_job(note, target_bp, &ctx, para_jobs.len() as i64));
        }
    }

    if para_jobs.is_empty() {
        return Err(anyhow::anyhow!("第{}页未找到有效内容", target_bp));
    }

    let total = para_jobs.len() as i64;
    for (idx, job) in para_jobs.iter_mut().enumerate() {
        if let Some(obj) = job.as_object_mut() {
            obj.insert("para_idx".to_string(), json!(idx as i64));
            obj.insert("para_total".to_string(), json!(total));
        }
    }

    Ok(json!([
        ctx,
        para_jobs,
        {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "request_count": 0,
        }
    ]))
}

pub fn build_unit_progress(
    repo: &dyn Repository,
    doc_id: &str,
    snapshot_json: Option<&str>,
    _use_lightweight: bool,
) -> Result<Value, anyhow::Error> {
    let raw_units = repo.list_fnm_translation_units(doc_id)?;
    let units: Vec<(usize, &TranslationUnitRecord)> = raw_units.iter().enumerate().collect();

    let total_units = units.len();
    let done_units = units.iter().filter(|(_, u)| u.status == "done").count();
    let error_unit_indices: Vec<i64> = units
        .iter()
        .filter(|(_, u)| u.status == "error")
        .map(|(i, _)| *i as i64 + 1)
        .collect();
    let error_units = error_unit_indices.len();
    let processed_units = done_units + error_units;
    let pending_units = if total_units > processed_units {
        total_units - processed_units
    } else {
        0
    };

    // Parse snapshot for current_bp
    let current_idx: Option<i64> = snapshot_json.and_then(|s| {
        let v: Value = serde_json::from_str(s).ok()?;
        let candidate = v.get("current_bp")?;
        let n = candidate.as_i64()?;
        if n >= 1 && n <= total_units as i64 {
            Some(n)
        } else {
            None
        }
    });

    let current_unit = current_idx.and_then(|idx| {
        let pos = idx as usize - 1;
        units.get(pos).map(|(_, u)| *u)
    });

    let unit_items: Vec<Value> = units
        .iter()
        .map(|(idx, u)| {
            let unit_idx = *idx as i64 + 1;
            let status = u.status.as_str();
            let preview = preview_text(if u.translated_text.is_empty() {
                &u.source_text
            } else {
                &u.translated_text
            });
            json!({
                "unit_idx": unit_idx,
                "unit_id": u.unit_id,
                "kind": u.kind,
                "label": format_unit_label(u),
                "pages": format_unit_pages(u),
                "status": status,
                "error_msg": u.error_msg,
                "preview": preview,
            })
        })
        .collect();

    Ok(json!({
        "total_units": total_units,
        "done_units": done_units,
        "error_units": error_units,
        "failed_unit_indices": error_unit_indices,
        "processed_units": processed_units,
        "pending_units": pending_units,
        "current_unit_idx": current_idx,
        "current_unit_id": current_unit.map(|u| u.unit_id.as_str()),
        "current_unit_kind": current_unit.map(|u| u.kind.as_str()),
        "current_unit_label": current_unit.map(format_unit_label),
        "current_unit_pages": current_unit.map(format_unit_pages),
        "unit_items": unit_items,
    }))
}

/// ←→ Python `_raw_pages_label()`: 从 pages 列表中查找页面的 print_page_label。
fn raw_pages_label(page_no: i64, pages: &[Value]) -> String {
    for p in pages {
        if p.get("bookPage").and_then(|v| v.as_i64()).unwrap_or(0) == page_no {
            if let Some(label) = p.get("print_page_label").and_then(|v| v.as_str()) {
                if !label.is_empty() {
                    return label.to_string();
                }
            }
        }
    }
    page_no.to_string()
}

/// ←→ Python `build_fnm_body_unit_jobs()`: 从 body unit 构建段级翻译任务。
pub fn build_fnm_body_unit_jobs(unit: &Value, pages: &[Value]) -> Value {
    let section_title = unit
        .get("section_title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    let mut paragraph_rows: Vec<Value> = Vec::new();

    if let Some(segments) = unit.get("page_segments").and_then(|v| v.as_array()) {
        for segment in segments {
            let page_no = segment.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
            if page_no <= 0 {
                continue;
            }
            let raw_label = raw_pages_label(page_no, pages);
            let display_label = if raw_label == page_no.to_string() {
                raw_label.clone()
            } else {
                format!("[{}]", raw_label)
            };

            if let Some(paragraphs) = segment.get("paragraphs").and_then(|v| v.as_array()) {
                for para in paragraphs {
                    let text = para
                        .get("source_text")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .trim()
                        .to_string();
                    if text.is_empty()
                        || para
                            .get("consumed_by_prev")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false)
                    {
                        continue;
                    }
                    let section_path: Vec<Value> = para
                        .get("section_path")
                        .and_then(|v| v.as_array())
                        .map(|a| {
                            if a.is_empty() && !section_title.is_empty() {
                                vec![json!(section_title)]
                            } else {
                                a.to_vec()
                            }
                        })
                        .unwrap_or_else(|| {
                            if section_title.is_empty() {
                                vec![]
                            } else {
                                vec![json!(section_title)]
                            }
                        });

                    paragraph_rows.push(json!({
                        "page_no": page_no,
                        "text": text,
                        "heading_level": para.get("heading_level").and_then(|v| v.as_i64()).unwrap_or(0),
                        "cross_page": para.get("cross_page"),
                        "print_page_label": raw_label,
                        "print_page_display": display_label,
                        "section_path": section_path,
                    }));
                }
            }
        }
    }

    let count = paragraph_rows.len();
    let mut jobs: Vec<Value> = Vec::with_capacity(count);
    for idx in 0..count {
        let row = &paragraph_rows[idx];
        let prev_text = if idx > 0 {
            paragraph_rows[idx - 1]
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string()
        } else {
            String::new()
        };
        let next_text = if idx + 1 < count {
            paragraph_rows[idx + 1]
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string()
        } else {
            String::new()
        };
        let heading_level = row
            .get("heading_level")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let prev_context = if heading_level > 0 {
            String::new()
        } else {
            let chars: Vec<char> = prev_text.chars().collect();
            let start = if chars.len() > 200 {
                chars.len() - 200
            } else {
                0
            };
            chars[start..].iter().collect()
        };
        let next_context = if heading_level > 0 {
            String::new()
        } else {
            next_text.chars().take(200).collect()
        };

        jobs.push(json!({
            "para_idx": idx,
            "para_total": count,
            "source_idx": idx,
            "bp": row.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0),
            "heading_level": heading_level,
            "text": row.get("text").and_then(|v| v.as_str()).unwrap_or(""),
            "cross_page": row.get("cross_page"),
            "start_bp": row.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0),
            "end_bp": row.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0),
            "print_page_label": row.get("print_page_label").and_then(|v| v.as_str()).unwrap_or(""),
            "print_page_display": row.get("print_page_display").and_then(|v| v.as_str()).unwrap_or(""),
            "bboxes": [],
            "footnotes": "",
            "prev_context": prev_context,
            "next_context": next_context,
            "section_path": row.get("section_path").cloned().unwrap_or(json!([])),
            "content_role": "body",
            "note_kind": "",
            "note_marker": "",
            "note_number": Value::Null,
            "note_section_title": "",
            "note_confidence": 0.0,
        }));
    }

    json!(jobs)
}

/// ←→ Python `apply_body_unit_translations()`: 将译文注入 body unit 的 segments。
///
/// 段落数不匹配时返回 `Err`（P2-6）。
pub fn apply_body_unit_translations(
    unit: &Value,
    translated_paragraphs: &[Value],
) -> Result<Value, anyhow::Error> {
    let translated: Vec<String> = translated_paragraphs
        .iter()
        .map(|v| v.as_str().unwrap_or("").trim().to_string())
        .collect();

    let _section_title = unit
        .get("section_title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    let mut cursor: usize = 0;
    let mut total_parts: usize = 0;
    let mut updated_segments: Vec<Value> = Vec::new();

    if let Some(segments) = unit.get("page_segments").and_then(|v| v.as_array()) {
        for segment in segments {
            let paragraphs: Vec<&Value> = segment
                .get("paragraphs")
                .and_then(|v| v.as_array())
                .map(|a| {
                    a.iter()
                        .filter(|p| {
                            !p.get("consumed_by_prev")
                                .and_then(|v| v.as_bool())
                                .unwrap_or(false)
                        })
                        .collect()
                })
                .unwrap_or_default();

            total_parts += paragraphs.len();
            let next_cursor = cursor + paragraphs.len();
            if next_cursor > translated.len() {
                return Err(anyhow::anyhow!("FNM body unit 段落数与译文数不一致"));
            }
            let translated_parts: Vec<String> = translated[cursor..next_cursor].to_vec();
            cursor = next_cursor;

            let mut updated_paragraphs: Vec<Value> = Vec::new();
            let mut trans_iter = translated_parts.iter();
            if let Some(orig_paragraphs) = segment.get("paragraphs").and_then(|v| v.as_array()) {
                for para in orig_paragraphs {
                    let mut p = para.clone();
                    if p.get("consumed_by_prev")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false)
                    {
                        p["translated_text"] = json!("");
                    } else {
                        p["translated_text"] = json!(trans_iter.next().unwrap_or(&String::new()));
                    }
                    updated_paragraphs.push(p);
                }
            }

            let mut seg: Value = segment.clone();
            seg["paragraphs"] = json!(updated_paragraphs);
            seg["translated_parts"] = json!(translated_parts);
            seg["translated_text"] = json!(translated_parts.join("\n\n"));
            updated_segments.push(seg);
        }
    }

    if cursor != translated.len() || cursor != total_parts {
        return Err(anyhow::anyhow!("FNM body unit 段落数与译文数不一致"));
    }

    Ok(json!({
        "translated_text": translated.join("\n\n"),
        "page_segments": updated_segments,
    }))
}

/// ←→ Python `apply_body_unit_entry_result()`: 将流式翻译结果合并到 unit。
pub fn apply_body_unit_entry_result(
    unit: &Value,
    entry: &Value,
    apply_only_unresolved: bool,
) -> Value {
    let page_entries: Vec<Value> = entry
        .get("_page_entries")
        .and_then(|v| v.as_array())
        .map(|a| a.to_vec())
        .unwrap_or_default();

    let section_title = unit
        .get("section_title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    let unresolved_statuses = ["error", "retry_pending", "retrying", "manual_required"];

    let mut updated_segments: Vec<Value> = Vec::new();
    let mut failed_locations: Vec<Value> = Vec::new();
    let mut visible_translated_parts: Vec<String> = Vec::new();
    let mut cursor: usize = 0;

    if let Some(segments) = unit.get("page_segments").and_then(|v| v.as_array()) {
        for segment in segments {
            let mut seg: Value = segment.clone();
            let page_no = segment.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
            let mut updated_paragraphs: Vec<Value> = Vec::new();
            let mut seg_translated_parts: Vec<String> = Vec::new();
            let mut visible_idx: i64 = 0;

            if let Some(paragraphs) = segment.get("paragraphs").and_then(|v| v.as_array()) {
                for para in paragraphs {
                    let mut p = para.clone();
                    if p.get("consumed_by_prev")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false)
                    {
                        p["translated_text"] = json!("");
                        updated_paragraphs.push(p);
                        continue;
                    }
                    if cursor >= page_entries.len() {
                        return json!({"error": "FNM body unit 段落数与流式结果不一致"});
                    }
                    let page_entry = page_entries[cursor].clone();
                    cursor += 1;

                    let current_status = p
                        .get("translation_status")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .trim()
                        .to_string();
                    let should_apply = !apply_only_unresolved
                        || current_status.is_empty()
                        || unresolved_statuses.contains(&current_status.as_str());

                    if should_apply {
                        let translated_text = page_entry
                            .get("translation")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .trim()
                            .to_string();
                        let error_text = page_entry
                            .get("_error")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .trim()
                            .to_string();
                        let entry_status = page_entry
                            .get("_status")
                            .and_then(|v| v.as_str())
                            .unwrap_or("done")
                            .trim()
                            .to_lowercase();

                        let attempt = p
                            .get("attempt_count")
                            .and_then(|v| v.as_i64())
                            .unwrap_or(0)
                            .max(0)
                            + 1;
                        p["attempt_count"] = json!(attempt);
                        let manual_resolved = p
                            .get("manual_resolved")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false);
                        p["manual_resolved"] = json!(manual_resolved);

                        if entry_status == "done"
                            && !translated_text.is_empty()
                            && !translated_text.starts_with("[翻译失败:")
                        {
                            p["translated_text"] = json!(translated_text);
                            p["translation_status"] = json!(if manual_resolved {
                                "manual_resolved"
                            } else {
                                "done"
                            });
                            p["last_error"] = json!("");
                        } else {
                            p["translated_text"] = json!("");
                            p["translation_status"] = json!("error");
                            p["last_error"] = json!(if !error_text.is_empty() {
                                error_text
                            } else {
                                translated_text
                            });
                        }
                    }

                    let final_text = p
                        .get("translated_text")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .trim()
                        .to_string();
                    if !final_text.is_empty() {
                        seg_translated_parts.push(final_text.clone());
                        visible_translated_parts.push(final_text);
                    }

                    let para_status = p
                        .get("translation_status")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .trim()
                        .to_string();
                    let manual_resolved = p
                        .get("manual_resolved")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false);
                    if unresolved_statuses.contains(&para_status.as_str()) && !manual_resolved {
                        failed_locations.push(json!({
                            "unit_id": unit.get("unit_id").and_then(|v| v.as_str()).unwrap_or(""),
                            "section_title": section_title,
                            "page_no": page_no,
                            "para_idx": visible_idx,
                            "error": p.get("last_error").and_then(|v| v.as_str()).unwrap_or(""),
                            "status": para_status,
                        }));
                    }

                    updated_paragraphs.push(p);
                    visible_idx += 1;
                }
            }

            seg["paragraphs"] = json!(updated_paragraphs);
            seg["translated_parts"] = json!(seg_translated_parts);
            seg["translated_text"] = json!(seg_translated_parts.join("\n\n"));
            updated_segments.push(seg);
        }
    }

    if cursor != page_entries.len() {
        return json!({"error": "FNM body unit 段落数与流式结果不一致"});
    }

    json!({
        "translated_text": visible_translated_parts.join("\n\n"),
        "page_segments": updated_segments,
        "failed_locations": failed_locations,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_preview_text_cjk_truncation() {
        // 121 个中文字符（每字 3 字节 = 363 字节），验证不会 panic
        let long_cjk: String = std::iter::repeat('好').take(121).collect();
        let preview = preview_text(&long_cjk);
        assert_eq!(preview.chars().count(), 120);
    }

    #[test]
    fn test_preview_text_short() {
        assert_eq!(preview_text("hello"), "hello");
        assert_eq!(preview_text(""), "");
    }

    #[test]
    fn test_unit_page_numbers() {
        let unit = TranslationUnitRecord {
            page_start: 3,
            page_end: 5,
            ..Default::default()
        };
        assert_eq!(unit_page_numbers(&unit), vec![3, 4, 5]);
    }

    #[test]
    fn test_unit_page_numbers_from_segments() {
        let mut unit = TranslationUnitRecord::default();
        unit.page_segments = vec![
            fnm_core::records::UnitPageSegmentRecord {
                page_no: 10,
                ..Default::default()
            },
            fnm_core::records::UnitPageSegmentRecord {
                page_no: 8,
                ..Default::default()
            },
        ];
        let pages = unit_page_numbers(&unit);
        assert_eq!(pages, vec![8, 10]); // sorted and deduped
    }

    #[test]
    fn test_format_unit_label_body() {
        let unit = json!({
            "kind": "body",
            "section_title": "Leçon 1",
            "page_segments": [{"page_no": 10}]
        });
        let label = format_unit_label_value(&unit);
        assert!(label.contains("正文"));
        assert!(label.contains("Leçon 1"));
        assert!(label.contains("10"));
    }

    #[test]
    fn test_format_unit_label_footnote() {
        let unit = json!({
            "kind": "footnote",
            "page_start": 5,
            "page_end": 5
        });
        let label = format_unit_label_value(&unit);
        assert!(label.contains("脚注"));
        assert!(label.contains("5"));
    }

    #[test]
    fn test_format_unit_label_empty_kind() {
        let unit = json!({"page_start": 1, "page_end": 1});
        let label = format_unit_label_value(&unit);
        assert!(label.contains("unit"));
    }

    #[test]
    fn test_format_unit_pages_empty() {
        let unit = json!({});
        assert_eq!(format_unit_pages_value(&unit), "-");
    }

    #[test]
    fn test_format_unit_pages_single() {
        let unit = json!({"page_segments": [{"page_no": 42}]});
        assert_eq!(format_unit_pages_value(&unit), "42");
    }

    #[test]
    fn test_format_unit_pages_range() {
        let unit = json!({
            "page_segments": [{"page_no": 3}, {"page_no": 7}]
        });
        assert_eq!(format_unit_pages_value(&unit), "3-7");
    }

    #[test]
    fn test_unit_page_numbers_value_empty() {
        let unit = json!({});
        let pages = unit_page_numbers_value(&unit);
        assert!(pages.is_empty());
    }

    #[test]
    fn test_unit_page_numbers_value_segments() {
        let unit = json!({"page_segments": [{"page_no": 5}, {"page_no": 3}]});
        let pages = unit_page_numbers_value(&unit);
        assert_eq!(pages, vec![3, 5]);
    }

    #[test]
    fn test_collect_unit_failed_locations_empty() {
        let unit = json!({
            "page_segments": [{
                "page_no": 1,
                "paragraphs": [{"visible_idx": 0, "source_text": "hello", "translation_status": "done"}]
            }]
        });
        let failed = collect_unit_failed_locations_value(&unit);
        assert!(failed.is_empty());
    }

    #[test]
    fn test_collect_unit_failed_locations_with_error() {
        let unit = json!({
            "section_title": "Ch1",
            "page_segments": [{
                "page_no": 1,
                "paragraphs": [{
                    "visible_idx": 0,
                    "source_text": "hello",
                    "translation_status": "error"
                }]
            }]
        });
        let failed = collect_unit_failed_locations_value(&unit);
        assert_eq!(failed.len(), 1);
        assert_eq!(failed[0]["page_no"], 1);
    }

    #[test]
    fn test_build_fnm_body_unit_jobs_basic() {
        let unit = json!({
            "kind": "body",
            "page_segments": [{
                "page_no": 10,
                "paragraphs": [{
                    "source_text": "Bonjour le monde.",
                    "section_path": []
                }]
            }]
        });
        let pages = vec![json!({"bookPage": 10, "markdown": "Bonjour le monde."})];
        let result = build_fnm_body_unit_jobs(&unit, &pages);
        let jobs = result.as_array().unwrap();
        assert!(!jobs.is_empty());
        assert!(jobs[0]["text"].as_str().unwrap().contains("Bonjour"));
    }

    #[test]
    fn test_apply_body_unit_translations_mismatch() {
        let unit = json!({
            "page_segments": [{
                "page_no": 1,
                "paragraphs": [{"source_text": "A", "section_path": []}]
            }]
        });
        // 传入 2 个翻译但只有 1 个段落 → 应返回 Err
        let result = apply_body_unit_translations(&unit, &[json!("T1"), json!("T2")]);
        assert!(result.is_err());
    }

    #[test]
    fn test_apply_body_unit_entry_result_basic() {
        let unit = json!({
            "page_segments": [{
                "page_no": 1,
                "paragraphs": [{
                    "source_text": "Bonjour.",
                    "section_path": [],
                    "translation_status": ""
                }]
            }]
        });
        let entry = json!({
            "_page_entries": [{"translation": "Hello.", "_status": "done"}]
        });
        let result = apply_body_unit_entry_result(&unit, &entry, false);
        assert!(result.get("error").is_none());
        let segs = result["page_segments"].as_array().unwrap();
        let paras = segs[0]["paragraphs"].as_array().unwrap();
        assert_eq!(paras[0]["translated_text"].as_str().unwrap(), "Hello.");
    }
}
