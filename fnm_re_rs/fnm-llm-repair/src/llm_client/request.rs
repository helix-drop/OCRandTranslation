//! ←→ Python `request_llm_repair_actions` (llm_repair.py:1356-1641) + 关联 provider 调用。
//!
//! 顶层流程：
//! 1. resolve 主/备用 model spec
//! 2. slice cluster 到请求容量并确定 allowed_actions
//! 3. 检查是否需要请求 LLM（all needs_review → 跳过）
//! 4. 附加截图（synthesize 模式）+ 组装 user_content
//! 5. 多模型 fallback：HTTP POST，捕获内容审核错误尝试剥离图片重试
//! 6. 解析响应、计算 usage_event、emit trace

use anyhow::Result;
use fnm_core::vision::HTTP_CLIENT;
use once_cell::sync::Lazy;
use serde_json::{json, Map, Value};
use std::time::{Duration, Instant};
use tokio::sync::Semaphore;

use crate::constants::{
    GLM46V_CONTEXT_TOKENS, GLM46V_MAX_IN_FLIGHT_REQUESTS, GLM46V_MAX_RETRY_ATTEMPTS,
    LLM_REPAIR_MAX_OUTPUT_TOKENS, LLM_REPAIR_USAGE_STAGE,
};
use crate::page_context::{attach_repair_images_to_contexts, page_context_trace_rows};
use crate::prompt_builder::{
    repair_system_prompt, repair_user_prompt, should_attach_repair_images,
    should_request_llm_for_cluster, slice_cluster_for_request, SliceCaps,
};
use crate::response_parser::parse_llm_repair_actions;
use crate::usage::{coerce_usage_int, compact_usage_context};

use super::error::classify_provider_error;
use super::{
    compact_cluster_for_trace, emit_llm_trace, request_metrics_for_cluster,
    resolve_all_repair_model_args, resolve_repair_model_args, token_accounting_for_request,
    RepairCallResult, RepairRequestParams, TraceCallback,
};

static GLM46V_REQUEST_GATE: Lazy<Semaphore> =
    Lazy::new(|| Semaphore::new(GLM46V_MAX_IN_FLIGHT_REQUESTS));

