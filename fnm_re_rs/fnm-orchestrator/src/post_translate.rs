//! ←→ Python `FNM_RE/app/mainline.py::run_post_translate_export_checks_for_doc`
//!
//! 翻译后导出检查 + 自修复循环。

use anyhow::Context;
use fnm_core::db::Repository;
use fnm_llm_repair::page_context::RepairImageRenderer;
use fnm_llm_repair::run::{run_llm_repair, RunLlmRepairParams};
use fnm_phase1::input::RawPage;
use serde_json::{json, Value};

use crate::load::load_phase6_structure;

struct NoopRenderer;
impl RepairImageRenderer for NoopRenderer {
    fn render_page_data_url(&self, _pdf_path: &str, _file_idx: i64) -> Option<String> {
        None
    }
}

fn translation_blockers(repo: &dyn Repository, doc_id: &str) -> Result<Vec<Value>, anyhow::Error> {
    let summary = crate::page_translate::build_retry_summary(repo, doc_id)?;
    if !summary
        .get("blocking_reason")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .is_empty()
    {
        let reason = summary["blocking_reason"].as_str().unwrap_or("");
        Ok(vec![json!({"reason": reason})])
    } else {
        Ok(vec![])
    }
}

fn tail_blocking_summary(
    translation_blockers: &[Value],
    export_blocking_reasons: &[String],
) -> Option<Value> {
    let mut combined: Vec<Value> = translation_blockers.to_vec();
    for reason in export_blocking_reasons {
        combined.push(json!({"reason": reason}));
    }
    if combined.is_empty() {
        None
    } else {
        Some(json!({"reasons": combined}))
    }
}

