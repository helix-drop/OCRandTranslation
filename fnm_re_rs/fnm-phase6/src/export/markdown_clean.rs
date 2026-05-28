//! ←→ FNM_RE/stages/export.py `_normalize_markdown_content()`

pub fn normalize_markdown_content(content: &str) -> String {
    let text = content.trim();
    if text.is_empty() {
        String::new()
    } else {
        format!("{text}\n")
    }
}