fn model_supports_repair_images(model_args: &Value) -> bool {
    model_args
        .get("supports_vision")
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

/// ←→ Python `request_llm_repair_actions` (llm_repair.py:1356-1641)
///
/// Async 顶层 LLM 修补请求；同步调用方可用 `tokio::runtime::Runtime::block_on`。
pub async fn request_llm_repair_actions(
    params: RepairRequestParams<'_>,
) -> Result<RepairCallResult> {
    let model_args_provided = params.model_args.is_some();
    let mut resolved_args = match params.model_args {
        Some(args) => args,
        None => resolve_repair_model_args()?,
    };
    let mut fallback_model_args: Vec<Value> = Vec::new();
    if !model_args_provided {
        let all_args = resolve_all_repair_model_args()?;
        if all_args.len() > 1 {
            fallback_model_args = all_args.into_iter().skip(1).collect();
        }
    }
    // 清掉 test-only 标记，避免污染 trace
    if let Some(obj) = resolved_args.as_object_mut() {
        obj.remove("__from_user");
    }

    let caps = SliceCaps {
        max_matched_examples: params.max_matched_examples,
        max_unmatched_note_items: params.max_unmatched_note_items,
        max_unmatched_anchors: params.max_unmatched_anchors,
    };
    let mut request_cluster = slice_cluster_for_request(params.cluster, caps);

    let model_info = json!({
        "provider": resolved_args.get("provider").and_then(|v| v.as_str()).unwrap_or("qwen"),
        "model_id": resolved_args.get("model_id").and_then(|v| v.as_str()).unwrap_or(""),
        "base_url": resolved_args.get("base_url").and_then(|v| v.as_str()).unwrap_or(""),
    });

    // 跳过路径：cluster 仅含 needs_review → 不请求 LLM
    if !should_request_llm_for_cluster(&request_cluster) {
        return Ok(build_skipped_result(
            params.cluster,
            &request_cluster,
            &model_info,
            params.trace_callback,
        ));
    }

    // 附加截图
    if should_attach_repair_images(&request_cluster) && model_supports_repair_images(&resolved_args)
    {
        let contexts = request_cluster
            .get("page_contexts")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let with_images =
            attach_repair_images_to_contexts(&contexts, &request_cluster, params.renderer);
        request_cluster["page_contexts"] = Value::Array(with_images);
    }

    let system_prompt = repair_system_prompt();
    let user_prompt = repair_user_prompt(&request_cluster, caps);

    let mut user_content: Vec<Value> = vec![json!({"type": "text", "text": user_prompt})];
    for context in request_cluster
        .get("page_contexts")
        .and_then(|v| v.as_array())
        .unwrap_or(&Vec::new())
    {
        let image_url = context
            .get("image_url")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if !image_url.is_empty() {
            user_content.push(json!({
                "type": "image_url",
                "image_url": {"url": image_url},
            }));
        }
    }

    let started_metrics = request_metrics_for_cluster(
        params.cluster,
        &request_cluster,
        &system_prompt,
        &user_prompt,
        false,
        false,
        "",
    );
    let started_trace = build_started_trace(
        params.cluster,
        &request_cluster,
        &model_info,
        &started_metrics,
    );
    emit_llm_trace(params.trace_callback, &started_trace);

    // 多模型 fallback 主循环
    let mut all_model_args = vec![resolved_args.clone()];
    all_model_args.append(&mut fallback_model_args);
    let started = Instant::now();
    let (body, image_refused) = run_fallback_loop(
        &all_model_args,
        &system_prompt,
        &user_content,
        &mut resolved_args,
        params.trace_callback,
        &started_trace,
        started,
    )
    .await?;

    // 解析响应
    let usage = build_usage_dict(
        body.get("usage")
            .and_then(|u| u.get("prompt_tokens"))
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        body.get("usage")
            .and_then(|u| u.get("completion_tokens"))
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        body.get("usage")
            .and_then(|u| u.get("total_tokens"))
            .and_then(|v| v.as_i64()),
    );
    let raw_text = body
        .get("choices")
        .and_then(|v| v.get(0))
        .and_then(|v| v.get("message"))
        .and_then(|v| v.get("content"))
        .map(extract_message_text)
        .unwrap_or_default();
    let parsed_actions = parse_llm_repair_actions(&raw_text);
    let duration_ms = started.elapsed().as_millis() as i64;

    let usage_event = json!({
        "stage": LLM_REPAIR_USAGE_STAGE,
        "provider": resolved_args.get("provider").and_then(|v| v.as_str()).unwrap_or("qwen"),
        "model_id": resolved_args.get("model_id").and_then(|v| v.as_str()).unwrap_or(""),
        "request_count": coerce_usage_int(&usage["request_count"]),
        "prompt_tokens": coerce_usage_int(&usage["prompt_tokens"]),
        "completion_tokens": coerce_usage_int(&usage["completion_tokens"]),
        "total_tokens": coerce_usage_int(&usage["total_tokens"]),
        "doc_id": params.doc_id.trim(),
        "slug": params.slug.trim(),
        "context": Value::Object(compact_usage_context(Some(&json!({
            "cluster_id": params.cluster.get("cluster_id").and_then(|v| v.as_str()).unwrap_or(""),
            "request_mode": request_cluster.get("request_mode").and_then(|v| v.as_str()).unwrap_or(""),
        })))),
    });

    let request_metrics = request_metrics_for_cluster(
        params.cluster,
        &request_cluster,
        &system_prompt,
        &user_prompt,
        image_refused,
        false,
        "",
    );
    let token_accounting =
        token_accounting_for_request(Some(&usage), Some(&request_metrics), false, "");
    // trace 通过 &refs 构造一个独立副本（Python 端 trace 也是 snapshot）；
    // 这里允许 token_accounting / raw_text / usage / parsed_actions 各一次 clone，
    // 因为 result 与 trace 在概念上是独立的数据 owner。
    let parsed_actions_value = serde_json::to_value(&parsed_actions).unwrap_or(Value::Null);
    let llm_trace = json!({
        "stage": LLM_REPAIR_USAGE_STAGE,
        "reason_for_request": "根据 unresolved cluster 请求 LLM 给出注释链接修补建议",
        "model": model_info,
        "request_prompt": {"system": system_prompt, "user": user_prompt},
        "request_content": {
            "cluster": compact_cluster_for_trace(&request_cluster),
            "page_contexts": page_context_trace_rows(
                request_cluster.get("page_contexts").and_then(|v| v.as_array()).unwrap_or(&Vec::new())
            ),
        },
        "request_context_summary": {
            "cluster_id": params.cluster.get("cluster_id").and_then(|v| v.as_str()).unwrap_or(""),
            "request_mode": request_cluster.get("request_mode").and_then(|v| v.as_str()).unwrap_or(""),
            "page_context_count": request_cluster.get("page_contexts").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            "image_refused": image_refused,
        },
        "token_accounting": token_accounting.clone(),
        "response_raw_text": raw_text.clone(),
        "response_parsed": parsed_actions_value.clone(),
        "derived_truth": {"parsed_actions": parsed_actions_value},
        "usage": usage.clone(),
        "timing": {"duration_ms": duration_ms},
    });
    emit_llm_trace(params.trace_callback, &llm_trace);

    Ok(RepairCallResult {
        raw_text,
        usage,
        usage_event,
        actions: parsed_actions,
        request_metrics,
        token_accounting,
        llm_trace,
        skipped: false,
    })
}

/// 构造 skipped 路径的完整 RepairCallResult。
///
/// ←→ Python `request_llm_repair_actions` 行 1385-1430 的 skipped 分支
fn build_skipped_result(
    cluster: &Value,
    request_cluster: &Value,
    model_info: &Value,
    trace_callback: Option<TraceCallback<'_>>,
) -> RepairCallResult {
    let metrics = request_metrics_for_cluster(
        cluster,
        request_cluster,
        "",
        "",
        false,
        true,
        "no_actionable_auto_repair",
    );
    let token_accounting = token_accounting_for_request(
        Some(&Value::Object(Map::new())),
        Some(&metrics),
        true,
        "no_actionable_auto_repair",
    );
    let trace = json!({
        "stage": format!("{LLM_REPAIR_USAGE_STAGE}.skipped"),
        "reason_for_request": "该 cluster 只有 needs_review 动作，真实流程无人工 review，跳过 LLM 请求",
        "model": model_info,
        "request_content": {
            "cluster": compact_cluster_for_trace(request_cluster),
            "page_contexts": page_context_trace_rows(
                request_cluster.get("page_contexts").and_then(|v| v.as_array()).unwrap_or(&Vec::new())
            ),
        },
        "request_context_summary": {
            "cluster_id": cluster.get("cluster_id").and_then(|v| v.as_str()).unwrap_or(""),
            "request_mode": request_cluster.get("request_mode").and_then(|v| v.as_str()).unwrap_or(""),
            "page_context_count": request_cluster.get("page_contexts").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            "skipped": true,
            "skip_reason": "no_actionable_auto_repair",
        },
        "request_metrics": metrics.clone(),
        "token_accounting": token_accounting.clone(),
        "response_raw_text": "",
        "response_parsed": [],
        "derived_truth": {"parsed_actions": []},
        "usage": {},
        "timing": {"duration_ms": 0},
    });
    emit_llm_trace(trace_callback, &trace);
    RepairCallResult {
        raw_text: String::new(),
        usage: json!({}),
        usage_event: json!({}),
        actions: vec![],
        request_metrics: metrics,
        token_accounting,
        llm_trace: trace,
        skipped: true,
    }
}

/// 构造 started 阶段的 trace（用于 emit started + 后续 failed fallback 复用）。
fn build_started_trace(
    cluster: &Value,
    request_cluster: &Value,
    model_info: &Value,
    started_metrics: &Value,
) -> Value {
    let image_count = request_cluster
        .get("page_contexts")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter(|c| {
                    c.get("image_url")
                        .and_then(|v| v.as_str())
                        .map(|s| !s.trim().is_empty())
                        .unwrap_or(false)
                })
                .count()
        })
        .unwrap_or(0);
    json!({
        "stage": format!("{LLM_REPAIR_USAGE_STAGE}.started"),
        "reason_for_request": "开始请求 LLM 修补 unresolved cluster",
        "model": model_info,
        "request_content": {
            "cluster": compact_cluster_for_trace(request_cluster),
            "page_contexts": page_context_trace_rows(
                request_cluster.get("page_contexts").and_then(|v| v.as_array()).unwrap_or(&Vec::new())
            ),
        },
        "request_context_summary": {
            "cluster_id": cluster.get("cluster_id").and_then(|v| v.as_str()).unwrap_or(""),
            "request_mode": request_cluster.get("request_mode").and_then(|v| v.as_str()).unwrap_or(""),
            "page_context_count": request_cluster.get("page_contexts").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            "image_count": image_count,
        },
        "request_metrics": started_metrics.clone(),
        "token_accounting": token_accounting_for_request(None, Some(started_metrics), false, ""),
        "usage": {},
    })
}

