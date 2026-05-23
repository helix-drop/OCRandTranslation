//! ←→ Python `FNM_RE/modules/llm_repair.py` 常量段（行 31-90）

use once_cell::sync::Lazy;
use regex::Regex;

/// ←→ Python `_JSON_BLOCK_RE` (llm_repair.py:31)
pub static JSON_BLOCK_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?is)```json\s*(.*?)```").unwrap());

/// ←→ Python `_CJK_CHAR_RE` (llm_repair.py:32)
pub static CJK_CHAR_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"[\u{3400}-\u{4dbf}\u{4e00}-\u{9fff}\u{f900}-\u{faff}]").unwrap());

/// ←→ Python `_BODY_CONTEXT_WORD_RE` (llm_repair.py:33)
pub static BODY_CONTEXT_WORD_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:[-'][A-Za-zÀ-ÖØ-öø-ÿ0-9]+)?").unwrap());

// ── Qwen 3.5+ 上下文容量（llm_repair.py:37-39）──
pub const QWEN35_PLUS_CONTEXT_TOKENS: i64 = 1_000_000;
pub const QWEN35_PLUS_MAX_INPUT_TOKENS_THINKING: i64 = 983_616;
pub const QWEN35_PLUS_MAX_INPUT_TOKENS_NO_THINK: i64 = 991_808;

// ── LLM repair 软预算 + 限流（llm_repair.py:43-53）──
pub const LLM_REPAIR_SOFT_INPUT_TOKEN_BUDGET: i64 = 2_048;
pub const LLM_REPAIR_MAX_OUTPUT_TOKENS: i64 = 2_048;
pub const LLM_REPAIR_MAX_MATCHED_EXAMPLES: usize = 2;
pub const LLM_REPAIR_MAX_UNMATCHED_DEFINITIONS: usize = 8;
pub const LLM_REPAIR_MAX_UNMATCHED_REFS: usize = 8;
pub const LLM_REPAIR_MAX_FOCUS_PAGES: usize = 8;
pub const LLM_REPAIR_MAX_IMAGE_PAGES: usize = 5;
pub const LLM_REPAIR_PAGE_CONTEXT_PROMPT_CHARS: usize = 700;
pub const LLM_REPAIR_IMAGE_SCALE: f64 = 1.3;

// ── GLM-4.6V 官方模型限制 ──
// 文档公开上下文窗口为 128K；repair 自身采用 2K 输出预算。
pub const GLM46V_CONTEXT_TOKENS: i64 = 128_000;
pub const GLM46V_MAX_IN_FLIGHT_REQUESTS: usize = 1;
pub const GLM46V_MAX_RETRY_ATTEMPTS: usize = 2;

// ── Footnote padding（llm_repair.py:78）──
pub const LLM_REPAIR_FOOTNOTE_PAGE_PADDING: i64 = 1;

// ── Tier 1 fuzzy（llm_repair.py:83-89）──
pub const FUZZY_SCORE_THRESHOLD: f64 = 88.0;
pub const MIN_CHAPTER_UNMATCHED_FOR_AUTO: usize = 1;
pub const FUZZY_AMBIGUITY_MARGIN: f64 = 5.0;

/// ←→ Python `_LLM_REPAIR_USAGE_STAGE` (llm_repair.py:90)
pub const LLM_REPAIR_USAGE_STAGE: &str = "llm_repair.cluster_request";
