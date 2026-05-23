//! ←→ Python `FNM_RE/modules/llm_repair.py` prompt 构建（行 471-820）。
//!
//! 11 个函数（按 Python 顺序）：
//! - `repair_system_prompt` ←→ `_repair_system_prompt` (行 471)
//! - `trim_excerpt` ←→ `_trim_excerpt` (行 490)
//! - `estimate_prompt_tokens` ←→ `_estimate_prompt_tokens` (行 497)
//! - `should_request_llm_for_cluster` ←→ `_should_request_llm_for_cluster` (行 507)
//! - `should_attach_repair_images` ←→ `_should_attach_repair_images` (行 512)
//! - `should_include_page_context_text` ←→ `_should_include_page_context_text` (行 517)
//! - `priority_pages_for_visual_context` ←→ `_priority_pages_for_visual_context` (行 586)
//! - `select_page_contexts_for_request` ←→ `_select_page_contexts_for_request` (行 616)
//! - `slice_cluster_for_request` ←→ `_slice_cluster_for_request` (行 629)
//! - `repair_user_prompt` ←→ `_repair_user_prompt` (行 701)

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::{json, Value};

use crate::constants::{
    BODY_CONTEXT_WORD_RE, CJK_CHAR_RE, LLM_REPAIR_MAX_IMAGE_PAGES, LLM_REPAIR_MAX_MATCHED_EXAMPLES,
    LLM_REPAIR_MAX_UNMATCHED_DEFINITIONS, LLM_REPAIR_MAX_UNMATCHED_REFS,
    LLM_REPAIR_PAGE_CONTEXT_PROMPT_CHARS,
};
use crate::page_context::endnote_synthesize_focus_pages;

static WHITESPACE_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

/// ←→ Python `_repair_system_prompt` (llm_repair.py:471-487)
pub fn repair_system_prompt() -> String {
    String::from(
        "你是 FNM 注释修补助手（同时处理 endnote 和 footnote 两种 note_system）。\
只处理已经确认的 unresolved cluster，不要改 section、note zone、标题或原文。\
优先依据页面截图判断，不要被 OCR 坏掉的数字误导。\
如果截图已经足够清楚，就不要退回 needs_review。\
你只能输出 JSON 数组；每项 action 只能是 match、ignore_ref、synthesize_anchor 或 needs_review。\
match 需要 note_item_id、anchor_id、confidence、reason；\
ignore_ref 需要 anchor_id、confidence、reason；\
synthesize_anchor 仅在正文里能找到一个独一无二的短语锚点、但该锚点没有对应的结构化 anchor 记录时使用，\
需要 note_item_id、anchor_phrase(从正文中原样抄写的 3~12 词唯一短语，不要自编)、confidence、reason；\
confidence 必须是 0.0 到 1.0 之间的数字（如 0.95、0.8、0.5），不能用 'high'、'medium'、'low' 等文字代替；\
若某条 note 当前只是错误地绑到了 synthetic / 跨页锚点，而截图清楚显示它应改绑到当前显式锚点，也直接用 match，不要 needs_review。\
needs_review 需要 reason。",
    )
    .replace("anchor_phrase(", "anchor_phrase（")
    .replace(", 不要自编)", "，不要自编）")
}

/// ←→ Python `_trim_excerpt` (llm_repair.py:490-494)
pub fn trim_excerpt(text: &str, limit: usize) -> String {
    let collapsed = WHITESPACE_RE.replace_all(text, " ").trim().to_string();
    if collapsed.chars().count() <= limit {
        return collapsed;
    }
    let mut truncated: String = collapsed.chars().take(limit).collect();
    while truncated.ends_with(char::is_whitespace) {
        truncated.pop();
    }
    truncated.push_str(" ...");
    truncated
}

/// ←→ Python `_estimate_prompt_tokens` (llm_repair.py:497-504)
///
/// 保守估算 prompt token 数：CJK 字符按 1 token / 字，其余按 3.5 字符 / token，加 16 token overhead。
pub fn estimate_prompt_tokens(text: &str) -> i64 {
    if text.is_empty() {
        return 0;
    }
    let cjk_count = CJK_CHAR_RE.find_iter(text).count();
    let total_chars = text.chars().count();
    let non_cjk = total_chars.saturating_sub(cjk_count);
    let non_cjk_tokens = (non_cjk as f64 / 3.5).ceil() as i64;
    (cjk_count as i64) + non_cjk_tokens + 16
}