/// 多模型 fallback 循环：返回 `(body, image_refused)` 或失败时上抛。
///
/// ←→ Python `request_llm_repair_actions` 行 1485-1565 的 for 循环
async fn run_fallback_loop(
    all_model_args: &[Value],
    system_prompt: &str,
    user_content: &[Value],
    resolved_args: &mut Value,
    trace_callback: Option<TraceCallback<'_>>,
    started_trace: &Value,
    started: Instant,
) -> Result<(Value, bool)> {
    let mut image_refused = false;
    let mut last_error: Option<anyhow::Error> = None;

    for (model_attempt, current_args) in all_model_args.iter().enumerate() {
        match call_provider_with_policy(current_args, system_prompt, user_content).await {
            Ok(body) => {
                if model_attempt > 0 {
                    *resolved_args = current_args.clone();
                }
                return Ok((body, image_refused));
            }
            Err(err) => {
                let msg = err.to_string();
                let lowered = msg.to_lowercase();
                // ←→ Python `is_moderation` (llm_repair.py:1514-1518)：DashScope 用
                // `data_inspection_failed` / `DataInspectionFailed`；OpenAI/Azure
                // 用 `content_filter` / `review`。Python 端 `is_moderation` 用于"内容审核错误"
                // 触发降级；剥图重试仅 `data_inspection*` 走（与图相关的过滤通常含图错）。
                let moderation = lowered.contains("data_inspection_failed")
                    || msg.contains("DataInspectionFailed")
                    || lowered.contains("content_filter")
                    || lowered.contains("review");
                let has_image = user_content
                    .iter()
                    .any(|c| c.get("type").and_then(|v| v.as_str()) == Some("image_url"));

                if moderation && has_image {
                    image_refused = true;
                    let text_only: Vec<Value> = user_content
                        .iter()
                        .filter(|c| c.get("type").and_then(|v| v.as_str()) != Some("image_url"))
                        .cloned()
                        .collect();
                    match call_provider_with_policy(current_args, system_prompt, &text_only).await {
                        Ok(body) => {
                            if model_attempt > 0 {
                                *resolved_args = current_args.clone();
                            }
                            return Ok((body, image_refused));
                        }
                        Err(e2) => {
                            last_error = Some(e2);
                            if model_attempt + 1 < all_model_args.len() {
                                continue;
                            }
                            let err = last_error.unwrap();
                            emit_failed_trace(trace_callback, started_trace, started, &err);
                            return Err(err);
                        }
                    }
                } else if model_attempt + 1 < all_model_args.len() {
                    // 内容审核错误 / 其它错误都尝试降级到下一个 model
                    last_error = Some(err);
                    continue;
                } else {
                    emit_failed_trace(trace_callback, started_trace, started, &err);
                    return Err(err);
                }
            }
        }
    }

    let final_err = last_error.unwrap_or_else(|| anyhow::anyhow!("all models failed"));
    Err(final_err)
}

