//! ←→ FNM_RE/modules/llm_book_type_verify.py
//! 系统 prompt + user prompt 构建。

pub const LLM_VERIFY_SYSTEM_PROMPT: &str = "\
You are an expert at analyzing book page layouts to determine the annotation (footnote/endnote) system of an academic book.

Your task: examine pages from DIFFERENT CHAPTERS of a book and classify each chapter's annotation mode. Then aggregate to determine the book's overall type.

CRITICAL — page number distinction:
- \"PDF file page\": sequential page number in the PDF file (1-based).
  These are the numbers shown in the page labels like \"p0100\".
- \"Printed book page\": the number physically printed on the book page itself.
- When you report page numbers in your JSON response, ALWAYS use PDF file page numbers.

CHAPTER MODE values (choose one per chapter):
  \"chapter_endnote_primary\" — chapter has endnotes clustered at its end (usually
    numbered, restarting from 1), body pages may also have footnotes
  \"footnote_primary\" — chapter only has footnotes (at bottom of body pages),
    no endnote collection at chapter end
  \"book_endnote_bound\" — chapter's endnotes are in a unified Notes section
    at the back of the book (not at this chapter's end)
  \"no_notes\" — chapter has no annotations of either kind

BOOK TYPE values (derived from chapter modes):
  \"endnote_only\" — ALL sampled chapters use endnotes (chapter_end or book_end)
  \"footnote_only\" — ALL sampled chapters use only footnotes
  \"mixed\" — some chapters use endnotes, others use footnotes

For each page image, note:
- Whether there are footnote markers or footnote text at the bottom of the page
- Whether there are superscript markers in the body text
- Whether the page appears to be a dedicated endnote page (numbered citation list)
- Whether body text transitions into a notes section

Return ONLY a JSON object. No markdown fences, no explanations outside the JSON.

JSON schema:
{
  \"book_type\": \"endnote_only\" | \"footnote_only\" | \"mixed\",
  \"confidence\": \"high\" | \"medium\" | \"low\",
  \"agrees_with_pipeline\": true | false,
  \"reasoning\": \"brief explanation (1-3 sentences)\",
  \"per_chapter\": [
    {
      \"chapter_label\": \"Ch1\",
      \"chapter_mode\": \"chapter_endnote_primary\" | \"footnote_primary\" | \"book_endnote_bound\" | \"no_notes\",
      \"has_body_footnotes\": true | false,
      \"has_endnote_region\": true | false,
      \"evidence\": \"one sentence describing what you saw\"
    }
  ],
  \"toc_notes_page_verified\": true | false,
  \"toc_notes_actual_pdf_page\": <integer or null>,
  \"suspected_false_positive_pages\": [<integer, ...>]
}";

#[derive(Debug, Clone)]
pub struct PageInfo {
    pub pdf_page: i64,
    pub printed_page: Option<i64>,
    pub chapter_label: String,
}

/// 用户 prompt 的书级统计参数。
pub struct BookPromptStats {
    pub book_type: String,
    pub toc_has_notes_entry: bool,
    pub toc_notes_page: Option<i64>,
    pub chapter_count: usize,
    pub mode_types: Vec<String>,
    pub endnote_region_count: usize,
    pub endnote_item_count: i64,
}