fn allowed_actions_of(request_cluster: &Value) -> Vec<String> {
    request_cluster
        .get("allowed_actions")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.trim().to_string()))
                .filter(|s| !s.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

/// ←→ Python `_should_request_llm_for_cluster` (llm_repair.py:507-509)
pub fn should_request_llm_for_cluster(request_cluster: &Value) -> bool {
    allowed_actions_of(request_cluster)
        .iter()
        .any(|action| !action.is_empty() && action != "needs_review")
}

/// ←→ Python `_should_attach_repair_images` (llm_repair.py:512-514)
pub fn should_attach_repair_images(request_cluster: &Value) -> bool {
    let actions = allowed_actions_of(request_cluster);
    actions.iter().any(|a| a == "synthesize_anchor")
}

/// ←→ Python `_should_include_page_context_text` (llm_repair.py:517-526)
pub fn should_include_page_context_text(request_cluster: &Value) -> bool {
    if should_attach_repair_images(request_cluster) {
        return true;
    }
    let actions = allowed_actions_of(request_cluster);
    actions.iter().any(|a| a == "ignore_ref")
}

/// ←→ Python `_priority_pages_for_visual_context` (llm_repair.py:586-613)
pub fn priority_pages_for_visual_context(request_cluster: &Value) -> Vec<i64> {
    let focus = endnote_synthesize_focus_pages(request_cluster);
    if !focus.is_empty() {
        return focus;
    }
    let mut pages: Vec<i64> = Vec::new();
    for item in request_cluster
        .get("unmatched_anchors")
        .and_then(|v| v.as_array())
        .unwrap_or(&Vec::new())
    {
        let p = item.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
        if p > 0 {
            pages.push(p);
        }
    }
    let note_system = request_cluster
        .get("note_system")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    if note_system != "endnote" {
        for item in request_cluster
            .get("unmatched_note_items")
            .and_then(|v| v.as_array())
            .unwrap_or(&Vec::new())
        {
            let p = item.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
            if p > 0 {
                pages.push(p);
            }
        }
    }
    let mut ordered: Vec<i64> = Vec::new();
    let mut seen: std::collections::HashSet<i64> = Default::default();
    for p in pages {
        if seen.insert(p) {
            ordered.push(p);
        }
    }
    ordered
}

/// ←→ Python `_select_page_contexts_for_request` (llm_repair.py:616-626)
pub fn select_page_contexts_for_request(request_cluster: &Value) -> Vec<Value> {
    let contexts: Vec<Value> = request_cluster
        .get("page_contexts")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    if contexts.is_empty() || !should_include_page_context_text(request_cluster) {
        return Vec::new();
    }
    let priority_pages = priority_pages_for_visual_context(request_cluster);
    // 与 Python 一致：priority_pages 有命中才替换 selected，否则保留原 contexts。
    // 通过 indices Vec 间接定位避免拷贝 Value：先按 page_no 收集 (idx, page_no)，
    // 再按 priority_pages 顺序挑出 indices；命中后才整体重排（move）。
    let mut selected = contexts;
    if !priority_pages.is_empty() {
        let page_index: Vec<(usize, i64)> = selected
            .iter()
            .enumerate()
            .map(|(i, item)| (i, item.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0)))
            .collect();
        let chosen_indices: Vec<usize> = priority_pages
            .iter()
            .filter_map(|p| page_index.iter().find(|(_, pn)| pn == p).map(|(i, _)| *i))
            .collect();
        if !chosen_indices.is_empty() {
            // chosen_indices 可能包含重复（priority_pages 罕见重复），用 take 防御
            let mut taken: Vec<Option<Value>> = selected.into_iter().map(Some).collect();
            selected = chosen_indices
                .into_iter()
                .filter_map(|i| taken.get_mut(i).and_then(|slot| slot.take()))
                .collect();
        }
    }
    selected.truncate(LLM_REPAIR_MAX_IMAGE_PAGES);
    selected
}

