use std::collections::HashSet;

use once_cell::sync::Lazy;
use regex::Regex;

static INVALID_CHAPTER_FILENAME_CHARS_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"[<>:"/\\|?*\x00-\x1f]+"#).unwrap());

static CHAPTER_FILENAME_SPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

pub fn sanitize_obsidian_chapter_title(title: &str) -> String {
    let sanitized = INVALID_CHAPTER_FILENAME_CHARS_RE.replace_all(title, " ");
    let sanitized = sanitized.replace('.', " ");
    let sanitized = CHAPTER_FILENAME_SPACE_RE.replace_all(&sanitized, " ");
    let sanitized = sanitized.trim().to_string();
    if sanitized.is_empty() {
        "chapter".to_string()
    } else {
        sanitized
    }
}

pub fn build_chapter_filename(
    order: i64,
    title: &str,
    used_filenames: &mut HashSet<String>,
) -> String {
    let base_name = format!(
        "{:03}-{}",
        order.max(0),
        sanitize_obsidian_chapter_title(title)
    );
    let mut candidate = format!("{base_name}.md");
    let mut suffix = 2;
    while used_filenames.contains(&candidate) {
        candidate = format!("{base_name}-{suffix}.md");
        suffix += 1;
    }
    used_filenames.insert(candidate.clone());
    candidate
}