/// emit failed trace（基于 started_trace 的副本 + 错误信息覆盖）。
///
/// ←→ Python `request_llm_repair_actions` 行 1537-1546 + 1555-1564
fn emit_failed_trace(
    trace_callback: Option<TraceCallback<'_>>,
    started_trace: &Value,
    started: Instant,
    err: &anyhow::Error,
) {
    let mut failed = started_trace.clone();
    if let Value::Object(obj) = &mut failed {
        obj.insert(
            "stage".to_string(),
            Value::String(format!("{LLM_REPAIR_USAGE_STAGE}.failed")),
        );
        obj.insert(
            "reason_for_request".to_string(),
            Value::String("LLM repair 请求失败（所有模型已尝试）".to_string()),
        );
        obj.insert("error".to_string(), Value::String(err.to_string()));
        obj.insert(
            "timing".to_string(),
            json!({"duration_ms": started.elapsed().as_millis() as i64}),
        );
    }
    emit_llm_trace(trace_callback, &failed);
}

/// 单次 provider 调用：组装 payload + 发 HTTP + 解析 body。
///
/// ←→ Python `request_llm_repair_actions::_do_call` (llm_repair.py:1489-1503)
fn is_glm46v(args: &Value) -> bool {
    args.get("provider").and_then(|v| v.as_str()) == Some("glm")
        && args.get("model_id").and_then(|v| v.as_str()) == Some("glm-4.6v")
}

