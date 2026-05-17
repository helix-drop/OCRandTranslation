//! ←→ FNM_RE/shared/refs.py
//! 冻结引用 token 工具：NOTE_REF / FN_REF / EN_REF 的解析与清理。

use crate::types::NoteKind;
use once_cell::sync::Lazy;
use regex::Regex;

// ── Regex 常量 ──────────────────────────────────────────────────

pub static NOTE_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\{\{NOTE_REF:([^}]+)\}\}").unwrap());

pub static FN_REF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\{\{FN_REF:([^}]+)\}\}").unwrap());

pub static EN_REF_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\{\{EN_REF:([^}]+)\}\}").unwrap());

pub static VISIBLE_ENDNOTE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\[\^(en-[^\]]+)\]").unwrap());

pub static VISIBLE_FOOTNOTE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\[\^([^\]]+)\]").unwrap());

pub static NOTE_REF_TOKEN_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\{\{NOTE_REF:[^}]+\}\}").unwrap());

static NESTED_NOTE_REF_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)\{\{NOTE_REF:([^}]*?)\{\{NOTE_REF:([^}]+)\}\}([^}]*?)\}\}").unwrap()
});

static SPLIT_NOTE_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)\{\{NO(\{\{NOTE_REF:([^}]+)\}\})TE_REF:([^}]+)\}\}").unwrap());

static WHITESPACE_BEFORE_FN_REF_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\s+(\[\^[^\]]+\])").unwrap());

// ── 公开 API ────────────────────────────────────────────────────

/// 修复嵌套的 `{{NOTE_REF:...{{NOTE_REF:...}}...}}` 结构。
/// 与 Python `cleanup_nested_note_refs` 一致。
pub fn cleanup_nested_note_refs(text: &str) -> String {
    let mut payload = text.to_string();
    let mut changed = true;
    while changed {
        changed = false;

        // 处理 SPLIT pattern（NOTE_REF 被嵌套 NOTE_REF 分裂）
        if let Some(split_match) = SPLIT_NOTE_REF_RE.find(&payload) {
            let inner_token = SPLIT_NOTE_REF_RE
                .captures(&payload)
                .and_then(|caps| caps.get(1))
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            let outer_id = SPLIT_NOTE_REF_RE
                .captures(&payload)
                .and_then(|caps| caps.get(3))
                .map(|m| m.as_str().to_string())
                .unwrap_or_default();
            let outer_token = format!("{{{{NOTE_REF:{}}}}}", outer_id);
            let replacement = format!("{} {}", outer_token, inner_token);
            let new_payload = payload.replacen(split_match.as_str(), &replacement, 1);
            if new_payload != payload {
                payload = new_payload;
                changed = true;
                continue;
            }
        }

        // 处理 NESTED pattern（NOTE_REF 内部包含 NOTE_REF）
        if let Some(caps) = NESTED_NOTE_REF_RE.captures(&payload) {
            let outer_prefix = caps.get(1).map(|m| m.as_str()).unwrap_or("");
            let inner_id = caps.get(2).map(|m| m.as_str()).unwrap_or("");
            let outer_suffix = caps.get(3).map(|m| m.as_str()).unwrap_or("");
            let outer_full = format!("{}{}{}", outer_prefix, inner_id, outer_suffix);
            let outer_token = format!("{{{{NOTE_REF:{}}}}}", outer_full);
            let inner_token = format!("{{{{NOTE_REF:{}}}}}", inner_id);
            let replacement = if outer_prefix.is_empty() && outer_suffix.is_empty() {
                inner_token
            } else {
                format!("{} {}", inner_token, outer_token)
            };
            let matched = caps.get(0).unwrap().as_str();
            let new_payload = payload.replacen(matched, &replacement, 1);
            if new_payload != payload {
                payload = new_payload;
                changed = true;
            }
        }
    }
    payload
}

/// 生成冻结 NOTE_REF token。
/// 与 Python `frozen_note_ref` 一致。
pub fn frozen_note_ref(note_id: &str) -> String {
    let token = note_id.trim();
    if token.is_empty() {
        String::new()
    } else {
        format!("{{{{NOTE_REF:{}}}}}", token)
    }
}

/// 从 note_id 判定 NoteKind：以 "en-" 开头为 endnote，否则为 footnote。
/// 与 Python `note_kind_from_id` 一致。
pub fn note_kind_from_id(note_id: &str) -> NoteKind {
    if note_id.trim().to_lowercase().starts_with("en-") {
        NoteKind::Endnote
    } else {
        NoteKind::Footnote
    }
}

fn normalize_endnote_label(note_id: &str) -> String {
    let token = note_id.trim();
    if token.is_empty() {
        return String::new();
    }
    if token.to_lowercase().starts_with("en-") {
        token.to_string()
    } else {
        format!("en-{}", token)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EndnoteMode {
    Legacy,
    Standard,
}

impl std::str::FromStr for EndnoteMode {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "legacy" => Ok(Self::Legacy),
            "standard" => Ok(Self::Standard),
            other => Err(format!("unsupported endnote_mode: {other}")),
        }
    }
}

