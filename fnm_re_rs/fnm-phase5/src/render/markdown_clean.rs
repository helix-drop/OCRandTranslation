use once_cell::sync::Lazy;
use regex::Regex;

use fnm_core::export_constants::TRAILING_IMAGE_ONLY_BLOCK_RE;

static ORDINAL_SUP_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)<sup>\s*([^\d<]+?)\s*</sup>").unwrap());

static ANY_SUP_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?i)</?sup[^>]*>").unwrap());

static DIV_TAG_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"(?i)</?div[^>]*>").unwrap());

pub fn clean_export_html(text: &str) -> String {
    let cleaned = ORDINAL_SUP_RE.replace_all(text, "$1");
    let cleaned = DIV_TAG_RE.replace_all(&cleaned, "");
    ANY_SUP_RE.replace_all(&cleaned, "").to_string()
}

pub fn strip_trailing_image_only_block(text: &str) -> String {
    let mut candidate = text.trim().to_string();
    if candidate.is_empty() {
        return String::new();
    }
    loop {
        let updated = TRAILING_IMAGE_ONLY_BLOCK_RE
            .replace_all(&candidate, "")
            .to_string();
        let updated = updated.trim().to_string();
        if updated == candidate {
            return candidate;
        }
        candidate = updated;
    }
}