fn validate_glm46v_text_budget(system_prompt: &str, user_content: &[Value]) -> Result<()> {
    let user_text = user_content
        .iter()
        .filter_map(|content| {
            if content.get("type").and_then(|v| v.as_str()) == Some("text") {
                content.get("text").and_then(|v| v.as_str())
            } else {
                None
            }
        })
        .collect::<Vec<_>>()
        .join("\n");
    let estimated_input = crate::prompt_builder::estimate_prompt_tokens(system_prompt)
        + crate::prompt_builder::estimate_prompt_tokens(&user_text);
    let reserved_output = LLM_REPAIR_MAX_OUTPUT_TOKENS;
    if estimated_input + reserved_output > GLM46V_CONTEXT_TOKENS {
        anyhow::bail!(
            "GLM-4.6V 文本上下文超过官方 128K 窗口：estimated_input={estimated_input}, max_output={reserved_output}"
        );
    }
    Ok(())
}

async fn call_provider_with_policy(
    args: &Value,
    system_prompt: &str,
    user_content: &[Value],
) -> Result<Value> {
    let glm46v = is_glm46v(args);
    if glm46v {
        validate_glm46v_text_budget(system_prompt, user_content)?;
    }
    let max_retries = if glm46v { GLM46V_MAX_RETRY_ATTEMPTS } else { 0 };
    for retry_no in 0..=max_retries {
        let result = if glm46v {
            let _permit = GLM46V_REQUEST_GATE.acquire().await?;
            call_provider(args, system_prompt, user_content).await
        } else {
            call_provider(args, system_prompt, user_content).await
        };
        match result {
            Ok(body) => return Ok(body),
            Err(err) if retry_no < max_retries => {
                let retryable = err
                    .downcast_ref::<super::ProviderError>()
                    .is_some_and(super::ProviderError::is_retryable);
                if !retryable {
                    return Err(err);
                }
                let provider_wait = err
                    .downcast_ref::<super::ProviderError>()
                    .and_then(super::ProviderError::retry_after_seconds);
                let seconds = provider_wait
                    .unwrap_or(2_f64.powi(retry_no as i32))
                    .max(1.0);
                tokio::time::sleep(Duration::from_secs_f64(seconds)).await;
            }
            Err(err) => return Err(err),
        }
    }
    anyhow::bail!("GLM-4.6V 请求退避循环意外退出")
}

