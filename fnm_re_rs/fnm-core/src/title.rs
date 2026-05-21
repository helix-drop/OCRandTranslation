//! ←→ FNM_RE/shared/title.py
//! 标题规范化与分类工具。

use once_cell::sync::Lazy;
use regex::Regex;
use unicode_normalization::UnicodeNormalization;

static TITLE_KEY_CLEAN_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[^0-9a-zà-ÿ]+").unwrap());
static TITLE_PREFIX_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:\d+|[ivxlcdm]+)[\.\)]\s*").unwrap());
static TITLE_LABEL_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?i)^\s*(?:chapter|chapitre|part|section)\b[:\s\-]*").unwrap());
static WHITESPACE_COLLAPSE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

/// 前缀匹配的前后记/序言标题（强制导出标志）。
///
/// 设计说明（CLAUDE.md §7 / §10）：
/// - 与 [`OTHER_TITLE_PATTERNS`] 的 `"front_matter"` 分组**语义不同**：
///   OTHER 是完整匹配（`^introduction$`）用于 family 判定；
///   此处是前缀匹配（`^\s*introduction\b`）用于 TOC force-export 过滤。
/// - 语言 bias：当前仅含法 + 英常用关键词。中文/德文/日文等需扩展（详见 #5 重组）。
/// - DRY：原本在 phase1 fallback / toc_semantics / role_heuristics / title_utils 共 4 处
///   重复定义，2026-05-21 合并到此处单一来源。
pub static FRONT_MATTER_FORCE_EXPORT_TITLE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)^\s*(?:introduction|avertissement|pr[eé]face|foreword|epilogue|conclusion)\b")
        .unwrap()
});

/// 判断标题前缀是否匹配 force-export 前后记标题。
///
/// caller 通常先 `normalize_title()` 处理输入。
pub fn matches_front_matter_force_export(title: &str) -> bool {
    FRONT_MATTER_FORCE_EXPORT_TITLE_RE.is_match(title)
}

// ── OTHER_TITLE_PATTERNS · 按语言分组 ───────────────────────────────────
//
// **设计与语言 bias 说明（CLAUDE.md §7 / §10 / 审计 #5）：**
//
// 当前 pattern 集合**只覆盖法语 + 英语**两种语言。其他语言的前后记/索引/参考
// 文献标题（如中文"参考文献"/"索引"、德文"Literaturverzeichnis"、日文"参考文献"等）
// 完全漏识别 → 该 family 会回退到 `body`。
//
// **根治方向（推迟到 LLM book_type_verify 主入口集成，详见 NEXT_PHASE_PLAN.md §8.4）：**
// LLM 根据 doc 语言生成 doc-specific 关键词集合，运行期注入到 `book_type_profile`，
// 取代静态 pattern 集合。
//
// **当前的局限性接受程度：**
// 法 + 英已覆盖项目当前 7 本 fixture（Biopolitics / Heidegger_en_France / Mad_Act /
// Napoleon / Germany_Madness / Neuropsychoanalysis_*）。新语种的书会以静默 fallback
// 到 body 的形式表现 — caller 应通过 LLM book_type_verify 在更上游标记该 family。
//
// 不要继续往此表加更多语种 — 跨语种 family 识别应通过 LLM 而非 regex 罗列。

/// 按语言分组的 family pattern 列表。
///
/// (language_tag, family_name, regex_patterns)
/// language_tag："en" / "fr" / "_neutral"（语言无关，如数字/符号）。
/// 注意：family 在不同语言中可能有多条记录（如 "contents" 同时有 en + fr）。
const FAMILY_PATTERNS_BY_LANGUAGE: &[(&str, &str, &[&str])] = &[
    // ── contents (TOC / 目录) ──
    ("en", "contents", &[r"^contents\b", r"^table of contents$", r"^table$"]),
    ("fr", "contents", &[r"^table des mati[eè]res$", r"^sommaire$"]),
    // ── illustrations (插图列表) ──
    (
        "en",
        "illustrations",
        &[
            r"^illustrations?$",
            r"^list of illustrations$",
            r"^list of figures$",
            r"^tables and maps$",
            r"^tables$",
            r"^figures and tables$",
            r"^figures$",
        ],
    ),
    (
        "fr",
        "illustrations",
        &[r"^liste des illustrations?$", r"^liste des figures?$"],
    ),
    // ── bibliography (参考文献) ──
    (
        "en",
        "bibliography",
        &[r"^bibliograph", r"^references?$", r"^works cited$"],
    ),
    ("fr", "bibliography", &[r"^livres et articles\b"]),
    // ── index (索引) ──
    ("_neutral", "index", &[r"^index\b", r"^indices?\b"]),
    // ── appendix (附录/术语表/略语) ──
    (
        "en",
        "appendix",
        &[
            r"^appendix\b",
            r"^appendices$",
            r"^annex",
            r"^glossary$",
            r"^note on sources$",
            r"^sources?$",
            r"^conventions$",
            r"^abbreviations?$",
        ],
    ),
    // ── front_matter (前言/致谢/序) ──
    (
        "en",
        "front_matter",
        &[
            r"^acknowledg",
            r"^foreword$",
            r"^preface$",
            r"^abstract$",
            r"^introduction$",
        ],
    ),
    ("fr", "front_matter", &[r"^remerciement", r"^avant-propos$", r"^avertissement$"]),
];