/// `_slice_cluster_for_request` 参数包
#[derive(Default, Clone, Copy)]
pub struct SliceCaps {
    pub max_matched_examples: Option<usize>,
    pub max_unmatched_note_items: Option<usize>,
    pub max_unmatched_anchors: Option<usize>,
}

fn slice_array(arr: Option<&Vec<Value>>, cap: usize) -> Vec<Value> {
    arr.cloned()
        .unwrap_or_default()
        .into_iter()
        .take(cap)
        .collect()
}

/// ←→ Python `_slice_cluster_for_request` (llm_repair.py:629-698)
///
/// 对 cluster 切片到请求容量，计算 allowed_actions + request_mode + page_contexts。
pub fn slice_cluster_for_request(cluster: &Value, caps: SliceCaps) -> Value {
    let cap_matched = caps
        .max_matched_examples
        .unwrap_or(LLM_REPAIR_MAX_MATCHED_EXAMPLES);
    let cap_notes = caps
        .max_unmatched_note_items
        .unwrap_or(LLM_REPAIR_MAX_UNMATCHED_DEFINITIONS);
    let cap_anchors = caps
        .max_unmatched_anchors
        .unwrap_or(LLM_REPAIR_MAX_UNMATCHED_REFS);

    let matched_examples = slice_array(
        cluster.get("matched_examples").and_then(|v| v.as_array()),
        cap_matched,
    );
    let unmatched_note_items = slice_array(
        cluster
            .get("unmatched_note_items")
            .and_then(|v| v.as_array()),
        cap_notes,
    );
    let unmatched_anchors = slice_array(
        cluster.get("unmatched_anchors").and_then(|v| v.as_array()),
        cap_anchors,
    );
    let rebind_candidates = slice_array(
        cluster.get("rebind_candidates").and_then(|v| v.as_array()),
        cap_notes,
    );

    let body_text_raw = cluster
        .get("chapter_body_text")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let body_word_count = BODY_CONTEXT_WORD_RE.find_iter(&body_text_raw).count();
    let mut has_body_text = body_text_raw.chars().count() >= 30 && body_word_count >= 5;
    if !has_body_text {
        let excerpts: Vec<String> = cluster
            .get("page_contexts")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .filter_map(|ctx| {
                ctx.get("ocr_excerpt")
                    .and_then(|v| v.as_str())
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
            })
            .collect();
        let excerpt_body = excerpts.join("\n");
        let excerpt_word_count = BODY_CONTEXT_WORD_RE.find_iter(&excerpt_body).count();
        has_body_text = excerpt_body.chars().count() >= 120 && excerpt_word_count >= 20;
    }
    let has_page_context = cluster
        .get("page_contexts")
        .and_then(|v| v.as_array())
        .map(|a| !a.is_empty())
        .unwrap_or(false);

    let (allowed_actions, request_mode) = derive_actions(
        &unmatched_note_items,
        &unmatched_anchors,
        &rebind_candidates,
        has_body_text,
        has_page_context,
    );

    let mut request_cluster = cluster.clone();
    request_cluster["matched_examples"] = Value::Array(matched_examples);
    request_cluster["unmatched_note_items"] = Value::Array(unmatched_note_items);
    request_cluster["unmatched_anchors"] = Value::Array(unmatched_anchors);
    request_cluster["rebind_candidates"] = Value::Array(rebind_candidates);
    request_cluster["allowed_actions"] = Value::Array(
        allowed_actions
            .iter()
            .map(|s| Value::String((*s).to_string()))
            .collect(),
    );
    request_cluster["request_mode"] = Value::String(request_mode.to_string());
    request_cluster["request_caps"] = json!({
        "matched_examples": cap_matched,
        "unmatched_note_items": cap_notes,
        "unmatched_anchors": cap_anchors,
    });
    let page_contexts = select_page_contexts_for_request(&request_cluster);
    request_cluster["page_contexts"] = Value::Array(page_contexts);
    request_cluster
}