/// ←→ Python `_build_user_prompt`
pub fn build_user_prompt(
    stats: &BookPromptStats,
    page_infos: &[PageInfo],
    chapter_modes_by_page: &std::collections::HashMap<i64, String>,
) -> String {
    let mut lines = vec![
        "The automated pipeline classified this book as:".to_string(),
        format!("  book_type = {}", stats.book_type),
        String::new(),
        "Book structure:".to_string(),
        format!("  chapters: {}", stats.chapter_count),
        format!(
            "  chapter modes present: {}",
            if stats.mode_types.is_empty() {
                "none".into()
            } else {
                stats.mode_types.join(", ")
            }
        ),
        format!("  endnote regions detected: {}", stats.endnote_region_count),
        format!(
            "  endnote items (from OCR scan): {}",
            stats.endnote_item_count
        ),
        format!(
            "  TOC has explicit 'Notes' / 'Endnotes' entry: {}",
            stats.toc_has_notes_entry
        ),
    ];
    if stats.toc_has_notes_entry {
        if let Some(p) = stats.toc_notes_page {
            lines.push(format!("  TOC says Notes/Endnotes at PRINTED page {p}"));
        }
    }

    // Group by chapter
    let mut ch_pages: std::collections::BTreeMap<String, Vec<&PageInfo>> =
        std::collections::BTreeMap::new();
    for info in page_infos {
        let label = if info.chapter_label.is_empty() {
            format!("ch_{}", info.pdf_page)
        } else {
            info.chapter_label.clone()
        };
        ch_pages.entry(label).or_default().push(info);
    }

    lines.push(String::new());
    lines.push("Pages to examine, grouped by chapter:".into());
    for (ch_label, infos) in &ch_pages {
        let pipeline_mode = infos
            .first()
            .and_then(|info| chapter_modes_by_page.get(&info.pdf_page))
            .cloned()
            .unwrap_or_else(|| "?".into());
        lines.push(format!("  [{ch_label}] pipeline says: {pipeline_mode}"));
        for info in infos {
            let printed = info
                .printed_page
                .map(|p| p.to_string())
                .unwrap_or_else(|| "?".into());
            lines.push(format!(
                "    PDF p.{:04} (printed {})",
                info.pdf_page, printed
            ));
        }
    }

    lines.extend([
        String::new(),
        "For EACH chapter above, determine its annotation mode:".into(),
        "  chapter_endnote_primary — endnotes clustered at this chapter's end".into(),
        "  footnote_primary — only footnotes, no endnote collection".into(),
        "  book_endnote_bound — endnotes in unified Notes section at book back".into(),
        "  no_notes — no annotations at all".into(),
        String::new(),
        "Then derive the book's overall book_type:".into(),
        "  mixed — if some chapters use endnotes AND others use footnotes".into(),
        "  endnote_only — if ALL chapters use endnotes (no footnote-only chapters)".into(),
        "  footnote_only — if ALL chapters use footnotes (no endnote chapters)".into(),
        String::new(),
        "If the TOC claims a Notes section, check whether the printed page number".into(),
        "on the physical page matches the TOC claim.".into(),
        "If endnote items are very few (< 50), check whether they are real endnotes".into(),
        "or high-numbered footnotes / appendix legal references.".into(),
        String::new(),
        "Return JSON.".into(),
    ]);
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_prompt_has_json_schema() {
        assert!(LLM_VERIFY_SYSTEM_PROMPT.contains("JSON schema"));
        assert!(LLM_VERIFY_SYSTEM_PROMPT.contains("book_type"));
    }

    #[test]
    fn user_prompt_groups_by_chapter() {
        let infos = vec![
            PageInfo {
                pdf_page: 10,
                printed_page: Some(5),
                chapter_label: "Ch1".into(),
            },
            PageInfo {
                pdf_page: 12,
                printed_page: Some(7),
                chapter_label: "Ch1".into(),
            },
            PageInfo {
                pdf_page: 50,
                printed_page: Some(45),
                chapter_label: "Ch2".into(),
            },
        ];
        let modes = std::collections::HashMap::new();
        let prompt = build_user_prompt(
            &BookPromptStats {
                book_type: "endnote_only".into(),
                toc_has_notes_entry: false,
                toc_notes_page: None,
                chapter_count: 5,
                mode_types: vec!["chapter_endnote_primary".into()],
                endnote_region_count: 3,
                endnote_item_count: 42,
            },
            &infos,
            &modes,
        );
        assert!(prompt.contains("[Ch1]"));
        assert!(prompt.contains("[Ch2]"));
        assert!(prompt.contains("PDF p.0010"));
    }
}