async fn call_provider(args: &Value, system_prompt: &str, user_content: &[Value]) -> Result<Value> {
    let model_id = args.get("model_id").and_then(|v| v.as_str()).unwrap_or("");
    let base_url = args
        .get("base_url")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim_end_matches('/')
        .to_string();
    let api_key = args.get("api_key").and_then(|v| v.as_str()).unwrap_or("");
    let provider = args
        .get("provider")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_lowercase();
    let mut request_overrides = args
        .get("request_overrides")
        .cloned()
        .unwrap_or(Value::Null);
    // 默认 qwen 关闭 thinking
    let overrides_empty = match &request_overrides {
        Value::Null => true,
        Value::Object(map) => map.is_empty(),
        _ => false,
    };
    if overrides_empty && provider == "qwen" {
        request_overrides = json!({"extra_body": {"enable_thinking": false}});
    }

    let mut payload = json!({
        "model": model_id,
        "max_tokens": LLM_REPAIR_MAX_OUTPUT_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    });
    merge_overrides_into_payload(&mut payload, &request_overrides);

    let response = match HTTP_CLIENT
        .post(format!("{base_url}/chat/completions"))
        .bearer_auth(api_key)
        .json(&payload)
        .timeout(Duration::from_secs(60))
        .send()
        .await
    {
        Ok(resp) => resp,
        Err(e) => {
            // 网络层错误（DNS / connect / timeout）：reqwest 给不出 status，靠消息识别 timeout。
            let msg = e.to_string();
            let status = e.status().map(|s| s.as_u16());
            return Err(classify_provider_error(status, None, None, &msg).into());
        }
    };

    let status_code = response.status().as_u16();
    let retry_after = response
        .headers()
        .get(reqwest::header::RETRY_AFTER)
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string());
    let body_text = match response.text().await {
        Ok(t) => t,
        Err(e) => {
            let msg = e.to_string();
            return Err(classify_provider_error(
                Some(status_code),
                retry_after.as_deref(),
                None,
                &msg,
            )
            .into());
        }
    };
    let body: Value = serde_json::from_str(&body_text).unwrap_or_else(|_| {
        // 服务端返回非 JSON 时构造一个最小 error 包装，方便分类器抽取 message
        serde_json::json!({"error": {"message": body_text}})
    });
    if !(200..300).contains(&status_code) {
        let err_msg = body
            .get("error")
            .and_then(|e| e.get("message"))
            .and_then(|v| v.as_str())
            .or_else(|| {
                let trimmed = body_text.trim();
                if trimmed.is_empty() {
                    None
                } else {
                    Some(trimmed)
                }
            })
            .unwrap_or("provider returned non-2xx")
            .to_string();
        return Err(classify_provider_error(
            Some(status_code),
            retry_after.as_deref(),
            Some(&body),
            &err_msg,
        )
        .into());
    }
    Ok(body)
}

/// 把 `request_overrides` deep-merge 进 payload。Python `_merge_overrides_into_chat_kwargs` 行为简化版：
/// object 字段做 1 层合并；其它类型直接覆盖。
fn merge_overrides_into_payload(payload: &mut Value, overrides: &Value) {
    let Value::Object(overrides_obj) = overrides else {
        return;
    };
    let Some(payload_obj) = payload.as_object_mut() else {
        return;
    };
    for (key, value) in overrides_obj.iter() {
        if let Some(existing) = payload_obj.get_mut(key) {
            if let (Value::Object(e), Value::Object(n)) = (existing, value) {
                for (k2, v2) in n {
                    e.insert(k2.clone(), v2.clone());
                }
                continue;
            }
        }
        payload_obj.insert(key.clone(), value.clone());
    }
}

/// ←→ Python `_build_usage`（translation/translator 内部，llm_repair.py:1570 调用）
fn build_usage_dict(prompt: i64, completion: i64, total: Option<i64>) -> Value {
    let total = total.unwrap_or(prompt + completion);
    json!({
        "request_count": 1,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    })
}

/// ←→ Python `_extract_openai_message_text`（translation/translator 内部，llm_repair.py:1577 调用）
fn extract_message_text(content: &Value) -> String {
    match content {
        Value::String(s) => s.clone(),
        Value::Array(arr) => {
            let mut buf = String::new();
            for part in arr {
                if let Some(text) = part.get("text").and_then(|v| v.as_str()) {
                    buf.push_str(text);
                }
            }
            buf
        }
        _ => String::new(),
    }
}