fn run_one_repair_round(
    repo: &dyn Repository,
    doc_id: &str,
    pages: &[RawPage],
    slug: &str,
    pdf_path: &str,
    auto_apply: bool,
    clear_overrides: bool,
    model_args_list: &[Value],
) -> (Vec<Value>, Option<Value>) {
    let mut model_attempts: Vec<Value> = Vec::new();
    let mut repair_result: Option<Value> = None;
    let renderer = NoopRenderer;

    for model_args in model_args_list {
        let provider = model_args
            .get("provider")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let model_id = model_args
            .get("model_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let api_key = model_args
            .get("api_key")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let label = model_args
            .get("display_label")
            .and_then(|v| v.as_str())
            .unwrap_or(model_id);

        if api_key.is_empty() {
            model_attempts.push(json!({
                "model_id": model_id,
                "model_label": label,
                "provider": provider,
                "result": "skipped_no_api_key",
            }));
            continue;
        }

        let mut params = RunLlmRepairParams::new(doc_id, repo, pages, pdf_path, &renderer);
        params.slug = slug;
        params.auto_apply = auto_apply;
        params.clear_materialized_overrides = clear_overrides;
        params.model_args = Some(model_args.clone());

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build();
        let runtime = match runtime {
            Ok(rt) => rt,
            Err(e) => {
                model_attempts.push(json!({
                    "model_id": model_id,
                    "model_label": label,
                    "provider": provider,
                    "result": "error",
                    "error": format!("tokio runtime: {}", e),
                }));
                continue;
            }
        };

        match runtime.block_on(run_llm_repair(params)) {
            Ok(report) => {
                let suggestion_count = report.suggestion_count as i64;
                let auto_applied = report.auto_applied_count as i64;
                model_attempts.push(json!({
                    "model_id": model_id,
                    "model_label": label,
                    "provider": provider,
                    "result": "used",
                    "suggestion_count": suggestion_count,
                    "auto_applied_count": auto_applied,
                }));
                repair_result = Some(
                    serde_json::to_value(&report)
                        .unwrap_or(json!({"error": "serialize report failed"})),
                );
                // Keep first working model; let the round-level logic handle retry
                break;
            }
            Err(e) => {
                model_attempts.push(json!({
                    "model_id": model_id,
                    "model_label": label,
                    "provider": provider,
                    "result": "error",
                    "error": format!("{}", e),
                }));
            }
        }
    }

    if repair_result.is_none() && !model_attempts.is_empty() {
        // Mark as no repair model succeeded
        if let Some(last) = model_attempts.last() {
            let _ = last; // already recorded
        }
    }

    (model_attempts, repair_result)
}

/// ←→ Python `run_post_translate_export_checks_for_doc()`
pub fn run_post_translate_export_checks(
    repo: &dyn Repository,
    doc_id: &str,
    slug: &str,
    pages: &[RawPage],
    pdf_path: &str,
    model_args_json: &str,
    max_repair_rounds: i64,
) -> Result<Value, anyhow::Error> {
    let max_rounds = std::cmp::max(0, max_repair_rounds);
    let model_args_list: Vec<Value> =
        serde_json::from_str(model_args_json).context("parse model_args_json")?;

    let trans_blockers = translation_blockers(repo, doc_id)?;

    let mut phase6 =
        load_phase6_structure(repo, doc_id, false).context("load phase6 structure")?;
    let (audit_report, _) = fnm_phase6::export_audit::audit_phase6_export(&phase6, slug, None);
    let mut can_ship = audit_report.can_ship;
    let mut blocking_reasons: Vec<String> =
        phase6.status.blocking_reasons.iter().cloned().collect();

    let mut repair_rounds: Vec<Value> = Vec::new();
    let mut attempted_rounds: i64 = 0;

    if !can_ship && max_rounds > 0 {
        for round_no in 1..=max_rounds {
            attempted_rounds = round_no;
            let clear_overrides = round_no == 1;

            let (model_attempts, repair_result) = run_one_repair_round(
                repo,
                doc_id,
                pages,
                slug,
                pdf_path,
                true,
                clear_overrides,
                &model_args_list,
            );

            let mut round_record = json!({
                "round": round_no,
                "model_attempts": model_attempts,
            });

            if let Some(ref rep) = repair_result {
                if let Some(sc) = rep.get("suggestion_count").and_then(|v| v.as_i64()) {
                    round_record["suggestion_count"] = json!(sc);
                }
                if let Some(aa) = rep.get("auto_applied_count").and_then(|v| v.as_i64()) {
                    round_record["auto_applied_count"] = json!(aa);
                }
            }

            // Reload phase6 after repair
            match load_phase6_structure(repo, doc_id, false) {
                Ok(new_phase6) => {
                    phase6 = new_phase6;
                    let (new_audit, _) =
                        fnm_phase6::export_audit::audit_phase6_export(&phase6, slug, None);
                    can_ship = new_audit.can_ship;
                    blocking_reasons =
                        phase6.status.blocking_reasons.iter().cloned().collect();
                }
                Err(e) => {
                    round_record["error"] = json!(format!("reload phase6: {}", e));
                }
            }

            round_record["post_round_can_ship"] = json!(can_ship);
            round_record["post_round_blocking_reasons"] = json!(blocking_reasons);
            repair_rounds.push(round_record);

            if can_ship {
                break;
            }
        }
    }

    let final_can_ship = can_ship && trans_blockers.is_empty();
    let final_blocking_reasons: Vec<String> = {
        let mut r: Vec<String> = blocking_reasons.clone();
        for b in &trans_blockers {
            if let Some(reason) = b.get("reason").and_then(|v| v.as_str()) {
                r.push(reason.to_string());
            }
        }
        r
    };

    let repair_payload = json!({
        "trigger": "after_translate",
        "max_repair_rounds": max_rounds,
        "attempted_rounds": attempted_rounds,
        "final_can_ship": final_can_ship,
        "final_blocking_reasons": final_blocking_reasons,
        "translation_blockers": trans_blockers,
        "repair_rounds": repair_rounds,
    });

    let blocking_summary = tail_blocking_summary(&trans_blockers, &blocking_reasons);

    Ok(json!({
        "ok": true,
        "export_ready_real": final_can_ship,
        "export_bundle_available": true,
        "export_has_blockers": blocking_summary.is_some(),
        "tail_blocking_summary": blocking_summary,
        "fnm_tail_state": "done",
        "structure_state": phase6.status.structure_state,
        "blocking_reasons": blocking_reasons,
        "translation_blockers": trans_blockers,
        "repair_rounds": repair_rounds,
        "post_translate_export_check": repair_payload,
    }))
}