/// 把文本中的 NOTE_REF/FN_REF/EN_REF token 改写为 markdown 脚注 `[^id]`。
/// 与 Python `replace_frozen_refs` 一致。
pub fn replace_frozen_refs(text: &str, _mode: EndnoteMode) -> String {
    let mut payload = text.to_string();

    // NOTE_REF
    payload = NOTE_REF_RE
        .replace_all(&payload, |caps: &regex::Captures| {
            let note_id = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("");
            if note_id.is_empty() {
                return String::new();
            }
            if note_kind_from_id(note_id) == NoteKind::Endnote {
                format!("[^{}]", normalize_endnote_label(note_id))
            } else {
                format!("[^{}]", note_id)
            }
        })
        .to_string();

    // FN_REF
    payload = FN_REF_RE
        .replace_all(&payload, |caps: &regex::Captures| {
            let note_id = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("");
            format!("[^{}]", note_id)
        })
        .to_string();

    // EN_REF
    payload = EN_REF_RE
        .replace_all(&payload, |caps: &regex::Captures| {
            let note_id = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("");
            format!("[^{}]", normalize_endnote_label(note_id))
        })
        .to_string();

    // 移除 [^...] 前的空白
    payload = WHITESPACE_BEFORE_FN_REF_RE
        .replace_all(&payload, "$1")
        .into_owned();

    payload
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NoteRef {
    pub kind: NoteKind,
    pub note_id: String,
}

/// 从文本提取所有 note refs。（genuine NOTE_REF tokens + 可见的 [^id] markdown 引用）
/// 与 Python `extract_note_refs` 一致。
pub fn extract_note_refs(text: &str) -> Vec<NoteRef> {
    let content = text;
    let mut matches: Vec<(usize, NoteKind, String)> = Vec::new();

    let patterns: Vec<(&str, &Lazy<Regex>)> = vec![
        ("generic", &NOTE_REF_RE),
        ("footnote", &FN_REF_RE),
        ("endnote", &EN_REF_RE),
        ("endnote", &VISIBLE_ENDNOTE_RE),
        ("footnote", &VISIBLE_FOOTNOTE_RE),
    ];

    for (kind_label, pattern) in patterns {
        for m in pattern.find_iter(content) {
            if let Some(caps) = pattern.captures(m.as_str()) {
                let note_id = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("");
                if note_id.is_empty() {
                    continue;
                }
                // VISIBLE_FOOTNOTE_RE 匹配所有 [^...]，需排除以 en- 开头的
                if kind_label == "footnote"
                    && pattern.as_str().contains("\\[\\^")
                    && note_id.to_lowercase().starts_with("en-")
                {
                    continue;
                }
                let resolved_kind = if kind_label == "generic" {
                    note_kind_from_id(note_id)
                } else if kind_label == "endnote" {
                    NoteKind::Endnote
                } else {
                    NoteKind::Footnote
                };
                matches.push((m.start(), resolved_kind, note_id.to_string()));
            }
        }
    }

    matches.sort_by_key(|(pos, ..)| *pos);

    let mut refs: Vec<NoteRef> = Vec::new();
    let mut seen: std::collections::HashSet<(NoteKind, String)> = std::collections::HashSet::new();
    for (_pos, kind, note_id) in matches {
        let key = (kind, note_id.clone());
        if seen.contains(&key) {
            continue;
        }
        seen.insert(key);
        refs.push(NoteRef { kind, note_id });
    }
    refs
}

use serde::{Deserialize, Serialize};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frozen_note_ref_basic() {
        assert_eq!(frozen_note_ref("fn-1"), "{{NOTE_REF:fn-1}}");
        assert_eq!(frozen_note_ref(""), "");
        assert_eq!(frozen_note_ref("  "), "");
    }

    #[test]
    fn note_kind_from_id_footnote() {
        assert_eq!(note_kind_from_id("fn-1"), NoteKind::Footnote);
        assert_eq!(note_kind_from_id("1"), NoteKind::Footnote);
    }

    #[test]
    fn note_kind_from_id_endnote() {
        assert_eq!(note_kind_from_id("en-1"), NoteKind::Endnote);
        assert_eq!(note_kind_from_id("EN-2"), NoteKind::Endnote);
    }

    #[test]
    fn cleanup_already_clean() {
        let text = "{{NOTE_REF:fn-1}} and {{NOTE_REF:fn-2}}";
        assert_eq!(cleanup_nested_note_refs(text), text);
    }

    #[test]
    fn replace_to_markdown_footnote() {
        let text = "Some text {{NOTE_REF:fn-1}}.";
        let result = replace_frozen_refs(text, EndnoteMode::Standard);
        assert!(result.contains("[^fn-1]"));
        assert!(!result.contains("{{NOTE_REF"));
    }

    #[test]
    fn replace_endnote_to_markdown() {
        let text = "Ref {{NOTE_REF:en-3}} here.";
        let result = replace_frozen_refs(text, EndnoteMode::Standard);
        assert!(result.contains("[^en-3]"));
    }

    #[test]
    fn extract_refs_basic() {
        let text = "{{NOTE_REF:fn-1}} and {{NOTE_REF:en-2}}";
        let refs = extract_note_refs(text);
        assert_eq!(refs.len(), 2);
        assert_eq!(refs[0].kind, NoteKind::Footnote);
        assert_eq!(refs[1].kind, NoteKind::Endnote);
    }
}