// ── 测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::page_context::NoopRenderer;

    #[tokio::test]
    async fn test_request_skips_when_only_review() {
        // 无 unmatched → review_only → skipped trace + 不发请求
        let cluster = json!({
            "cluster_id": "c1:r1:endnote",
            "note_system": "endnote",
        });
        let renderer = NoopRenderer;
        // 直接传入 model_args 避免读取真实 config
        let args = json!({
            "provider": "qwen",
            "model_id": "qwen-test",
            "api_key": "sk-test",
            "base_url": "http://127.0.0.1:9",
            "request_overrides": {},
            "display_label": "test",
            "__from_user": true,
        });
        let params = RepairRequestParams {
            cluster: &cluster,
            model_args: Some(args),
            max_matched_examples: None,
            max_unmatched_note_items: None,
            max_unmatched_anchors: None,
            doc_id: "doc",
            slug: "slug",
            trace_callback: None,
            renderer: &renderer,
        };
        let result = request_llm_repair_actions(params).await.unwrap();
        assert!(result.skipped);
        assert!(result.actions.is_empty());
        assert_eq!(result.raw_text, "");
    }

    #[test]
    fn test_extract_message_text_string() {
        assert_eq!(extract_message_text(&json!("hello")), "hello");
    }

    #[test]
    fn test_extract_message_text_array() {
        let content = json!([
            {"type": "text", "text": "a"},
            {"type": "image_url"},
            {"type": "text", "text": "b"},
        ]);
        assert_eq!(extract_message_text(&content), "ab");
    }

    #[test]
    fn test_extract_message_text_null() {
        assert_eq!(extract_message_text(&Value::Null), "");
    }

    #[test]
    fn test_merge_overrides_object_field() {
        let mut payload = json!({"a": {"x": 1}, "b": 2});
        let overrides = json!({"a": {"y": 9}, "c": 3});
        merge_overrides_into_payload(&mut payload, &overrides);
        assert_eq!(payload["a"]["x"], 1);
        assert_eq!(payload["a"]["y"], 9);
        assert_eq!(payload["b"], 2);
        assert_eq!(payload["c"], 3);
    }

    #[test]
    fn test_build_usage_dict_derives_total() {
        let usage = build_usage_dict(10, 5, None);
        assert_eq!(usage["total_tokens"], 15);
    }

    #[test]
    fn glm_repair_reserves_small_output_budget_inside_context_window() {
        let max_output = LLM_REPAIR_MAX_OUTPUT_TOKENS;
        let context = GLM46V_CONTEXT_TOKENS;
        assert!(max_output < context);
    }

    #[test]
    fn glm_repair_rejects_text_larger_than_official_context_window() {
        let oversized = "上下文".repeat(130_000);
        let result =
            validate_glm46v_text_budget("system", &[json!({"type": "text", "text": oversized})]);
        assert!(result.is_err());
    }

    #[test]
    fn repair_images_require_vision_capable_model_args() {
        assert!(model_supports_repair_images(
            &json!({"supports_vision": true})
        ));
        assert!(!model_supports_repair_images(
            &json!({"supports_vision": false})
        ));
        assert!(!model_supports_repair_images(&json!({})));
    }

    #[tokio::test]
    async fn test_call_provider_classifies_connect_refused_as_retryable_transient() {
        // 端口 1 通常无服务；无 HTTP 响应的连接失败必须进入瞬时重试路径。
        let args = json!({
            "provider": "qwen",
            "model_id": "qwen-test",
            "api_key": "sk-test",
            "base_url": "http://127.0.0.1:1",
            "request_overrides": {},
            "display_label": "test",
        });
        let result = call_provider(&args, "sys", &[json!({"type":"text","text":"u"})]).await;
        assert!(result.is_err(), "本地端口 1 必然失败");
        let err = result.err().unwrap();
        let provider_err = err
            .downcast_ref::<crate::llm_client::ProviderError>()
            .expect("传输错误应分类为 ProviderError");
        assert!(provider_err.is_retryable());
    }
}
