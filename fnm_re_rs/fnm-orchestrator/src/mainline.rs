//! DB-driven pipeline 入口（每个 phase 完成后持久化到 SQLite）。
//!
//! ←→ Python `FNM_RE/app/mainline.py::run_phase6_pipeline_for_doc()`
//!
//! 本模块和纯内存 [`crate::pipeline::run_pipeline`] 的区别：
//! - 每个 phase 完成后立即调 `repo.replace_fnm_phaseN_products()` 持久化
//! - 在 phase 3 后可选触发 LLM repair（基于 DB 中 phase3 产物 + 写 review_overrides）
//! - 失败时已持久化的前置 phase 数据保留，下次可从 start_phase 续跑

use crate::error::{OrchestratorError, Result};
use crate::pipeline;
use crate::types::{
    ModulePipelineSnapshot, PipelineConfig, SerPhase1, SerPhase2, SerPhase3, SerPhase4, SerPhase5,
    SerPhase6, StartPhase,
};

use fnm_core::db::{
    Phase1Products, Phase2Products, Phase3Products, Phase4Products, Phase5Products, Phase6Products,
    Repository,
};
use fnm_llm_repair::page_context::RepairImageRenderer;
use fnm_llm_repair::run::{run_llm_repair, LlmRepairReport, RunLlmRepairParams};
use fnm_phase1::input::{RawPage, TocItem};
use fnm_phase2::chapter_split::build_chapter_layers;

/// LLM repair 启用配置。
///
/// ←→ Python `run_llm_repair(doc_id, slug=..., auto_apply=True)` kwargs。
pub struct LlmRepairOptions<'a> {
    pub renderer: &'a dyn RepairImageRenderer,
    pub pdf_path: &'a str,
    pub auto_apply: bool,
    pub confidence_threshold: f64,
}

impl<'a> LlmRepairOptions<'a> {
    /// 默认值对齐 Python `run_llm_repair` kwargs。
    pub fn with_renderer(renderer: &'a dyn RepairImageRenderer, pdf_path: &'a str) -> Self {
        Self {
            renderer,
            pdf_path,
            auto_apply: true,
            confidence_threshold: 0.9,
        }
    }
}