fn derive_actions(
    unmatched_note_items: &[Value],
    unmatched_anchors: &[Value],
    rebind_candidates: &[Value],
    has_body_text: bool,
    has_page_context: bool,
) -> (Vec<&'static str>, &'static str) {
    if !unmatched_note_items.is_empty() && !unmatched_anchors.is_empty() {
        if has_body_text {
            return (
                vec!["match", "ignore_ref", "synthesize_anchor", "needs_review"],
                "paired",
            );
        }
        return (vec!["match", "ignore_ref", "needs_review"], "paired");
    }
    if !unmatched_anchors.is_empty() && !rebind_candidates.is_empty() {
        if has_page_context && unmatched_anchors.len() > rebind_candidates.len() {
            return (vec!["match", "ignore_ref", "needs_review"], "anchor_rebind");
        }
        return (vec!["match", "ignore_ref", "needs_review"], "anchor_rebind");
    }
    if !unmatched_anchors.is_empty() {
        if has_page_context {
            return (vec!["ignore_ref", "needs_review"], "ref_only_visual");
        }
        return (vec!["ignore_ref", "needs_review"], "ref_only");
    }
    if !unmatched_note_items.is_empty() {
        if has_body_text {
            return (
                vec!["synthesize_anchor", "needs_review"],
                "note_only_with_body",
            );
        }
        return (vec!["needs_review"], "note_only");
    }
    (vec!["needs_review"], "review_only")
}

/// ←→ Python `_repair_user_prompt` (llm_repair.py:701-820)
///
/// 组装用户 prompt：JSON payload + allowed_actions hint + 模式相关额外规则。
pub fn repair_user_prompt(cluster: &Value, caps: SliceCaps) -> String {
    let request_cluster = slice_cluster_for_request(cluster, caps);
    let allowed_actions: Vec<String> = request_cluster
        .get("allowed_actions")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_else(|| vec![Value::String("needs_review".to_string())])
        .into_iter()
        .filter_map(|v| v.as_str().map(|s| s.to_string()))
        .collect();
    let allowed_set: std::collections::HashSet<&str> =
        allowed_actions.iter().map(|s| s.as_str()).collect();

    let mut payload = json!({
        "cluster_id": request_cluster.get("cluster_id").cloned().unwrap_or(Value::Null),
        "chapter_title": request_cluster.get("chapter_title").cloned().unwrap_or(Value::Null),
        "page_range": [
            request_cluster.get("page_start").cloned().unwrap_or(Value::Null),
            request_cluster.get("page_end").cloned().unwrap_or(Value::Null),
        ],
        "note_system": request_cluster.get("note_system").cloned().unwrap_or(Value::Null),
        "request_mode": request_cluster.get("request_mode").cloned().unwrap_or(Value::Null),
        "allowed_actions": allowed_actions.iter().map(|s| Value::String(s.clone())).collect::<Vec<_>>(),
        "page_contexts": page_contexts_payload(&request_cluster),
        "matched_examples": matched_examples_payload(&request_cluster),
        "unmatched_note_items": unmatched_note_items_payload(&request_cluster),
        "unmatched_anchors": unmatched_anchors_payload(&request_cluster),
        "rebind_candidates": rebind_candidates_payload(&request_cluster),
    });

    let mut chapter_body_text = request_cluster
        .get("chapter_body_text")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if chapter_body_text.is_empty() && allowed_set.contains("synthesize_anchor") {
        let parts: Vec<String> = request_cluster
            .get("page_contexts")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .filter_map(|ctx| {
                ctx.get("ocr_excerpt")
                    .and_then(|v| v.as_str())
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
            })
            .collect();
        if !parts.is_empty() {
            chapter_body_text = parts.join("\n\n");
        }
    }
    if !chapter_body_text.is_empty() && allowed_set.contains("synthesize_anchor") {
        payload["chapter_body_excerpt"] = Value::String(trim_excerpt(&chapter_body_text, 1800));
    }

    let action_hint = allowed_actions.join("、");
    let mut extra_rules = String::new();
    if allowed_set.contains("synthesize_anchor") {
        extra_rules.push_str(
            "\n若正文里确实能找到某条孤儿尾注对应的独一无二短语，且该短语没有对应的结构化 anchor 记录，\
才用 synthesize_anchor；anchor_phrase 必须逐字摘自 chapter_body_excerpt，长度 3~12 词，\
禁止自编、禁止填章节其他地方或通用短语。",
        );
    }
    if allowed_set.contains("ignore_ref") {
        extra_rules.push_str(
            "\n去重任务：判断 unmatched_anchors 中哪些是假阳性 ref。\
参考 page_contexts 的 OCR 文本片段和 matched_examples 的正例模式。\
以下情况应判定为假阳性（ignore_ref, confidence>=0.9）：\
(1) 同一 marker 在同一页或相邻页重复出现（取与 matched_examples 模式一致的那个，其余忽略）\
(2) marker 出现在明显非注释上下文中（如 'p. 15' 是页码、'n 9' 是编号、日期年份等）\
(3) marker 所在段落已有同编号的 matched anchor（该 unmatched 是重复检测）\
(4) marker 周围文字模式与同章 matched_examples 的锚点上下文明显不同\
以下情况应保留（needs_review, confidence<=0.5）：\
(1) marker 周围文字可能是注释引用，但 OCR 文本不足以确认\
(2) 该页的 OCR 文本损坏严重",
        );
    }

    let json_payload = serde_json::to_string_pretty(&payload).unwrap_or_else(|_| String::new());

    format!(
        "/no_think\n下面是一个 FNM unresolved cluster。请只返回 JSON 数组，不要解释。\n本次只允许动作：{action_hint}。\n若信息足够明确，请直接输出可自动落地的动作，不要退回 needs_review；每条 reason 不超过 20 个词，禁止输出逐步分析。{extra_rules}\n\n{json_payload}"
    )
}

