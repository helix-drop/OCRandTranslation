//! ←→ FNM_RE/stages/export.py `_build_index_markdown()`

use fnm_core::records::ExportChapterRecord;

/// 构建 Obsidian 主目录页 markdown。
///
/// ←→ Python `_build_index_markdown()` (export.py:648)
pub fn build_index_markdown(chapters: &[ExportChapterRecord]) -> String {
    let mut lines = vec!["# 目录".to_string(), String::new()];
    for chapter in chapters {
        if chapter.path.trim().is_empty() {
            continue;
        }
        let title = if chapter.title.trim().is_empty() {
            "Untitled"
        } else {
            chapter.title.trim()
        };
        let safe_title = title.replace('[', "\\[").replace(']', "\\]");
        lines.push(format!("- [{safe_title}]({})", chapter.path));
    }
    let result = lines.join("\n").trim_end().to_string();
    format!("{result}\n")
}
