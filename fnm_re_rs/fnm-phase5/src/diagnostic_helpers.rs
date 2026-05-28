use once_cell::sync::Lazy;
use regex::Regex;

pub static LOCAL_DEF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?m)^\[\^([0-9]+)\]:").unwrap());

pub static LEGACY_FOOTNOTE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[FN-[^\]]+\]").unwrap());
pub static LEGACY_ENDNOTE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[\^en-[^\]]+\]").unwrap());
pub static LEGACY_EN_BRACKET_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\[EN-[^\]]+\]").unwrap());
pub static LEGACY_NOTE_TOKEN_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\{\{(?:NOTE_REF|FN_REF|EN_REF):[^}]+\}\}").unwrap());

pub fn split_body_and_definitions(content: &str) -> (String, String) {
    let mut body_lines: Vec<String> = Vec::new();
    let mut definition_lines: Vec<String> = Vec::new();
    let mut in_definition_block = false;

    for raw_line in content.lines() {
        if LOCAL_DEF_RE.is_match(raw_line) {
            in_definition_block = true;
            definition_lines.push(raw_line.to_string());
            continue;
        }
        if in_definition_block && (raw_line.starts_with("    ") || raw_line.starts_with('\t')) {
            definition_lines.push(raw_line.to_string());
            continue;
        }
        in_definition_block = false;
        body_lines.push(raw_line.to_string());
    }

    (body_lines.join("\n"), definition_lines.join("\n"))
}

pub fn detect_mid_paragraph_heading(body_text: &str) -> bool {
    let lines: Vec<&str> = body_text.lines().collect();
    for (idx, line) in lines.iter().enumerate() {
        let stripped = line.trim();
        if !stripped.starts_with("### ") {
            continue;
        }
        let prev = if idx > 0 { lines[idx - 1].trim() } else { "" };
        if !prev.is_empty() && !prev.starts_with('#') {
            return true;
        }
    }
    false
}
