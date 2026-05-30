//! ←→ FNM_RE/shared/token_counter.py
//! 统一 token 计数与用量追踪。
//!
//! 使用 `tokenizers` crate 加载 GPT-4o tokenizer，与 Python `tiktoken` 对齐。

use once_cell::sync::Lazy;
use std::collections::HashMap;
use std::sync::Mutex;
use tokenizers::Tokenizer;

const O200K_BASE_JSON: &[u8] = include_bytes!("../assets/o200k_base.json");

static O200K_BASE: Lazy<Tokenizer> =
    Lazy::new(|| Tokenizer::from_bytes(O200K_BASE_JSON).expect("load o200k_base tokenizer"));

/// 全局用量记录（线程安全）。
static USAGE_RECORDS: Lazy<Mutex<Vec<UsageRecord>>> = Lazy::new(|| Mutex::new(Vec::new()));

#[derive(Debug, Clone)]
pub struct UsageRecord {
    pub stage: String,
    pub model_id: String,
    pub provider: String,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub total_tokens: i64,
    pub request_count: i64,
    pub dur_ms: i64,
}

/// 计算文本的 token 数。与 Python `tiktoken.encoding_for_model("gpt-4o").encode(text)` 对齐。
pub fn count_tokens(text: &str) -> usize {
    O200K_BASE.encode(text, false).map(|e| e.len()).unwrap_or(0)
}

/// 记录一次 LLM 用量。与 Python `record_usage` 一致。
pub fn record_usage(record: UsageRecord) {
    if let Ok(mut records) = USAGE_RECORDS.lock() {
        records.push(record);
    }
}

