//! ←→ FNM_RE/shared/token_counter.py
//! Trace 文件写入：`dump_traces` / `write_summary_traces`。

use std::collections::HashMap;
use std::path::Path;

/// 将全局 USAGE_RECORDS 逐条写入 llm_traces/ 目录。
///
/// ←→ Python `dump_traces()`
pub fn dump_traces(example_dir: &str, doc_id: &str) -> Result<i64, std::io::Error> {
    let trace_dir = Path::new(example_dir).join("llm_traces");
    std::fs::create_dir_all(&trace_dir)?;

    let records = fnm_core::token_counter::get_usage_records();
    let mut stage_counters: HashMap<String, i64> = HashMap::new();
    let mut written: i64 = 0;

    for c in &records {
        let stage = c.stage.clone();
        let seq = stage_counters.entry(stage.clone()).or_insert(0);
        *seq += 1;
        let path = trace_dir.join(format!("{}.{:03}.json", stage, seq));

        let trace = serde_json::json!({
            "stage": stage,
            "model_id": c.model_id,
            "provider": c.provider,
            "usage": {
                "prompt_tokens": c.prompt_tokens,
                "completion_tokens": c.completion_tokens,
                "total_tokens": c.total_tokens,
            },
            "timing": {"duration_ms": c.dur_ms},
            "doc_id": doc_id,
        });

        if let Ok(content) = serde_json::to_string_pretty(&trace) {
            std::fs::write(&path, content)?;
            written += 1;
        }
    }

    Ok(written)
}

/// 将 usage_summary 按阶段写入 llm_traces/ 目录（每阶段一个文件）。
///
/// ←→ Python `write_summary_traces()`
pub fn write_summary_traces(
    example_dir: &str,
    usage_summary: &serde_json::Value,
    doc_id: &str,
) -> Result<i64, std::io::Error> {
    let trace_dir = Path::new(example_dir).join("llm_traces");
    std::fs::create_dir_all(&trace_dir)?;

    let by_stage = usage_summary
        .get("by_stage")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();

    let mut written: i64 = 0;

    for (stage, info) in &by_stage {
        let request_count = info
            .get("request_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        if request_count == 0 {
            continue;
        }

        let path = trace_dir.join(format!("{}.summary.json", stage));
        let trace = serde_json::json!({
            "stage": stage,
            "usage": {
                "request_count": request_count,
                "prompt_tokens": info.get("prompt_tokens").and_then(|v| v.as_i64()).unwrap_or(0),
                "completion_tokens": info.get("completion_tokens").and_then(|v| v.as_i64()).unwrap_or(0),
                "total_tokens": info.get("total_tokens").and_then(|v| v.as_i64()).unwrap_or(0),
            },
            "doc_id": doc_id,
        });

        if let Ok(content) = serde_json::to_string_pretty(&trace) {
            std::fs::write(&path, content)?;
            written += 1;
        }
    }

    Ok(written)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dump_traces_without_setup_does_not_panic() {
        let dir = tempfile::tempdir().unwrap();
        // 全局记录可能被并行测试写入；这里只验证无预置状态时不 panic。
        let _written = dump_traces(dir.path().to_str().unwrap(), "test-doc");
    }

    #[test]
    fn dump_traces_writes_files() {
        fnm_core::token_counter::clear_usage();
        fnm_core::token_counter::record_usage(fnm_core::token_counter::UsageRecord {
            stage: "dump_test_stage".into(),
            model_id: "gpt-4o".into(),
            provider: "openai".into(),
            prompt_tokens: 100,
            completion_tokens: 50,
            total_tokens: 150,
            request_count: 1,
            dur_ms: 300,
        });
        let dir = tempfile::tempdir().unwrap();
        let written = dump_traces(dir.path().to_str().unwrap(), "test-doc").unwrap();
        assert!(written >= 1);
        let trace_dir = dir.path().join("llm_traces");
        assert!(trace_dir.join("dump_test_stage.001.json").exists());
    }

    #[test]
    fn write_summary_traces_basic() {
        let dir = tempfile::tempdir().unwrap();
        let summary = serde_json::json!({
            "by_stage": {
                "repair": {
                    "request_count": 2,
                    "prompt_tokens": 200,
                    "completion_tokens": 100,
                    "total_tokens": 300
                }
            }
        });
        let written =
            write_summary_traces(dir.path().to_str().unwrap(), &summary, "doc-1").unwrap();
        assert_eq!(written, 1);
        let trace_dir = dir.path().join("llm_traces");
        assert!(trace_dir.join("repair.summary.json").exists());
    }

    #[test]
    fn write_summary_traces_zero_requests_skipped() {
        let dir = tempfile::tempdir().unwrap();
        let summary = serde_json::json!({
            "by_stage": {
                "skipped_stage": {
                    "request_count": 0,
                    "prompt_tokens": 0
                }
            }
        });
        let written =
            write_summary_traces(dir.path().to_str().unwrap(), &summary, "doc-1").unwrap();
        assert_eq!(written, 0);
    }

    #[test]
    fn write_summary_traces_empty_summary() {
        let dir = tempfile::tempdir().unwrap();
        let summary = serde_json::json!({});
        let written =
            write_summary_traces(dir.path().to_str().unwrap(), &summary, "doc-1").unwrap();
        assert_eq!(written, 0);
    }
}
