//! ←→ FNM_RE/stages/export.py `_format_chapter_title()`

/// 对齐金标：Leçon du 章标题用全大写（原书印刷体例）。
///
/// ←→ Python `_format_chapter_title()` (export.py:395)
pub fn format_chapter_title(title: &str, _chapter_id: &str) -> String {
    let lower = title.trim().to_lowercase();
    if lower.starts_with("leçon du ") {
        title.to_uppercase()
    } else {
        title.to_string()
    }
}