fn page_contexts_payload(request_cluster: &Value) -> Value {
    let items: Vec<Value> = request_cluster
        .get("page_contexts")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|item| {
            json!({
                "page_no": item.get("page_no").cloned().unwrap_or(Value::Null),
                "ocr_excerpt": trim_excerpt(
                    item.get("ocr_excerpt").and_then(|v| v.as_str()).unwrap_or(""),
                    LLM_REPAIR_PAGE_CONTEXT_PROMPT_CHARS,
                ),
            })
        })
        .collect();
    Value::Array(items)
}

fn matched_examples_payload(request_cluster: &Value) -> Value {
    let items: Vec<Value> = request_cluster
        .get("matched_examples")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|item| {
            json!({
                "note_item_id": item.get("note_item_id").cloned().unwrap_or(Value::Null),
                "anchor_id": item.get("anchor_id").cloned().unwrap_or(Value::Null),
                "marker": item.get("marker").cloned().unwrap_or(Value::Null),
                "note_excerpt": trim_excerpt(
                    item.get("note_excerpt").and_then(|v| v.as_str()).unwrap_or(""),
                    240,
                ),
                "anchor_excerpt": trim_excerpt(
                    item.get("anchor_excerpt").and_then(|v| v.as_str()).unwrap_or(""),
                    240,
                ),
            })
        })
        .collect();
    Value::Array(items)
}

fn unmatched_note_items_payload(request_cluster: &Value) -> Value {
    let items: Vec<Value> = request_cluster
        .get("unmatched_note_items")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|item| {
            json!({
                "note_item_id": item.get("note_item_id").cloned().unwrap_or(Value::Null),
                "marker": item.get("marker").cloned().unwrap_or(Value::Null),
                "page_no": item.get("page_no").cloned().unwrap_or(Value::Null),
                "source_text": trim_excerpt(
                    item.get("source_text").and_then(|v| v.as_str()).unwrap_or(""),
                    240,
                ),
            })
        })
        .collect();
    Value::Array(items)
}

fn unmatched_anchors_payload(request_cluster: &Value) -> Value {
    let items: Vec<Value> = request_cluster
        .get("unmatched_anchors")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|item| {
            let marker = item
                .get("normalized_marker")
                .filter(|v| !matches!(v, Value::Null))
                .cloned()
                .or_else(|| item.get("source_marker").cloned())
                .unwrap_or(Value::Null);
            json!({
                "anchor_id": item.get("anchor_id").cloned().unwrap_or(Value::Null),
                "marker": marker,
                "page_no": item.get("page_no").cloned().unwrap_or(Value::Null),
                "paragraph_index": item.get("paragraph_index").cloned().unwrap_or(Value::Null),
                "source_text": trim_excerpt(
                    item.get("source_text").and_then(|v| v.as_str()).unwrap_or(""),
                    240,
                ),
            })
        })
        .collect();
    Value::Array(items)
}