/// 按 family 聚合的预编译 Regex 列表（语言信息在编译期合并，避免运行时按语言过滤）。
///
/// 结构与上一版 `OTHER_TITLE_PATTERNS` 行为等价 —— 仅来源数据按语言分组。
///
/// AGENTS.md §2：避免 hot loop 内 `Regex::new`。
static OTHER_TITLE_PATTERNS: Lazy<Vec<(&'static str, Vec<Regex>)>> = Lazy::new(|| {
    use std::collections::BTreeMap;
    // 用 BTreeMap 保持 family 顺序稳定（按字母序），避免对依赖匹配顺序的下游产生影响
    let mut by_family: BTreeMap<&'static str, Vec<Regex>> = BTreeMap::new();
    for (_lang, family, patterns) in FAMILY_PATTERNS_BY_LANGUAGE {
        let entry = by_family.entry(*family).or_default();
        for p in *patterns {
            entry.push(Regex::new(p).expect("compile-time pattern should be valid"));
        }
    }
    // 保持原始顺序：contents / illustrations / bibliography / index / appendix / front_matter
    let family_order = [
        "contents",
        "illustrations",
        "bibliography",
        "index",
        "appendix",
        "front_matter",
    ];
    family_order
        .iter()
        .filter_map(|family| {
            by_family
                .remove(family)
                .map(|patterns| (*family, patterns))
        })
        .collect()
});

/// 规范化标题：压缩连续空白。与 Python `normalize_title` 一致。
pub fn normalize_title(value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    WHITESPACE_COLLAPSE_RE
        .replace_all(trimmed, " ")
        .into_owned()
}

/// 生成标题的归一化键（用于比对）。NFKD 归一化 + 去重音 + 去非字母数字。
/// 与 Python `normalized_title_key` 一致。
pub fn normalized_title_key(value: &str) -> String {
    let normalized = normalize_title(value).to_lowercase();
    let nfkd: String = normalized.nfkd().collect();
    // 去除 combining marks（重音符号等）
    let folded: String = nfkd.chars().filter(|c| !is_combining_mark(*c)).collect();
    TITLE_KEY_CLEAN_RE.replace_all(&folded, "").to_string()
}

/// 生成章节标题匹配键：去掉 title label/prefix 后再归一。
/// 与 Python `chapter_title_match_key` 一致。
pub fn chapter_title_match_key(value: &str) -> String {
    let normalized = normalize_title(value).to_lowercase();
    let normalized = TITLE_LABEL_RE.replace(&normalized, "").to_string();
    let normalized = TITLE_PREFIX_RE.replace(&normalized, "").to_string();
    TITLE_KEY_CLEAN_RE.replace(&normalized, "").to_string()
}

/// 根据标题文本推断所属 family（contents / illustrations / bibliography / index /
/// appendix / front_matter / body）。
/// 与 Python `guess_title_family` 一致。
pub fn guess_title_family(value: &str, page_no: i64, total_pages: i64) -> &'static str {
    let safe_page_no = page_no.max(1);
    let safe_total_pages = total_pages.max(1);
    let lowered = normalize_title(value).to_lowercase();
    for (family, patterns) in OTHER_TITLE_PATTERNS.iter() {
        for re in patterns {
            if re.is_match(&lowered) {
                return family;
            }
        }
    }
    if safe_page_no <= (12).max(safe_total_pages * 8 / 100) && lowered == "introduction" {
        return "front_matter";
    }
    "body"
}

fn is_combining_mark(c: char) -> bool {
    // Unicode combining marks: U+0300–U+036F, U+1AB0–U+1AFF, U+1DC0–U+1DFF,
    // U+20D0–U+20FF, U+FE20–U+FE2F
    matches!(
        c,
        '\u{0300}'..='\u{036F}'
            | '\u{1AB0}'..='\u{1AFF}'
            | '\u{1DC0}'..='\u{1DFF}'
            | '\u{20D0}'..='\u{20FF}'
            | '\u{FE20}'..='\u{FE2F}'
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_basic() {
        assert_eq!(normalize_title("  Hello   World  "), "Hello World");
        assert_eq!(normalize_title(""), "");
        assert_eq!(normalize_title("Single"), "Single");
    }

    #[test]
    fn normalized_key_removes_accents() {
        let key = normalized_title_key("Préface");
        assert_eq!(key, "preface");
    }

    #[test]
    fn chapter_match_key() {
        let key = chapter_title_match_key("Chapter 1: Introduction");
        assert_eq!(key, "1introduction");
    }

    #[test]
    fn guess_front_matter() {
        assert_eq!(guess_title_family("Introduction", 1, 100), "front_matter");
    }

    #[test]
    fn guess_body() {
        assert_eq!(guess_title_family("The History", 50, 100), "body");
    }
}
