//! 页面上下文与 job 构建。

use fnm_core::db::Repository;
use fnm_core::records::{DiagnosticNoteRecord, TranslationUnitRecord};
use fnm_phase1::input::RawPage;
use serde_json::{json, Value};

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
    // fallback：page_segments 为空时退回 unit.source_text
    if parts.is_empty() {
        for unit in units {
            if unit.kind != "body" {
                continue;
            }
            if unit.page_start <= bp && bp <= unit.page_end.max(unit.page_start) {
                let st = unit.source_text.trim();
                if !st.is_empty() {
                    parts.push(st);
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
struct BodyJobParams<'a> {
    text: &'a str,
    target_bp: i64,
    print_page_label: &'a str,
    print_page_display: &'a str,
    para_idx: i64,
    heading_level: i64,
    cross_page: Option<&'a str>,
    prev_context: &'a str,
    next_context: &'a str,
    section_path: &'a [String],
}

fn body_job(p: &BodyJobParams) -> Value {
    json!({
        "idx": p.para_idx,
        "text": p.text,
        "target_bp": p.target_bp,
        "print_page_label": p.print_page_label,
        "print_page_display": p.print_page_display,
        "heading_level": p.heading_level,
        "cross_page": p.cross_page,
        "prev_context": p.prev_context,
        "next_context": p.next_context,
        "section_path": p.section_path,
        "content_role": "body",
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

        let job = body_job(&BodyJobParams {
            text,
            target_bp,
            print_page_label,
            print_page_display: &print_page_display,
            para_idx: para_jobs.len() as i64,
            heading_level: hlevel,
            cross_page: cross,
            prev_context: &prev_context,
            next_context: &next_context,
            section_path: &title_stack,
        });
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
