//! ←→ FNM_RE/stages/export.py `_diagnostic_machine_text_by_page()`

use std::collections::HashMap;

use fnm_core::records::DiagnosticPageRecord;

/// 按页构建 machine translation 文本。
///
/// ←→ Python `_diagnostic_machine_text_by_page()` (export.py:233)
pub fn diagnostic_machine_text_by_page(
    diagnostic_pages: &[DiagnosticPageRecord],
) -> HashMap<i64, String> {
    let mut payload: HashMap<i64, String> = HashMap::new();
    for page in diagnostic_pages {
        let page_no = page._page_bp;
        if page_no <= 0 {
            continue;
        }
        let mut entries: Vec<String> = Vec::new();
        for entry in &page._page_entries {
            let source = entry._translation_source.trim().to_lowercase();
            if source == "source" {
                continue;
            }
            let candidate = if !entry.translation.trim().is_empty() {
                entry.translation.trim().to_string()
            } else if !entry._machine_translation.trim().is_empty() {
                entry._machine_translation.trim().to_string()
            } else {
                entry._manual_translation.trim().to_string()
            };
            if !candidate.is_empty() {
                entries.push(candidate);
            }
        }
        if !entries.is_empty() {
            payload.insert(page_no, entries.join("\n\n"));
        }
    }
    payload
}