/// DB-driven 入口：跑 phase1→6 并持久化到 SQLite。
///
/// ←→ Python `FNM_RE/app/mainline.py::run_phase6_pipeline_for_doc()`
///
/// 与纯内存 [`pipeline::run_pipeline`] 的关系：
/// 本函数内联了 phase 调用，每个 phase 完成后立即 persist；
/// caller 无需再单独持久化 snapshot。
pub fn run_pipeline_for_doc<R: Repository>(
    repo: &R,
    doc_id: &str,
    raw_pages: Vec<RawPage>,
    toc_items: Vec<TocItem>,
    config: PipelineConfig,
    llm_repair: Option<LlmRepairOptions<'_>>,
) -> Result<ModulePipelineSnapshot> {
    let pipeline_run_id = pipeline::generate_run_id(doc_id);

    let mut snapshot = ModulePipelineSnapshot {
        doc_id: doc_id.to_string(),
        slug: config.slug.clone(),
        pipeline_run_id: pipeline_run_id.clone(),
        ..Default::default()
    };

    // ── 0. 确保 documents 行存在（满足 fnm_* 表的外键）──
    repo.upsert_document(doc_id, &config.slug)
        .map_err(|e| OrchestratorError::Phase1(anyhow::anyhow!("upsert document: {}", e)))?;

    // ── Phase 1 ──
    let phase1 = pipeline::run_phase1(&raw_pages, &toc_items, &config)?;
    let phase1_products = Phase1Products {
        pages: phase1.structure.pages.clone(),
        chapters: phase1.structure.chapters.clone(),
        heading_candidates: phase1.structure.heading_candidates.clone(),
        section_heads: phase1.structure.section_heads.clone(),
    };
    repo.replace_fnm_phase1_products(doc_id, &phase1_products)
        .map_err(|e| OrchestratorError::Phase1(anyhow::anyhow!("persist phase1: {}", e)))?;
    snapshot.phase1 = Some(SerPhase1 {
        pages: phase1_products.pages,
        chapters: phase1_products.chapters,
        heading_candidates: phase1_products.heading_candidates,
        section_heads: phase1_products.section_heads,
    });

    // ── Phase 2 ──
    let phase2 = pipeline::run_phase2(&phase1, &raw_pages, &config)?;
    let phase2_products = Phase2Products {
        pages: phase1.structure.pages.clone(),
        chapters: phase1.structure.chapters.clone(),
        heading_candidates: phase1.structure.heading_candidates.clone(),
        section_heads: phase1.structure.section_heads.clone(),
        note_regions: phase2.note_regions.clone(),
        chapter_note_modes: phase2.chapter_note_modes.clone(),
        note_items: phase2.note_items.clone(),
    };
    repo.replace_fnm_phase2_products(doc_id, &phase2_products)
        .map_err(|e| OrchestratorError::Phase2(anyhow::anyhow!("persist phase2: {}", e)))?;
    snapshot.phase2 = Some(SerPhase2 {
        note_regions: phase2.note_regions.clone(),
        note_items: phase2.note_items.clone(),
        chapter_note_modes: phase2.chapter_note_modes.clone(),
    });

    // ── Phase 3 ──
    let phase3 = pipeline::run_phase3(&phase1, &phase2, &raw_pages, &config)?;
    let phase3_products = Phase3Products {
        body_anchors: phase3.body_anchors.clone(),
        note_links: phase3.note_links.clone(),
    };
    repo.replace_fnm_phase3_products(doc_id, &phase3_products)
        .map_err(|e| OrchestratorError::Phase3(anyhow::anyhow!("persist phase3: {}", e)))?;
    snapshot.phase3 = Some(SerPhase3 {
        body_anchors: phase3_products.body_anchors,
        note_links: phase3_products.note_links,
    });

    // ── Phase 3.5: LLM repair（可选）──
    // ←→ Python `pipeline.py:1598-1609`：phase3 持久化后调 run_llm_repair，
    //    auto_apply=True 时直接写 fnm_review_overrides，phase4 读 DB 时自然消费。
    let llm_repair_report = if let Some(opts) = llm_repair {
        let report = run_llm_repair_sync(repo, doc_id, &raw_pages, &config, &opts)?;
        Some(report)
    } else {
        None
    };

    // ── Phase 4 ──
    let chapter_layers = build_chapter_layers(
        &phase1.structure.chapters,
        &phase2.note_regions,
        &phase2.note_items,
        &phase1.structure.pages,
        &raw_pages,
    );
    let phase4 = pipeline::run_phase4(
        &phase1,
        &phase3,
        &chapter_layers,
        &raw_pages,
        &pipeline_run_id,
        &config,
    )?;
    let phase4_products = Phase4Products {
        translation_units: phase4.translation_units.clone(),
        structure_reviews: phase4.structure_reviews.clone(),
    };
    repo.replace_fnm_phase4_products(doc_id, &phase4_products)
        .map_err(|e| OrchestratorError::Phase4(anyhow::anyhow!("persist phase4: {}", e)))?;
    snapshot.phase4 = Some(SerPhase4 {
        translation_units: phase4_products.translation_units,
        structure_reviews: phase4_products.structure_reviews,
    });

    // ── Phase 5 ──
    let phase5 = pipeline::run_phase5(&phase4, &phase3, &chapter_layers, &phase1, &config)?;
    let phase5_products = Phase5Products {
        chapter_markdowns: phase5.chapter_markdowns.chapters.clone(),
        diagnostic_pages: Vec::new(),
        diagnostic_notes: Vec::new(),
    };
    repo.replace_fnm_phase5_products(doc_id, &phase5_products)
        .map_err(|e| OrchestratorError::Phase5(anyhow::anyhow!("persist phase5: {}", e)))?;
    snapshot.phase5 = Some(SerPhase5 {
        chapter_count: phase5.chapter_markdowns.chapters.len() as i64,
        merge_summary: phase5.chapter_markdowns.merge_summary.clone(),
    });

    // ── Phase 6 ──
    let phase6 = pipeline::run_phase6(&phase5, &phase1, &config)?;
    let phase6_products = Phase6Products {
        export_chapters: phase6.export_bundle.chapters.clone(),
        export_bundle: phase6.export_bundle.clone(),
        export_audit: phase6.export_audit.clone(),
    };
    repo.replace_fnm_phase6_products(doc_id, &phase6_products)
        .map_err(|e| OrchestratorError::Phase6(anyhow::anyhow!("persist phase6: {}", e)))?;
    snapshot.phase6 = Some(SerPhase6 {
        export_bundle: phase6_products.export_bundle,
        export_audit: phase6_products.export_audit,
    });

    let llm_repair_summary = llm_repair_report.as_ref().map(|r| {
        serde_json::json!({
            "cluster_count": r.cluster_count,
            "suggestion_count": r.suggestion_count,
            "auto_applied_count": r.auto_applied_count,
            "usage_summary": r.usage_summary.clone(),
        })
    });

    snapshot.run_meta = serde_json::json!({
        "pipeline_run_id": pipeline_run_id,
        "start_phase": format!("{:?}", config.start_phase),
        "phase_state": "done",
        "persisted": true,
        "llm_repair": llm_repair_summary,
    });

    Ok(snapshot)
}