/// 获取分阶段和分模型的用量汇总。
/// 与 Python `get_usage_summary` 一致。
///
/// 注：lock 中毒（其他线程 panic 持锁）时返回空 summary 而非自身 panic。
/// LLM 路径不应因 token 统计副作用 panic（AGENTS.md §9）。
pub fn get_usage_summary() -> serde_json::Value {
    let records = match USAGE_RECORDS.lock() {
        Ok(g) => g,
        Err(_) => {
            return serde_json::json!({
                "by_stage": {},
                "by_model": {},
                "total": {
                    "request_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "_error": "USAGE_RECORDS lock poisoned",
            });
        }
    };
    let mut by_stage: HashMap<String, HashMap<String, i64>> = HashMap::new();
    let mut by_model: HashMap<String, HashMap<String, i64>> = HashMap::new();
    let mut total: HashMap<&str, i64> = [
        ("request_count", 0),
        ("prompt_tokens", 0),
        ("completion_tokens", 0),
        ("total_tokens", 0),
    ]
    .into();

    let metric_fields = [
        "request_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    ];

    for c in records.iter() {
        let stage_entry = by_stage.entry(c.stage.clone()).or_insert_with(|| {
            HashMap::from([
                ("request_count".into(), 0),
                ("prompt_tokens".into(), 0),
                ("completion_tokens".into(), 0),
                ("total_tokens".into(), 0),
            ])
        });
        for key in &metric_fields {
            let v = match *key {
                "request_count" => c.request_count,
                "prompt_tokens" => c.prompt_tokens,
                "completion_tokens" => c.completion_tokens,
                "total_tokens" => c.total_tokens,
                _ => 0,
            };
            *stage_entry.entry((*key).to_string()).or_insert(0) += v;
        }
        let model_entry = by_model.entry(c.model_id.clone()).or_insert_with(|| {
            HashMap::from([
                ("request_count".into(), 0),
                ("prompt_tokens".into(), 0),
                ("completion_tokens".into(), 0),
                ("total_tokens".into(), 0),
            ])
        });
        for key in &metric_fields {
            let v = match *key {
                "request_count" => c.request_count,
                "prompt_tokens" => c.prompt_tokens,
                "completion_tokens" => c.completion_tokens,
                "total_tokens" => c.total_tokens,
                _ => 0,
            };
            *model_entry.entry((*key).to_string()).or_insert(0) += v;
        }
        for key in &metric_fields {
            let v = match *key {
                "request_count" => c.request_count,
                "prompt_tokens" => c.prompt_tokens,
                "completion_tokens" => c.completion_tokens,
                "total_tokens" => c.total_tokens,
                _ => 0,
            };
            *total.entry(*key).or_insert(0) += v;
        }
    }

    serde_json::json!({
        "by_stage": by_stage,
        "by_model": by_model,
        "total": total,
    })
}

/// 获取所有用量记录副本。与 Python 全局 `_counts` 等价。
pub fn get_usage_records() -> Vec<UsageRecord> {
    match USAGE_RECORDS.lock() {
        Ok(g) => g.clone(),
        Err(_) => Vec::new(),
    }
}

/// 清空用量记录。与 Python `clear_usage` 一致。
pub fn clear_usage() {
    if let Ok(mut records) = USAGE_RECORDS.lock() {
        records.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn count_tokens_returns_nonzero() {
        let n = count_tokens("Hello world");
        assert!(n > 0);
    }

    #[test]
    fn count_tokens_empty() {
        let n = count_tokens("");
        assert_eq!(n, 0);
    }

    // 全局 USAGE_RECORDS 的测试合并为单函数：内部按段串行（每段先 clear_usage），
    // 避免 cargo 并行执行下跨测试污染全局状态，从而恢复精确断言（不再用 >= / any
    // 弹性绕过）。本 crate 内仅这些测试触碰全局用量状态——record_usage 的其他调用
    // 在 fnm-llm-repair，属不同测试进程，不会干扰。
    #[test]
    fn usage_records_global_state() {
        // 1. record 后 summary.total 精确
        clear_usage();
        record_usage(UsageRecord {
            stage: "test".into(),
            model_id: "gpt-4o".into(),
            provider: "openai".into(),
            prompt_tokens: 100,
            completion_tokens: 50,
            total_tokens: 150,
            request_count: 1,
            dur_ms: 200,
        });
        let summary = get_usage_summary();
        assert_eq!(summary["total"]["prompt_tokens"], 100);
        assert_eq!(summary["total"]["completion_tokens"], 50);

        // 2. clear 后为空
        clear_usage();
        assert!(get_usage_records().is_empty());

        // 3. record 后恰好 1 条，字段精确
        clear_usage();
        record_usage(UsageRecord {
            stage: "records_test_stage".into(),
            model_id: "gpt-4o".into(),
            provider: "openai".into(),
            prompt_tokens: 200,
            completion_tokens: 100,
            total_tokens: 300,
            request_count: 2,
            dur_ms: 500,
        });
        let records = get_usage_records();
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].stage, "records_test_stage");
        assert_eq!(records[0].prompt_tokens, 200);

        // 4. by_stage 聚合精确
        clear_usage();
        for (stage, prompt, completion, total) in [
            ("summary_stage_a", 10, 5, 15),
            ("summary_stage_a", 20, 10, 30),
            ("summary_stage_b", 5, 5, 10),
        ] {
            record_usage(UsageRecord {
                stage: stage.into(),
                model_id: "m".into(),
                provider: "openai".into(),
                prompt_tokens: prompt,
                completion_tokens: completion,
                total_tokens: total,
                request_count: 1,
                dur_ms: 100,
            });
        }
        let summary = get_usage_summary();
        let by_stage = summary.get("by_stage").unwrap();
        let sa = by_stage.get("summary_stage_a").unwrap();
        assert_eq!(sa["request_count"].as_i64().unwrap(), 2);
        assert_eq!(sa["prompt_tokens"].as_i64().unwrap(), 30);
        let sb = by_stage.get("summary_stage_b").unwrap();
        assert_eq!(sb["request_count"].as_i64().unwrap(), 1);

        // 5. clear 重置
        clear_usage();
        record_usage(UsageRecord {
            stage: "clear_test_stage".into(),
            model_id: "m".into(),
            provider: "p".into(),
            prompt_tokens: 1,
            completion_tokens: 1,
            total_tokens: 2,
            request_count: 1,
            dur_ms: 10,
        });
        assert!(!get_usage_records().is_empty());
        clear_usage();
        assert!(get_usage_records().is_empty());
    }

    #[test]
    fn count_tokens_cjk_nonzero() {
        let n = count_tokens("你好世界");
        assert!(n > 0);
    }
}