fn rebind_candidates_payload(request_cluster: &Value) -> Value {
    let items: Vec<Value> = request_cluster
        .get("rebind_candidates")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|item| {
            json!({
                "link_id": item.get("link_id").cloned().unwrap_or(Value::Null),
                "note_item_id": item.get("note_item_id").cloned().unwrap_or(Value::Null),
                "current_anchor_id": item.get("current_anchor_id").cloned().unwrap_or(Value::Null),
                "marker": item.get("marker").cloned().unwrap_or(Value::Null),
                "note_page_no": item.get("note_page_no").cloned().unwrap_or(Value::Null),
                "anchor_page_no": item.get("anchor_page_no").cloned().unwrap_or(Value::Null),
                "current_anchor_marker": item.get("current_anchor_marker").cloned().unwrap_or(Value::Null),
                "current_anchor_synthetic": item.get("current_anchor_synthetic").cloned().unwrap_or(Value::Null),
                "note_excerpt": trim_excerpt(
                    item.get("note_excerpt").and_then(|v| v.as_str()).unwrap_or(""),
                    240,
                ),
                "anchor_excerpt": trim_excerpt(
                    item.get("anchor_excerpt").and_then(|v| v.as_str()).unwrap_or(""),
                    240,
                ),
            })
        })
        .collect();
    Value::Array(items)
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_repair_system_prompt_contains_actions() {
        let prompt = repair_system_prompt();
        assert!(prompt.contains("match"));
        assert!(prompt.contains("synthesize_anchor"));
        assert!(
            !prompt.contains("synthesize_note_item"),
            "system prompt must not mention removed action"
        );
        assert!(prompt.contains("needs_review"));
    }

    #[test]
    fn test_trim_excerpt_short() {
        assert_eq!(trim_excerpt("  hello  world  ", 240), "hello world");
    }

    #[test]
    fn test_trim_excerpt_truncate() {
        let s = "a ".repeat(500);
        let out = trim_excerpt(&s, 240);
        assert!(out.ends_with("..."));
    }

    #[test]
    fn test_estimate_prompt_tokens_empty() {
        assert_eq!(estimate_prompt_tokens(""), 0);
    }

    #[test]
    fn test_estimate_prompt_tokens_ascii() {
        // "hello world" = 11 chars / 3.5 = ceil(3.14) = 4, + 16 overhead = 20
        let t = estimate_prompt_tokens("hello world");
        assert_eq!(t, 4 + 16);
    }

    #[test]
    fn test_estimate_prompt_tokens_cjk() {
        // 3 CJK + 16 overhead
        let t = estimate_prompt_tokens("中文字");
        assert_eq!(t, 3 + 16);
    }

    #[test]
    fn test_should_request_llm_for_cluster() {
        let req = json!({"allowed_actions": ["match", "ignore_ref"]});
        assert!(should_request_llm_for_cluster(&req));
        let req = json!({"allowed_actions": ["needs_review"]});
        assert!(!should_request_llm_for_cluster(&req));
    }

    #[test]
    fn test_should_attach_repair_images() {
        let req = json!({"allowed_actions": ["match", "synthesize_anchor"]});
        assert!(should_attach_repair_images(&req));
        let req = json!({"allowed_actions": ["match", "ignore_ref"]});
        assert!(!should_attach_repair_images(&req));
    }

    #[test]
    fn test_should_include_page_context_text() {
        // synthesize_anchor → 是（也需要 page_context）
        let req = json!({"allowed_actions": ["synthesize_anchor"]});
        assert!(should_include_page_context_text(&req));
        // ignore_ref → 是
        let req = json!({"allowed_actions": ["ignore_ref"]});
        assert!(should_include_page_context_text(&req));
        // match-only → 否
        let req = json!({"allowed_actions": ["match", "needs_review"]});
        assert!(!should_include_page_context_text(&req));
    }

    #[test]
    fn test_priority_pages_footnote() {
        let req = json!({
            "note_system": "footnote",
            "unmatched_anchors": [{"page_no": 5}, {"page_no": 10}],
            "unmatched_note_items": [{"page_no": 5}],
        });
        let pages = priority_pages_for_visual_context(&req);
        // dedup: 5,10
        assert_eq!(pages, vec![5, 10]);
    }

    #[test]
    fn test_slice_cluster_paired_with_body_text() {
        let cluster = json!({
            "cluster_id": "c1:r1:endnote",
            "note_system": "endnote",
            "unmatched_note_items": [
                {"note_item_id": "n1", "marker": "1", "page_no": 200, "source_text": "note text"}
            ],
            "unmatched_anchors": [
                {"anchor_id": "a1", "page_no": 5, "source_text": "anchor ctx"}
            ],
            "chapter_body_text": "This is body text. ".repeat(20),
        });
        let req = slice_cluster_for_request(&cluster, SliceCaps::default());
        let actions: Vec<String> = req["allowed_actions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert!(actions.contains(&"match".to_string()));
        assert!(actions.contains(&"synthesize_anchor".to_string()));
        assert_eq!(req["request_mode"], "paired");
    }

    #[test]
    fn test_slice_cluster_ref_only_visual() {
        let cluster = json!({
            "cluster_id": "c1:r1:endnote",
            "note_system": "footnote",
            "unmatched_anchors": [{"anchor_id": "a1", "page_no": 5}],
            "page_contexts": [{"page_no": 5, "ocr_excerpt": "ocr text"}],
        });
        let req = slice_cluster_for_request(&cluster, SliceCaps::default());
        assert_eq!(req["request_mode"], "ref_only_visual");
        let actions: Vec<String> = req["allowed_actions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        // synthesize_note_item 已移除（P0-2），ref_only_visual 只剩 ignore_ref + needs_review
        assert_eq!(actions, vec!["ignore_ref", "needs_review"]);
    }

    #[test]
    fn test_slice_cluster_review_only() {
        let cluster = json!({"cluster_id": "c1:r1:endnote", "note_system": "endnote"});
        let req = slice_cluster_for_request(&cluster, SliceCaps::default());
        assert_eq!(req["request_mode"], "review_only");
        let actions: Vec<String> = req["allowed_actions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(actions, vec!["needs_review"]);
    }

    #[test]
    fn test_slice_cluster_anchor_rebind() {
        let cluster = json!({
            "cluster_id": "c1:r1:endnote",
            "note_system": "endnote",
            "unmatched_anchors": [{"anchor_id": "a1", "page_no": 5}, {"anchor_id": "a2", "page_no": 6}],
            "rebind_candidates": [
                {"note_item_id": "n1", "current_anchor_id": "synthetic-1"}
            ],
            "page_contexts": [{"page_no": 5}],
        });
        let req = slice_cluster_for_request(&cluster, SliceCaps::default());
        assert_eq!(req["request_mode"], "anchor_rebind");
        let actions: Vec<String> = req["allowed_actions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        // synthesize_note_item 已移除（P0-2），anchor_rebind 返回 match/ignore_ref/needs_review
        assert!(!actions.contains(&"synthesize_note_item".to_string()));
        assert!(actions.contains(&"match".to_string()));
        assert!(actions.contains(&"ignore_ref".to_string()));
        assert!(actions.contains(&"needs_review".to_string()));
    }

    #[test]
    fn test_repair_user_prompt_contains_action_hint() {
        let cluster = json!({
            "cluster_id": "c1:r1:endnote",
            "chapter_title": "Chapter 1",
            "note_system": "endnote",
            "page_start": 5,
            "page_end": 5,
            "unmatched_anchors": [{"anchor_id": "a1", "page_no": 5}],
        });
        let prompt = repair_user_prompt(&cluster, SliceCaps::default());
        assert!(prompt.contains("/no_think"));
        assert!(prompt.contains("FNM unresolved cluster"));
        assert!(prompt.contains("ignore_ref"));
    }

    #[test]
    fn test_repair_user_prompt_synth_anchor_extra_rules() {
        let cluster = json!({
            "cluster_id": "c1:r1:endnote",
            "chapter_title": "Chapter 1",
            "note_system": "endnote",
            "page_start": 5,
            "page_end": 5,
            "unmatched_note_items": [{"note_item_id": "n1", "marker": "1", "page_no": 5}],
            "unmatched_anchors": [{"anchor_id": "a1", "page_no": 5}],
            "chapter_body_text": "This is body text. ".repeat(20),
        });
        let prompt = repair_user_prompt(&cluster, SliceCaps::default());
        assert!(prompt.contains("anchor_phrase"));
        assert!(prompt.contains("chapter_body_excerpt"));
    }
}