/// 同步包装 async `run_llm_repair`。
///
/// 在 orchestrator 内部创建 tokio runtime 执行 async LLM 调用，
/// caller 不需要持有 runtime（对齐 Python `run_llm_repair` 同步语义）。
fn run_llm_repair_sync<R: Repository>(
    repo: &R,
    doc_id: &str,
    raw_pages: &[RawPage],
    config: &PipelineConfig,
    opts: &LlmRepairOptions<'_>,
) -> Result<LlmRepairReport> {
    let mut params = RunLlmRepairParams::new(doc_id, repo, raw_pages, opts.pdf_path, opts.renderer);
    params.slug = if config.slug.is_empty() {
        doc_id
    } else {
        &config.slug
    };
    params.auto_apply = opts.auto_apply;
    params.confidence_threshold = opts.confidence_threshold;

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| OrchestratorError::LlmRepair(anyhow::anyhow!("tokio runtime: {}", e)))?;

    runtime
        .block_on(run_llm_repair(params))
        .map_err(OrchestratorError::LlmRepair)
}

/// DB-driven 入口：加载数据 → 跑 pipeline → 写入 fnm_runs 记录。
///
/// 与 [`run_pipeline_for_doc`] 的区别：本函数自动从 DB 加载 pages + TOC items，
/// 并自动维护 fnm_runs 表的 create/update 生命周期。
/// **错误路径也会 finalize fnm_run**（状态设为 error + 记录错误消息），不会留下 `running` 悬挂。
///
/// ←→ Python `FNM_RE/__init__.py::run_doc_pipeline()`
pub fn run_pipeline_from_db<R: Repository>(
    repo: &R,
    doc_id: &str,
    config: PipelineConfig,
    llm_repair: Option<LlmRepairOptions<'_>>,
) -> Result<ModulePipelineSnapshot> {
    // start_phase != Toc 且未实现真实续跑 → 直接报错
    if config.start_phase != StartPhase::Toc {
        return Err(OrchestratorError::Phase1(anyhow::anyhow!(
            "start_phase={:?} 续跑未实现，仅支持 start_phase=Toc",
            config.start_phase
        )));
    }
    let pages = repo
        .load_raw_pages_for_doc(doc_id)
        .map_err(|e| OrchestratorError::Phase1(anyhow::anyhow!("load pages: {}", e)))?;
    let page_count = pages.len() as i64;
    if page_count == 0 {
        return Err(OrchestratorError::Phase1(anyhow::anyhow!(
            "no pages found for doc_id '{}'",
            doc_id
        )));
    }
    let toc_items = repo
        .load_toc_items_for_doc(doc_id)
        .map_err(|e| OrchestratorError::Phase1(anyhow::anyhow!("load toc: {}", e)))?;

    let run_id = repo
        .create_fnm_run(doc_id, page_count)
        .map_err(|e| OrchestratorError::Phase1(anyhow::anyhow!("create fnm_run: {}", e)))?;

    // 跑 pipeline，无论成功/失败都 finalize fnm_run
    let result = run_pipeline_for_doc(repo, doc_id, pages, toc_items, config, llm_repair);
    match result {
        Ok(snapshot) => {
            let section_count = snapshot
                .phase1
                .as_ref()
                .map(|p| p.chapters.len() as i64)
                .unwrap_or(0);
            let note_count = snapshot
                .phase2
                .as_ref()
                .map(|p| p.note_items.len() as i64)
                .unwrap_or(0);
            let unit_count = snapshot
                .phase4
                .as_ref()
                .map(|p| p.translation_units.len() as i64)
                .unwrap_or(0);
            let structure_state = snapshot
                .phase6
                .as_ref()
                .map(|p| p.export_audit.structure_state.clone())
                .unwrap_or_default();
            let blocking_reasons = snapshot
                .phase6
                .as_ref()
                .map(|p| p.export_audit.blocking_reasons.clone())
                .unwrap_or_default();
            let blocking_reasons_json =
                serde_json::to_string(&blocking_reasons).unwrap_or_default();

            repo.update_fnm_run(
                run_id,
                "done",
                section_count,
                note_count,
                unit_count,
                &structure_state,
                &blocking_reasons_json,
                "",
            )
            .map_err(|e| {
                OrchestratorError::Phase1(anyhow::anyhow!("finalize fnm_run done: {}", e))
            })?;

            Ok(snapshot)
        }
        Err(e) => {
            let err_msg = format!("{:#}", e);
            let _ = repo.update_fnm_run(run_id, "error", 0, 0, 0, "", "[]", &err_msg);
            Err(e)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::StartPhase;
    use fnm_core::db::schema;
    use r2d2::Pool;
    use r2d2_sqlite::SqliteConnectionManager;
    /// 创建内存 SQLite + `pages` 表 + TOC 列，返回 `pool`（conn 随 seed 回调使用后释放）。
    fn create_test_db() -> Pool<SqliteConnectionManager> {
        let manager = SqliteConnectionManager::memory();
        let pool = Pool::builder().build(manager).unwrap();
        let conn = pool.get().unwrap();
        conn.execute_batch("PRAGMA foreign_keys=ON;").unwrap();
        schema::run_migrations(&conn).unwrap();
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS pages (
                row_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id       TEXT NOT NULL,
                book_page    INTEGER NOT NULL,
                payload_json TEXT
            );",
        )
        .unwrap();
        for col in &["toc_user_json", "toc_auto_visual_json", "toc_auto_pdf_json"] {
            let sql = format!("ALTER TABLE documents ADD COLUMN {} TEXT DEFAULT '[]'", col);
            let _ = conn.execute_batch(&sql);
        }
        pool
    }

    fn seed_data<F>(pool: &Pool<SqliteConnectionManager>, f: F)
    where
        F: FnOnce(&rusqlite::Connection),
    {
        let conn = pool.get().unwrap();
        f(&conn);
    }

    fn default_config(doc_id: &str) -> PipelineConfig {
        PipelineConfig {
            doc_id: doc_id.to_string(),
            slug: doc_id.to_string(),
            pdf_path: String::new(),
            toc_offset: 0,
            max_body_chars: 6000,
            include_diagnostic_entries: false,
            manual_toc_ready: false,
            pipeline_state: "done".to_string(),
            start_phase: StartPhase::Toc,
            review_overrides: None,
            visual_toc_bundle: None,
        }
    }

    #[test]
    fn run_pipeline_from_db_errors_when_no_pages() {
        let pool = create_test_db();
        let repo = fnm_core::db::SqliteRepository::new(pool);
        let config = default_config("no-pages-doc");
        let result = run_pipeline_from_db(&repo, "no-pages-doc", config, None);
        assert!(result.is_err(), "expected error for empty pages");
        let err = result.unwrap_err().to_string();
        assert!(
            err.contains("no pages found"),
            "error should mention 'no pages': {}",
            err
        );
    }

    #[test]
    fn run_pipeline_from_db_succeeds_with_minimal_data() {
        let pool = create_test_db();
        let doc_id = "minimal-doc";

        seed_data(&pool, |conn| {
            conn.execute(
                "INSERT INTO documents (id, slug, toc_user_json) VALUES (?1, 'minimal',
                 '[{\"item_id\":\"ch-1\",\"title\":\"Chapter 1\",\"level\":1,\"depth\":0,\"role_hint\":\"chapter\"}]')",
                rusqlite::params![doc_id],
            ).unwrap();
            let p1 = serde_json::json!({"bookPage": 1, "markdown": "# Chapter 1\n\nThis is page one.\n\n[^1]: A footnote.\n\n## NOTES\n1. First note."});
            conn.execute(
                "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?1, 1, ?2)",
                rusqlite::params![doc_id, p1.to_string()],
            )
            .unwrap();
            let p2 = serde_json::json!({"bookPage": 2, "markdown": "Page two content."});
            conn.execute(
                "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?1, 2, ?2)",
                rusqlite::params![doc_id, p2.to_string()],
            )
            .unwrap();
        });

        let repo = fnm_core::db::SqliteRepository::new(pool);
        let config = default_config(doc_id);
        let result = run_pipeline_from_db(&repo, doc_id, config, None);
        assert!(
            result.is_ok(),
            "pipeline should succeed: {:?}",
            result.as_ref().err()
        );

        let snapshot = result.unwrap();
        assert_eq!(snapshot.doc_id, doc_id);
        assert!(snapshot.phase1.is_some(), "phase1 should be present");
        assert_eq!(snapshot.phase1.as_ref().unwrap().chapters.len(), 1);
    }

    #[test]
    fn run_pipeline_from_db_records_fnm_run() {
        let pool = create_test_db();
        let doc_id = "stats-doc";

        seed_data(&pool, |conn| {
            conn.execute(
                "INSERT INTO documents (id, slug, toc_user_json) VALUES (?1, 'stats',
                 '[{\"item_id\":\"ch-1\",\"title\":\"Chapter 1\",\"level\":1,\"depth\":0,\"role_hint\":\"chapter\"}]')",
                rusqlite::params![doc_id],
            ).unwrap();
            let p = serde_json::json!({"bookPage": 1, "markdown": "# Chapter 1\n\nText."});
            conn.execute(
                "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?1, 1, ?2)",
                rusqlite::params![doc_id, p.to_string()],
            )
            .unwrap();
        });

        let repo = fnm_core::db::SqliteRepository::new(pool);
        let config = default_config(doc_id);
        let result = run_pipeline_from_db(&repo, doc_id, config, None);
        assert!(
            result.is_ok(),
            "pipeline should succeed: {:?}",
            result.as_ref().err()
        );

        let run = repo
            .get_latest_fnm_run(doc_id)
            .unwrap()
            .expect("run should exist");
        assert_eq!(run.status, "done");
        assert_eq!(run.page_count, 1);
        assert!(run.updated_at > 0);
    }

    #[test]
    fn run_pipeline_from_db_errors_when_no_pages_does_not_create_run() {
        // 验证：页面加载错误发生在 create_fnm_run 之前，不会创建 fnm_run。
        let pool = create_test_db();
        let repo = fnm_core::db::SqliteRepository::new(pool);
        let config = default_config("ghost-doc");
        let result = run_pipeline_from_db(&repo, "ghost-doc", config, None);
        assert!(result.is_err(), "expected error for empty pages");

        let run = repo.get_latest_fnm_run("ghost-doc").unwrap();
        assert!(
            run.is_none(),
            "no fnm_run should exist when error is before create_fnm_run"
        );
    }
}
