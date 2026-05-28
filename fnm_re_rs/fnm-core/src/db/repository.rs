//! Repository trait + SQLite 实现。
//!
//! 封装所有 `fnm_*` 表的读写，后续 phase crate 通过此 trait 操作 DB。

use crate::records::*;
use crate::types::*;
use anyhow::{Context, Result};
use r2d2::Pool;
use r2d2_sqlite::SqliteConnectionManager;
use rusqlite::types::Type;
use serde::de::DeserializeOwned;
use serde_json::Value;
use std::io;
use std::str::FromStr;

fn invalid_db_value(column: usize, message: impl Into<String>) -> rusqlite::Error {
    rusqlite::Error::FromSqlConversionFailure(
        column,
        Type::Text,
        Box::new(io::Error::new(io::ErrorKind::InvalidData, message.into())),
    )
}

fn parse_required_json<T: DeserializeOwned>(
    raw: Option<String>,
    column: usize,
) -> rusqlite::Result<T> {
    let raw = raw.ok_or_else(|| invalid_db_value(column, "required JSON value is NULL"))?;
    serde_json::from_str(&raw).map_err(|e| invalid_db_value(column, e.to_string()))
}

// ── Phase products payload ───────────────────────────────────────

#[derive(Debug, Clone)]
pub struct Phase1Products {
    pub pages: Vec<PagePartitionRecord>,
    pub chapters: Vec<ChapterRecord>,
    pub heading_candidates: Vec<HeadingCandidate>,
    pub section_heads: Vec<SectionHeadRecord>,
}

#[derive(Debug, Clone)]
pub struct Phase2Products {
    pub pages: Vec<PagePartitionRecord>,
    pub chapters: Vec<ChapterRecord>,
    pub heading_candidates: Vec<HeadingCandidate>,
    pub section_heads: Vec<SectionHeadRecord>,
    pub note_regions: Vec<NoteRegionRecord>,
    pub chapter_note_modes: Vec<ChapterNoteModeRecord>,
    pub note_items: Vec<NoteItemRecord>,
}

#[derive(Debug, Clone)]
pub struct Phase3Products {
    pub body_anchors: Vec<BodyAnchorRecord>,
    pub note_links: Vec<NoteLinkRecord>,
}

#[derive(Debug, Clone)]
pub struct Phase4Products {
    pub translation_units: Vec<TranslationUnitRecord>,
    pub structure_reviews: Vec<StructureReviewRecord>,
}

#[derive(Debug, Clone)]
pub struct Phase5Products {
    pub chapter_markdowns: Vec<ChapterMarkdownEntry>,
    pub diagnostic_pages: Vec<DiagnosticPageRecord>,
    pub diagnostic_notes: Vec<DiagnosticNoteRecord>,
    pub merge_reviews: Vec<StructureReviewRecord>,
}

#[derive(Debug, Clone)]
pub struct Phase6Products {
    pub export_chapters: Vec<ExportChapterRecord>,
    pub export_bundle: ExportBundleRecord,
    pub export_audit: ExportAuditReportRecord,
}

// ── Repository trait ─────────────────────────────────────────────

pub trait Repository {
    // ── Phase 1 ──
    fn list_fnm_pages(&self, doc_id: &str) -> Result<Vec<PagePartitionRecord>>;
    fn list_fnm_chapters(&self, doc_id: &str) -> Result<Vec<ChapterRecord>>;
    fn list_fnm_heading_candidates(&self, doc_id: &str) -> Result<Vec<HeadingCandidate>>;
    fn list_fnm_section_heads(&self, doc_id: &str) -> Result<Vec<SectionHeadRecord>>;
    fn replace_fnm_phase1_products(&self, doc_id: &str, payload: &Phase1Products) -> Result<()>;

    // ── Phase 2 ──
    fn list_fnm_note_regions(&self, doc_id: &str) -> Result<Vec<NoteRegionRecord>>;
    fn list_fnm_note_items(&self, doc_id: &str) -> Result<Vec<NoteItemRecord>>;
    fn list_fnm_chapter_note_modes(&self, doc_id: &str) -> Result<Vec<ChapterNoteModeRecord>>;
    fn replace_fnm_phase2_products(&self, doc_id: &str, payload: &Phase2Products) -> Result<()>;

    // ── Phase 3 ──
    fn list_fnm_body_anchors(&self, doc_id: &str) -> Result<Vec<BodyAnchorRecord>>;
    fn list_fnm_note_links(&self, doc_id: &str) -> Result<Vec<NoteLinkRecord>>;
    fn list_fnm_chapter_anchor_alignments(
        &self,
        doc_id: &str,
    ) -> Result<Vec<ChapterAnchorAlignmentRecord>>;
    fn list_fnm_chapter_endnotes(&self, doc_id: &str) -> Result<Vec<ChapterEndnoteRecord>>;
    fn list_fnm_paragraph_footnotes(&self, doc_id: &str) -> Result<Vec<ParagraphFootnoteRecord>>;
    fn list_fnm_review_overrides_v2(&self, doc_id: &str) -> Result<Vec<Value>>;
    /// 清空指定 scope 的 LLM 修补 overrides（scope=None 时清空全部）。
    /// ←→ Python `SQLiteRepository.clear_fnm_review_overrides`
    fn clear_fnm_review_overrides_v2(&self, doc_id: &str, scope: Option<&str>) -> Result<()>;
    /// 批量写入 review overrides。rows: [(scope, target_id, payload), ...]
    /// ←→ Python `SQLiteRepository.batch_save_fnm_review_overrides`
    fn batch_save_fnm_review_overrides_v2(
        &self,
        doc_id: &str,
        rows: &[(String, String, Value)],
    ) -> Result<()>;
    fn replace_fnm_phase3_products(&self, doc_id: &str, payload: &Phase3Products) -> Result<()>;

    // ── Phase 3 按章 scope 写入──
    fn upsert_fnm_chapter_anchor_alignment(
        &self,
        doc_id: &str,
        chapter_id: &str,
        alignment_status: &str,
        body_anchor_count: i64,
        endnote_count: i64,
        mismatch: Option<Value>,
    ) -> Result<()>;
    fn replace_fnm_paragraph_footnotes(
        &self,
        doc_id: &str,
        chapter_id: &str,
        footnotes: &[ParagraphFootnoteRecord],
    ) -> Result<()>;
    fn replace_fnm_chapter_endnotes(
        &self,
        doc_id: &str,
        chapter_id: &str,
        endnotes: &[ChapterEndnoteRecord],
    ) -> Result<()>;

    // ── Translation units ──
    fn list_fnm_translation_units(&self, doc_id: &str) -> Result<Vec<TranslationUnitRecord>>;
    fn replace_fnm_translation_units(
        &self,
        doc_id: &str,
        units: &[TranslationUnitRecord],
    ) -> Result<()>;

    // ── Structure reviews ──
    fn list_fnm_structure_reviews(&self, doc_id: &str) -> Result<Vec<StructureReviewRecord>>;
    fn replace_fnm_structure_reviews(
        &self,
        doc_id: &str,
        reviews: &[StructureReviewRecord],
    ) -> Result<()>;

    // ── Phase 4 ──
    fn replace_fnm_phase4_products(&self, doc_id: &str, payload: &Phase4Products) -> Result<()>;

    // ── Phase 5 ──
    fn list_fnm_chapter_markdowns(&self, doc_id: &str) -> Result<Vec<ChapterMarkdownEntry>>;
    fn list_fnm_diagnostic_pages(&self, doc_id: &str) -> Result<Vec<DiagnosticPageRecord>>;
    fn list_fnm_diagnostic_notes(&self, doc_id: &str) -> Result<Vec<DiagnosticNoteRecord>>;
    fn replace_fnm_phase5_products(&self, doc_id: &str, payload: &Phase5Products) -> Result<()>;

    // ── Phase 6 ──
    fn list_fnm_export_chapters(&self, doc_id: &str) -> Result<Vec<ExportChapterRecord>>;
    fn list_fnm_export_audit(&self, doc_id: &str) -> Result<Option<ExportAuditReportRecord>>;
    fn list_fnm_export_bundle(&self, doc_id: &str) -> Result<Option<ExportBundleRecord>>;
    fn replace_fnm_phase6_products(&self, doc_id: &str, payload: &Phase6Products) -> Result<()>;

    // ── documents 元数据 ──
    /// upsert documents 表（满足 fnm_* 表的外键约束）。
    /// ←→ Python `SQLiteRepository.upsert_document(doc_id, slug)`
    fn upsert_document(&self, doc_id: &str, slug: &str) -> Result<()>;

    // ── fnm_runs ──
    /// 获取最新一条 fnm_run 记录。
    /// ←→ Python `SQLiteRepository.get_latest_fnm_run(doc_id)`
    fn get_latest_fnm_run(&self, doc_id: &str) -> Result<Option<FnmRunRecord>>;

    // ── Input bridge (M3) ──
    /// 从 `pages` 表加载原始 OCR 页面。
    ///
    /// ←→ Python `SQLiteRepository.load_raw_pages(doc_id)` / `fnm-py/src/lib.rs:465`
    fn load_raw_pages_for_doc(&self, doc_id: &str) -> Result<Vec<RawPage>>;

    /// 从 `documents` 表加载 TOC 条目，按优先级选择数据源。
    /// 优先级：toc_user_json（最高）> toc_auto_visual_json > toc_auto_pdf_json（最低）。
    ///
    /// ←→ Python `fnm-py/src/lib.rs:491`
    fn load_toc_items_for_doc(&self, doc_id: &str) -> Result<Vec<TocItem>>;

    /// 创建一条 fnm_runs 记录，状态为 'running'，返回 run_id。
    ///
    /// ←→ Python `INSERT INTO fnm_runs` in `fnm-py/src/lib.rs:566`
    fn create_fnm_run(&self, doc_id: &str, page_count: i64) -> Result<i64>;

    /// 更新 fnm_runs 记录的状态和统计字段。
    ///
    /// ←→ Python `UPDATE fnm_runs` in `fnm-py/src/lib.rs:611`
    fn update_fnm_run(&self, params: UpdateFnmRunParams<'_>) -> Result<()>;
}

/// `update_fnm_run` 的参数集合。
pub struct UpdateFnmRunParams<'a> {
    pub run_id: i64,
    pub status: &'a str,
    pub section_count: i64,
    pub note_count: i64,
    pub unit_count: i64,
    pub structure_state: &'a str,
    pub blocking_reasons_json: &'a str,
    pub error_msg: &'a str,
}

/// 把 Rust 端 heading_family_guess 映射到 schema CHECK 允许的 6 个值之一。
///
/// ←→ Python `FNM_RE/app/persist_helpers.py::serialize_heading_candidates_for_repo`
/// 中的 family_alias 表 + 白名单兜底为 'unknown'。
fn normalize_heading_family_guess(raw: &str) -> &'static str {
    match raw.trim().to_ascii_lowercase().as_str() {
        "book" => "book",
        "chapter" => "chapter",
        "section" => "section",
        "note" => "note",
        "other" => "other",
        "unknown" => "unknown",
        "front_matter" => "book",
        "back_matter" => "other",
        _ => "unknown",
    }
}

// ── SqliteRepository ─────────────────────────────────────────────

pub struct SqliteRepository {
    pool: Pool<SqliteConnectionManager>,
}

impl SqliteRepository {
    pub fn new(pool: Pool<SqliteConnectionManager>) -> Self {
        Self { pool }
    }

    fn get_conn(&self) -> Result<r2d2::PooledConnection<SqliteConnectionManager>> {
        self.pool.get().context("failed to get DB connection")
    }

    fn now_ts() -> i64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs() as i64
    }

    /// 写 fnm_pages + fnm_chapters + fnm_section_heads + fnm_heading_candidates。
    /// 接受切片，避免 Phase2/3 的 `replace_*` 调用方 clone Vec。
    fn write_phase1_tables(
        &self,
        doc_id: &str,
        pages: &[PagePartitionRecord],
        chapters: &[ChapterRecord],
        heading_candidates: &[HeadingCandidate],
        section_heads: &[SectionHeadRecord],
    ) -> Result<()> {
        let conn = self.get_conn()?;
        let ts = Self::now_ts();

        conn.execute("DELETE FROM fnm_pages WHERE doc_id = ?1", [doc_id])?;
        conn.execute("DELETE FROM fnm_chapters WHERE doc_id = ?1", [doc_id])?;
        conn.execute("DELETE FROM fnm_section_heads WHERE doc_id = ?1", [doc_id])?;
        conn.execute(
            "DELETE FROM fnm_heading_candidates WHERE doc_id = ?1",
            [doc_id],
        )?;

        // 插入 pages
        let mut stmt = conn.prepare(
            "INSERT INTO fnm_pages (doc_id, page_no, target_pdf_page, page_role, role_confidence,
             role_reason, section_hint, has_note_heading, note_scan_summary_json,
             created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
        )?;
        for p in pages {
            stmt.execute(rusqlite::params![
                doc_id,
                p.page_no,
                p.target_pdf_page,
                p.page_role.as_str(),
                p.confidence,
                p.reason,
                p.section_hint,
                p.has_note_heading as i64,
                serde_json::to_string(&p.note_scan_summary).ok(),
                ts,
                ts,
            ])?;
        }

        // 插入 chapters
        let mut stmt = conn.prepare(
            "INSERT INTO fnm_chapters (doc_id, chapter_id, title, start_page, end_page,
             pages_json, source, boundary_state, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
        )?;
        for ch in chapters {
            stmt.execute(rusqlite::params![
                doc_id,
                ch.chapter_id,
                ch.title,
                ch.start_page,
                ch.end_page,
                serde_json::to_string(&ch.pages).ok(),
                ch.source.as_str(),
                ch.boundary_state.as_str(),
                ts,
                ts,
            ])?;
        }

        // 插入 heading_candidates
        let mut stmt = conn.prepare(
            "INSERT INTO fnm_heading_candidates (doc_id, heading_id, page_no, text,
             normalized_text, source, block_label, top_band, font_height, x, y, width_estimate, confidence,
             heading_family_guess, suppressed_as_chapter, reject_reason,
             font_name, font_weight_hint, align_hint, width_ratio, heading_level_hint,
             created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23)",
        )?;
        for hc in heading_candidates {
            stmt.execute(rusqlite::params![
                doc_id,
                hc.heading_id,
                hc.page_no,
                hc.text,
                hc.normalized_text,
                hc.source,
                hc.block_label,
                hc.top_band as i64,
                hc.font_height,
                hc.x,
                hc.y,
                hc.width_estimate,
                hc.confidence,
                normalize_heading_family_guess(&hc.heading_family_guess),
                hc.suppressed_as_chapter as i64,
                hc.reject_reason,
                hc.font_name,
                hc.font_weight_hint,
                hc.align_hint,
                hc.width_ratio,
                hc.heading_level_hint,
                ts,
                ts,
            ])?;
        }

        // 插入 section_heads
        let mut stmt = conn.prepare(
            "INSERT INTO fnm_section_heads (doc_id, section_head_id, chapter_id, page_no,
             text, normalized_text, level, source, confidence, heading_family_guess,
             rejected_chapter_candidate, reject_reason, derived_from_heading_id,
             created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
        )?;
        for sh in section_heads {
            stmt.execute(rusqlite::params![
                doc_id,
                sh.section_head_id,
                sh.chapter_id,
                sh.page_no,
                sh.title,
                sh.title,
                sh.level,
                sh.source,
                1.0_f64,
                "section",
                0_i64,
                "",
                "",
                ts,
                ts,
            ])?;
        }

        Ok(())
    }
}

impl Repository for SqliteRepository {
    // ── Phase 1 ──────────────────────────────────────────────────

    fn list_fnm_pages(&self, doc_id: &str) -> Result<Vec<PagePartitionRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT page_no, target_pdf_page, page_role, role_confidence, role_reason,
                    section_hint, has_note_heading, note_scan_summary_json
             FROM fnm_pages WHERE doc_id = ?1 ORDER BY page_no",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(PagePartitionRecord {
                page_no: row.get(0)?,
                target_pdf_page: row.get::<_, Option<i64>>(1)?.unwrap_or(0),
                page_role: PageRole::from_str(&row.get::<_, String>(2)?).unwrap_or(PageRole::Other),
                confidence: row.get(3)?,
                reason: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                section_hint: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
                has_note_heading: row.get::<_, i64>(6)? != 0,
                note_scan_summary: row
                    .get::<_, Option<String>>(7)?
                    .and_then(|s| serde_json::from_str(&s).ok())
                    .unwrap_or_default(),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_chapters(&self, doc_id: &str) -> Result<Vec<ChapterRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT chapter_id, title, start_page, end_page, pages_json, source, boundary_state
             FROM fnm_chapters WHERE doc_id = ?1 ORDER BY start_page",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(ChapterRecord {
                chapter_id: row.get(0)?,
                title: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                start_page: row.get(2)?,
                end_page: row.get(3)?,
                pages: parse_required_json(row.get(4)?, 4)?,
                source: ChapterSource::from_str(
                    &row.get::<_, Option<String>>(5)?.unwrap_or_default(),
                )
                .unwrap_or(ChapterSource::Fallback),
                boundary_state: BoundaryState::from_str(
                    &row.get::<_, Option<String>>(6)?.unwrap_or_default(),
                )
                .unwrap_or(BoundaryState::Ready),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_section_heads(&self, doc_id: &str) -> Result<Vec<SectionHeadRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT section_head_id, chapter_id, text, page_no, level, source
             FROM fnm_section_heads WHERE doc_id = ?1 ORDER BY page_no",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(SectionHeadRecord {
                section_head_id: row.get(0)?,
                chapter_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                title: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                page_no: row.get(3)?,
                level: row.get(4)?,
                source: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_heading_candidates(&self, doc_id: &str) -> Result<Vec<HeadingCandidate>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT heading_id, page_no, text, normalized_text, source, block_label,
                    top_band, confidence, heading_family_guess, suppressed_as_chapter,
                    reject_reason, font_height, x, y, width_estimate, font_name,
                    font_weight_hint, align_hint, width_ratio, heading_level_hint
             FROM fnm_heading_candidates WHERE doc_id = ?1 ORDER BY page_no",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(HeadingCandidate {
                heading_id: row.get(0)?,
                page_no: row.get(1)?,
                text: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                normalized_text: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                source: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                block_label: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
                top_band: row.get::<_, i64>(6)? != 0,
                confidence: row.get(7)?,
                heading_family_guess: row.get::<_, Option<String>>(8)?.unwrap_or_default(),
                suppressed_as_chapter: row.get::<_, i64>(9)? != 0,
                reject_reason: row.get::<_, Option<String>>(10)?.unwrap_or_default(),
                font_height: row.get(11)?,
                x: row.get(12)?,
                y: row.get(13)?,
                width_estimate: row.get(14)?,
                font_name: row.get(15)?,
                font_weight_hint: row.get(16)?,
                align_hint: row.get(17)?,
                width_ratio: row.get(18)?,
                heading_level_hint: row.get(19)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn replace_fnm_phase1_products(&self, doc_id: &str, payload: &Phase1Products) -> Result<()> {
        self.write_phase1_tables(
            doc_id,
            &payload.pages,
            &payload.chapters,
            &payload.heading_candidates,
            &payload.section_heads,
        )
    }

    // ── Phase 2 ──────────────────────────────────────────────────

    fn list_fnm_note_regions(&self, doc_id: &str) -> Result<Vec<NoteRegionRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT region_id, bound_chapter_id, start_page, end_page, pages_json,
                    region_kind, region_scope, region_source, title_hint, start_reason, end_reason,
                    region_marker_alignment_ok, region_start_first_source_marker,
                    region_first_note_item_marker, review_required
             FROM fnm_note_regions WHERE doc_id = ?1 ORDER BY start_page",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            let scope = RegionScope::from_str(&row.get::<_, String>(6)?)
                .map_err(|e| invalid_db_value(6, e))?;
            let source = RegionSource::from_str(&row.get::<_, String>(7)?)
                .map_err(|e| invalid_db_value(7, e))?;
            Ok(NoteRegionRecord {
                region_id: row.get(0)?,
                chapter_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                page_start: row.get(2)?,
                page_end: row.get(3)?,
                pages: parse_required_json(row.get(4)?, 4)?,
                note_kind: NoteKind::from_str(&row.get::<_, String>(5)?)
                    .unwrap_or(NoteKind::Unknown),
                scope,
                source,
                heading_text: row.get::<_, Option<String>>(8)?.unwrap_or_default(),
                start_reason: row.get(9)?,
                end_reason: row.get(10)?,
                region_marker_alignment_ok: row.get::<_, i64>(11)? != 0,
                region_start_first_source_marker: row
                    .get::<_, Option<String>>(12)?
                    .unwrap_or_default(),
                region_first_note_item_marker: row
                    .get::<_, Option<String>>(13)?
                    .unwrap_or_default(),
                review_required: row.get::<_, i64>(14)? != 0,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_note_items(&self, doc_id: &str) -> Result<Vec<NoteItemRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT note_item_id, region_id, chapter_id, page_no, marker,
                    marker_type, note_kind, source_text, item_source, source_page_label,
                    is_reconstructed, review_required, projection_mode, owner_chapter_id,
                    source_marker, normalized_marker
             FROM fnm_note_items WHERE doc_id = ?1 ORDER BY page_no, marker",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(NoteItemRecord {
                note_item_id: row.get(0)?,
                region_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                chapter_id: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                page_no: row.get(3)?,
                marker: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                marker_type: row.get(5)?,
                text: row.get::<_, Option<String>>(7)?.unwrap_or_default(),
                source: row.get(8)?,
                source_page_label: row.get(9)?,
                is_reconstructed: row.get::<_, i64>(10)? != 0,
                review_required: row.get::<_, i64>(11)? != 0,
                note_kind: NoteKind::from_str(&row.get::<_, String>(6)?)
                    .unwrap_or(NoteKind::Unknown),
                projection_mode: row.get(12)?,
                owner_chapter_id: row.get(13)?,
                source_marker: row.get(14)?,
                normalized_marker: row.get(15)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_chapter_note_modes(&self, doc_id: &str) -> Result<Vec<ChapterNoteModeRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT chapter_id, note_mode, region_ids_json, primary_region_scope,
                    has_footnote_band, has_endnote_region
             FROM fnm_chapter_note_modes WHERE doc_id = ?1 ORDER BY chapter_id",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(ChapterNoteModeRecord {
                chapter_id: row.get(0)?,
                note_mode: NoteMode::from_str(&row.get::<_, String>(1)?)
                    .unwrap_or(NoteMode::ReviewRequired),
                region_ids: parse_required_json(row.get(2)?, 2)?,
                primary_region_scope: row.get(3)?,
                has_footnote_band: row.get::<_, i64>(4)? != 0,
                has_endnote_region: row.get::<_, i64>(5)? != 0,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn replace_fnm_phase2_products(&self, doc_id: &str, payload: &Phase2Products) -> Result<()> {
        // Phase 2 只写 Phase 2 表，不触碰 Phase 1 表（Phase 1 已持久化）。
        let conn = self.get_conn()?;
        let ts = Self::now_ts();

        conn.execute("DELETE FROM fnm_note_regions WHERE doc_id = ?1", [doc_id])?;
        conn.execute(
            "DELETE FROM fnm_chapter_note_modes WHERE doc_id = ?1",
            [doc_id],
        )?;
        conn.execute("DELETE FROM fnm_note_items WHERE doc_id = ?1", [doc_id])?;

        let mut stmt_region = conn.prepare(
            "INSERT INTO fnm_note_regions (doc_id, region_id, region_kind,
             start_page, end_page, pages_json, title_hint, bound_chapter_id,
             region_scope, region_source, start_reason, end_reason, review_required,
             region_start_first_source_marker, region_first_note_item_marker,
             region_marker_alignment_ok, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18)",
        )?;
        for r in &payload.note_regions {
            let pages_json = serde_json::to_string(&r.pages)?;
            stmt_region.execute(rusqlite::params![
                doc_id,
                r.region_id,
                r.note_kind.as_str(),
                r.page_start,
                r.page_end,
                pages_json,
                r.heading_text,
                r.chapter_id,
                r.scope.as_str(),
                r.source.as_str(),
                r.start_reason,
                r.end_reason,
                r.review_required as i64,
                r.region_start_first_source_marker,
                r.region_first_note_item_marker,
                r.region_marker_alignment_ok as i64,
                ts,
                ts,
            ])?;
        }

        let mut stmt_mode = conn.prepare(
            "INSERT INTO fnm_chapter_note_modes (doc_id, chapter_id, chapter_title,
             note_mode, region_ids_json, primary_region_scope, has_footnote_band,
             has_endnote_region, sampled_pages_json, detection_confidence, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
        )?;
        for cm in &payload.chapter_note_modes {
            let region_ids_json = serde_json::to_string(&cm.region_ids)?;
            stmt_mode.execute(rusqlite::params![
                doc_id,
                cm.chapter_id,
                "",
                cm.note_mode.as_str(),
                region_ids_json,
                cm.primary_region_scope,
                cm.has_footnote_band as i64,
                cm.has_endnote_region as i64,
                "[]",
                1.0_f64,
                ts,
                ts,
            ])?;
        }

        let mut stmt_item = conn.prepare(
            "INSERT INTO fnm_note_items (doc_id, note_item_id, note_kind,
             chapter_id, region_id, marker, marker_type, normalized_marker, occurrence,
             source_text, item_source, source_page_label, is_reconstructed, review_required,
             projection_mode, owner_chapter_id, page_no, display_marker, source_marker, title_hint,
             created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22)",
        )?;
        for item in &payload.note_items {
            stmt_item.execute(rusqlite::params![
                doc_id,
                item.note_item_id,
                item.note_kind.as_str(),
                item.chapter_id,
                item.region_id,
                item.marker,
                item.marker_type,
                item.normalized_marker,
                1_i64,
                item.text,
                item.source,
                item.source_page_label,
                item.is_reconstructed as i64,
                item.review_required as i64,
                item.projection_mode,
                item.owner_chapter_id,
                item.page_no,
                item.marker,
                item.source_marker,
                "",
                ts,
                ts,
            ])?;
        }

        Ok(())
    }

    // ── Phase 3 ──────────────────────────────────────────────────

    fn list_fnm_body_anchors(&self, doc_id: &str) -> Result<Vec<BodyAnchorRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT anchor_id, chapter_id, page_no, paragraph_index, char_start,
                    char_end, source_marker, normalized_marker, anchor_kind, certainty,
                    source_text, anchor_source, synthetic, ocr_repaired_from_marker,
                    coordinate_unit
             FROM fnm_body_anchors WHERE doc_id = ?1 ORDER BY page_no, paragraph_index",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            let coordinate_unit: String = row.get(14)?;
            if coordinate_unit != "char" {
                return Err(invalid_db_value(
                    14,
                    format!("unsupported body anchor coordinate_unit: {coordinate_unit}"),
                ));
            }
            Ok(BodyAnchorRecord {
                anchor_id: row.get(0)?,
                chapter_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                page_no: row.get(2)?,
                paragraph_index: row.get(3)?,
                char_start: row.get(4)?,
                char_end: row.get(5)?,
                source_marker: row.get::<_, Option<String>>(6)?.unwrap_or_default(),
                normalized_marker: row.get::<_, Option<String>>(7)?.unwrap_or_default(),
                anchor_kind: AnchorKind::from_str(&row.get::<_, String>(8)?)
                    .unwrap_or(AnchorKind::Unknown),
                certainty: row.get(9)?,
                source_text: row.get::<_, Option<String>>(10)?.unwrap_or_default(),
                source: row.get(11)?,
                synthetic: row.get::<_, i64>(12)? != 0,
                ocr_repaired_from_marker: row.get(13)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_note_links(&self, doc_id: &str) -> Result<Vec<NoteLinkRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT link_id, chapter_id, region_id, note_item_id, anchor_id,
                    status, resolver, confidence, note_kind, marker,
                    page_no_start, page_no_end
             FROM fnm_note_links WHERE doc_id = ?1 ORDER BY page_no_start",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(NoteLinkRecord {
                link_id: row.get(0)?,
                chapter_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                region_id: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                note_item_id: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                anchor_id: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                status: LinkStatus::from_str(&row.get::<_, String>(5)?)
                    .unwrap_or(LinkStatus::OrphanNote),
                resolver: LinkResolver::from_str(
                    &row.get::<_, Option<String>>(6)?.unwrap_or_default(),
                )
                .unwrap_or(LinkResolver::Fallback),
                confidence: row.get(7)?,
                note_kind: NoteKind::from_str(
                    &row.get::<_, Option<String>>(8)?.unwrap_or_default(),
                )
                .unwrap_or(NoteKind::Unknown),
                marker: row.get::<_, Option<String>>(9)?.unwrap_or_default(),
                page_no_start: row.get::<_, Option<i64>>(10)?.unwrap_or(0),
                page_no_end: row.get::<_, Option<i64>>(11)?.unwrap_or(0),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn replace_fnm_phase3_products(&self, doc_id: &str, payload: &Phase3Products) -> Result<()> {
        let conn = self.get_conn()?;
        let ts = Self::now_ts();

        conn.execute("DELETE FROM fnm_body_anchors WHERE doc_id = ?1", [doc_id])?;
        conn.execute("DELETE FROM fnm_note_links WHERE doc_id = ?1", [doc_id])?;

        let mut stmt_anchor = conn.prepare(
            "INSERT INTO fnm_body_anchors (doc_id, anchor_id, chapter_id, page_no,
             paragraph_index, char_start, char_end, source_marker, normalized_marker,
             anchor_kind, certainty, source_text, anchor_source, synthetic,
             ocr_repaired_from_marker, coordinate_unit, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18)",
        )?;
        for ba in &payload.body_anchors {
            stmt_anchor.execute(rusqlite::params![
                doc_id,
                ba.anchor_id,
                ba.chapter_id,
                ba.page_no,
                ba.paragraph_index,
                ba.char_start,
                ba.char_end,
                ba.source_marker,
                ba.normalized_marker,
                ba.anchor_kind.as_str(),
                ba.certainty,
                ba.source_text,
                ba.source,
                ba.synthetic as i64,
                ba.ocr_repaired_from_marker,
                "char",
                ts,
                ts,
            ])?;
        }

        let mut stmt_link = conn.prepare(
            "INSERT INTO fnm_note_links (doc_id, link_id, chapter_id, region_id,
             note_item_id, anchor_id, status, resolver, confidence, note_kind, marker,
             page_no_start, page_no_end, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
        )?;
        for link in &payload.note_links {
            stmt_link.execute(rusqlite::params![
                doc_id,
                link.link_id,
                link.chapter_id,
                link.region_id,
                link.note_item_id,
                link.anchor_id,
                link.status.as_str(),
                link.resolver.as_str(),
                link.confidence,
                link.note_kind.as_str(),
                link.marker,
                link.page_no_start,
                link.page_no_end,
                ts,
                ts,
            ])?;
        }

        Ok(())
    }

    // ── Phase 3 Reads ──────────────────────────────────────────────

    fn list_fnm_chapter_anchor_alignments(
        &self,
        doc_id: &str,
    ) -> Result<Vec<ChapterAnchorAlignmentRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT chapter_id, alignment_status, body_anchor_count, endnote_count, mismatch_json
             FROM fnm_chapter_anchor_alignment WHERE doc_id = ?1 ORDER BY chapter_id",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(ChapterAnchorAlignmentRecord {
                doc_id: doc_id.to_string(),
                chapter_id: row.get(0)?,
                alignment_status: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                body_anchor_count: row.get::<_, Option<i64>>(2)?.unwrap_or(0),
                endnote_count: row.get::<_, Option<i64>>(3)?.unwrap_or(0),
                mismatch: row
                    .get::<_, Option<String>>(4)?
                    .and_then(|s| serde_json::from_str::<Value>(&s).ok()),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_chapter_endnotes(&self, doc_id: &str) -> Result<Vec<ChapterEndnoteRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT chapter_id, ordinal, marker, numbering_scheme, text,
                    source_page_no, is_reconstructed, review_required
             FROM fnm_chapter_endnotes WHERE doc_id = ?1 ORDER BY chapter_id, ordinal",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(ChapterEndnoteRecord {
                doc_id: doc_id.to_string(),
                chapter_id: row.get(0)?,
                ordinal: row.get(1)?,
                marker: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                numbering_scheme: row
                    .get::<_, Option<String>>(3)?
                    .unwrap_or_else(|| "per_chapter".to_string()),
                text: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                source_page_no: row.get::<_, Option<i64>>(5)?.unwrap_or(0),
                is_reconstructed: row.get::<_, Option<i64>>(6)?.unwrap_or(0) != 0,
                review_required: row.get::<_, Option<i64>>(7)?.unwrap_or(1) != 0,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_paragraph_footnotes(&self, doc_id: &str) -> Result<Vec<ParagraphFootnoteRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT chapter_id, page_no, paragraph_index, attachment_kind,
                    source_marker, text
             FROM fnm_paragraph_footnotes WHERE doc_id = ?1 ORDER BY chapter_id, page_no",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(ParagraphFootnoteRecord {
                doc_id: doc_id.to_string(),
                chapter_id: row.get(0)?,
                page_no: row.get(1)?,
                paragraph_index: row.get::<_, Option<i64>>(2)?.unwrap_or(0),
                attachment_kind: row
                    .get::<_, Option<String>>(3)?
                    .unwrap_or_else(|| "page_tail".to_string()),
                source_marker: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                text: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_review_overrides_v2(&self, doc_id: &str) -> Result<Vec<Value>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT scope, target_id, payload_json
             FROM fnm_review_overrides_v2 WHERE doc_id = ?1 ORDER BY scope, target_id",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            let scope: String = row.get(0)?;
            let target_id: String = row.get(1)?;
            let payload_json: String = row.get(2)?;
            Ok(serde_json::json!({
                "scope": scope,
                "target_id": target_id,
                "payload": serde_json::from_str::<Value>(&payload_json).unwrap_or(Value::Null),
            }))
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn clear_fnm_review_overrides_v2(&self, doc_id: &str, scope: Option<&str>) -> Result<()> {
        let conn = self.get_conn()?;
        if let Some(scope_value) = scope {
            conn.execute(
                "DELETE FROM fnm_review_overrides_v2 WHERE doc_id = ?1 AND scope = ?2",
                rusqlite::params![doc_id, scope_value],
            )?;
        } else {
            conn.execute(
                "DELETE FROM fnm_review_overrides_v2 WHERE doc_id = ?1",
                rusqlite::params![doc_id],
            )?;
        }
        Ok(())
    }

    fn batch_save_fnm_review_overrides_v2(
        &self,
        doc_id: &str,
        rows: &[(String, String, Value)],
    ) -> Result<()> {
        if rows.is_empty() {
            return Ok(());
        }
        let mut conn = self.get_conn()?;
        let tx = conn.transaction()?;
        let now = Self::now_ts();
        for (scope, target_id, payload) in rows {
            let payload_json = serde_json::to_string(payload)?;
            tx.execute(
                "INSERT INTO fnm_review_overrides_v2(
                    doc_id, scope, target_id, payload_json, created_at, updated_at
                ) VALUES (?1, ?2, ?3, ?4, ?5, ?5)
                ON CONFLICT(doc_id, scope, target_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at",
                rusqlite::params![doc_id, scope, target_id, payload_json, now],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    // ── Phase 3 按章 scope 写入 ────────────────────────────────────

    fn upsert_fnm_chapter_anchor_alignment(
        &self,
        doc_id: &str,
        chapter_id: &str,
        alignment_status: &str,
        body_anchor_count: i64,
        endnote_count: i64,
        mismatch: Option<Value>,
    ) -> Result<()> {
        let conn = self.get_conn()?;
        let ts = Self::now_ts();
        let mismatch_json = mismatch
            .as_ref()
            .map(|v| serde_json::to_string(v).unwrap_or_default());
        conn.execute(
            "INSERT INTO fnm_chapter_anchor_alignment
             (doc_id, chapter_id, alignment_status, body_anchor_count, endnote_count,
              mismatch_json, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
             ON CONFLICT(doc_id, chapter_id) DO UPDATE SET
                alignment_status = excluded.alignment_status,
                body_anchor_count = excluded.body_anchor_count,
                endnote_count = excluded.endnote_count,
                mismatch_json = excluded.mismatch_json,
                updated_at = excluded.updated_at",
            rusqlite::params![
                doc_id,
                chapter_id,
                alignment_status,
                body_anchor_count,
                endnote_count,
                mismatch_json,
                ts,
                ts,
            ],
        )?;
        Ok(())
    }

    fn replace_fnm_paragraph_footnotes(
        &self,
        doc_id: &str,
        chapter_id: &str,
        footnotes: &[ParagraphFootnoteRecord],
    ) -> Result<()> {
        let conn = self.get_conn()?;
        let ts = Self::now_ts();
        conn.execute(
            "DELETE FROM fnm_paragraph_footnotes WHERE doc_id = ?1 AND chapter_id = ?2",
            rusqlite::params![doc_id, chapter_id],
        )?;
        let mut stmt = conn.prepare(
            "INSERT INTO fnm_paragraph_footnotes
             (doc_id, chapter_id, page_no, paragraph_index, attachment_kind,
              source_marker, text, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
        )?;
        for f in footnotes {
            stmt.execute(rusqlite::params![
                doc_id,
                f.chapter_id,
                f.page_no,
                f.paragraph_index,
                f.attachment_kind,
                f.source_marker,
                f.text,
                ts,
                ts,
            ])?;
        }
        Ok(())
    }

    fn replace_fnm_chapter_endnotes(
        &self,
        doc_id: &str,
        chapter_id: &str,
        endnotes: &[ChapterEndnoteRecord],
    ) -> Result<()> {
        let conn = self.get_conn()?;
        let ts = Self::now_ts();
        conn.execute(
            "DELETE FROM fnm_chapter_endnotes WHERE doc_id = ?1 AND chapter_id = ?2",
            rusqlite::params![doc_id, chapter_id],
        )?;
        let mut stmt = conn.prepare(
            "INSERT INTO fnm_chapter_endnotes
             (doc_id, chapter_id, ordinal, marker, numbering_scheme, text,
              source_page_no, is_reconstructed, review_required, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
        )?;
        for e in endnotes {
            stmt.execute(rusqlite::params![
                doc_id,
                e.chapter_id,
                e.ordinal,
                e.marker,
                e.numbering_scheme,
                e.text,
                e.source_page_no,
                e.is_reconstructed as i64,
                e.review_required as i64,
                ts,
                ts,
            ])?;
        }
        Ok(())
    }

    // ── Translation units ──

    fn list_fnm_translation_units(&self, doc_id: &str) -> Result<Vec<TranslationUnitRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT doc_id, unit_id, kind, owner_kind, owner_id, section_id, section_title,
                    section_start_page, section_end_page, note_id, page_start, page_end,
                    char_count, source_text, translated_text, status, error_msg, target_ref,
                    page_segments_json, source_hash
             FROM fnm_translation_units WHERE doc_id = ?1
             ORDER BY page_start, unit_id",
        )?;
        let rows = stmt.query_map(rusqlite::params![doc_id], |row| {
            let seg_json: String = row.get(18)?;
            let page_segments: Vec<UnitPageSegmentRecord> =
                serde_json::from_str(&seg_json).unwrap_or_default();
            Ok(TranslationUnitRecord {
                unit_id: row.get(1)?,
                kind: row.get(2)?,
                owner_kind: row.get(3)?,
                owner_id: row.get(4)?,
                section_id: row.get(5)?,
                section_title: row.get(6)?,
                section_start_page: row.get::<_, i64>(7)?,
                section_end_page: row.get::<_, i64>(8)?,
                note_id: row.get(9)?,
                page_start: row.get::<_, i64>(10)?,
                page_end: row.get::<_, i64>(11)?,
                char_count: row.get::<_, i64>(12)?,
                source_text: row.get(13)?,
                translated_text: row.get(14)?,
                status: row.get(15)?,
                error_msg: row.get(16)?,
                target_ref: row.get(17)?,
                page_segments,
                source_hash: row.get(19)?,
                ..Default::default()
            })
        })?;
        let mut units = Vec::new();
        for row in rows {
            units.push(row?);
        }
        Ok(units)
    }

    fn replace_fnm_translation_units(
        &self,
        doc_id: &str,
        units: &[TranslationUnitRecord],
    ) -> Result<()> {
        let conn = self.get_conn()?;
        let ts = Self::now_ts();
        conn.execute(
            "DELETE FROM fnm_translation_units WHERE doc_id = ?1",
            rusqlite::params![doc_id],
        )?;
        let mut stmt = conn.prepare(
            "INSERT INTO fnm_translation_units
             (doc_id, unit_id, kind, owner_kind, owner_id, section_id, section_title,
              section_start_page, section_end_page, note_id, page_start, page_end,
              char_count, source_text, translated_text, status, error_msg, target_ref,
              page_segments_json, source_hash, segment_plan_hash, pipeline_run_id,
              stale_reason, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16,
                     ?17, ?18, ?19, ?20, ?21, ?22, ?23, ?24, ?25)",
        )?;
        for unit in units {
            let seg_json = serde_json::to_string(&unit.page_segments).unwrap_or_default();
            stmt.execute(rusqlite::params![
                doc_id,
                unit.unit_id,
                unit.kind,
                unit.owner_kind,
                unit.owner_id,
                unit.section_id,
                unit.section_title,
                unit.section_start_page,
                unit.section_end_page,
                unit.note_id,
                unit.page_start,
                unit.page_end,
                unit.char_count,
                unit.source_text,
                unit.translated_text,
                unit.status,
                unit.error_msg,
                unit.target_ref,
                seg_json,
                unit.source_hash,
                unit.segment_plan_hash,
                unit.pipeline_run_id,
                "", // stale_reason
                ts,
                ts,
            ])?;
        }
        Ok(())
    }

    fn list_fnm_structure_reviews(&self, doc_id: &str) -> Result<Vec<StructureReviewRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT review_type, chapter_id, page_start, page_end, payload_json, severity
             FROM fnm_structure_reviews WHERE doc_id = ?1",
        )?;
        let rows = stmt.query_map(rusqlite::params![doc_id], |row| {
            let payload_json: String = row.get(4)?;
            let payload: Value = serde_json::from_str(&payload_json).unwrap_or(Value::Null);
            Ok(StructureReviewRecord {
                review_id: String::new(), // 将在下方重建
                review_type: row.get(0)?,
                chapter_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                page_start: row.get::<_, Option<i64>>(2)?.unwrap_or(0),
                page_end: row.get::<_, Option<i64>>(3)?.unwrap_or(0),
                severity: row.get(5)?,
                payload,
            })
        })?;
        let mut reviews = Vec::new();
        for row in rows {
            let mut review = row?;
            // 重建 review_id
            review.review_id = format!(
                "review-{}-{}-{}-{}-{}",
                review
                    .review_type
                    .replace(|c: char| !c.is_alphanumeric(), "-"),
                review
                    .chapter_id
                    .replace(|c: char| !c.is_alphanumeric(), "-"),
                review.page_start,
                review.page_end,
                "na"
            );
            reviews.push(review);
        }
        Ok(reviews)
    }

    fn replace_fnm_structure_reviews(
        &self,
        doc_id: &str,
        reviews: &[StructureReviewRecord],
    ) -> Result<()> {
        let conn = self.get_conn()?;
        let ts = Self::now_ts();
        conn.execute(
            "DELETE FROM fnm_structure_reviews WHERE doc_id = ?1",
            rusqlite::params![doc_id],
        )?;
        let mut stmt = conn.prepare(
            "INSERT INTO fnm_structure_reviews
             (doc_id, review_type, chapter_id, page_start, page_end, payload_json, severity, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
        )?;
        for review in reviews {
            let payload_json = serde_json::to_string(&review.payload).unwrap_or_default();
            stmt.execute(rusqlite::params![
                doc_id,
                review.review_type,
                review.chapter_id,
                review.page_start,
                review.page_end,
                payload_json,
                review.severity,
                ts,
                ts,
            ])?;
        }
        Ok(())
    }

    fn replace_fnm_phase4_products(&self, doc_id: &str, payload: &Phase4Products) -> Result<()> {
        self.replace_fnm_translation_units(doc_id, &payload.translation_units)?;
        self.replace_fnm_structure_reviews(doc_id, &payload.structure_reviews)?;
        Ok(())
    }

    // ── Phase 5 ──────────────────────────────────────────────────

    fn list_fnm_chapter_markdowns(&self, doc_id: &str) -> Result<Vec<ChapterMarkdownEntry>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT chapter_id, order_idx, title, path, markdown_text,
                    start_page, end_page, pages_json
             FROM fnm_chapter_markdowns WHERE doc_id = ?1 ORDER BY order_idx",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(ChapterMarkdownEntry {
                chapter_id: row.get(0)?,
                order: row.get(1)?,
                title: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                path: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                markdown_text: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                start_page: row.get::<_, Option<i64>>(5)?.unwrap_or(0),
                end_page: row.get::<_, Option<i64>>(6)?.unwrap_or(0),
                pages: row
                    .get::<_, Option<String>>(7)?
                    .and_then(|s| serde_json::from_str(&s).ok())
                    .unwrap_or_default(),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_diagnostic_pages(&self, doc_id: &str) -> Result<Vec<DiagnosticPageRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT page_bp, status, pages, page_entries_json, fnm_source_json
             FROM fnm_diagnostic_pages WHERE doc_id = ?1 ORDER BY page_bp",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(DiagnosticPageRecord {
                _page_bp: row.get(0)?,
                _status: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                pages: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                _page_entries: row
                    .get::<_, Option<String>>(3)?
                    .and_then(|s| serde_json::from_str(&s).ok())
                    .unwrap_or_default(),
                _fnm_source: row
                    .get::<_, Option<String>>(4)?
                    .and_then(|s| serde_json::from_str(&s).ok())
                    .unwrap_or_default(),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_diagnostic_notes(&self, doc_id: &str) -> Result<Vec<DiagnosticNoteRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT note_id, section_id, section_title, section_start_page,
                    section_end_page, kind, original_marker, start_page,
                    pages_json, source_text, translated_text, translate_status, region_id
             FROM fnm_diagnostic_notes WHERE doc_id = ?1 ORDER BY note_id",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(DiagnosticNoteRecord {
                note_id: row.get(0)?,
                section_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                section_title: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                section_start_page: row.get::<_, Option<i64>>(3)?.unwrap_or(0),
                section_end_page: row.get::<_, Option<i64>>(4)?.unwrap_or(0),
                kind: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
                original_marker: row.get::<_, Option<String>>(6)?.unwrap_or_default(),
                start_page: row.get::<_, Option<i64>>(7)?.unwrap_or(0),
                pages: row
                    .get::<_, Option<String>>(8)?
                    .and_then(|s| serde_json::from_str(&s).ok())
                    .unwrap_or_default(),
                source_text: row.get::<_, Option<String>>(9)?.unwrap_or_default(),
                translated_text: row.get::<_, Option<String>>(10)?.unwrap_or_default(),
                translate_status: row.get::<_, Option<String>>(11)?.unwrap_or_default(),
                region_id: row.get::<_, Option<String>>(12)?.unwrap_or_default(),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn replace_fnm_phase5_products(&self, doc_id: &str, payload: &Phase5Products) -> Result<()> {
        let conn = self.get_conn()?;
        let ts = Self::now_ts();

        conn.execute(
            "DELETE FROM fnm_chapter_markdowns WHERE doc_id = ?1",
            [doc_id],
        )?;
        conn.execute(
            "DELETE FROM fnm_diagnostic_pages WHERE doc_id = ?1",
            [doc_id],
        )?;
        conn.execute(
            "DELETE FROM fnm_diagnostic_notes WHERE doc_id = ?1",
            [doc_id],
        )?;

        let mut stmt_cm = conn.prepare(
            "INSERT INTO fnm_chapter_markdowns
             (doc_id, chapter_id, order_idx, title, path, markdown_text,
              start_page, end_page, pages_json, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
        )?;
        for cm in &payload.chapter_markdowns {
            stmt_cm.execute(rusqlite::params![
                doc_id,
                cm.chapter_id,
                cm.order,
                cm.title,
                cm.path,
                cm.markdown_text,
                cm.start_page,
                cm.end_page,
                serde_json::to_string(&cm.pages).ok(),
                ts,
                ts,
            ])?;
        }

        let mut stmt_dp = conn.prepare(
            "INSERT INTO fnm_diagnostic_pages
             (doc_id, page_bp, status, pages, page_entries_json,
              fnm_source_json, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        )?;
        for dp in &payload.diagnostic_pages {
            stmt_dp.execute(rusqlite::params![
                doc_id,
                dp._page_bp,
                dp._status,
                dp.pages,
                serde_json::to_string(&dp._page_entries).ok(),
                serde_json::to_string(&dp._fnm_source).ok(),
                ts,
                ts,
            ])?;
        }

        let mut stmt_dn = conn.prepare(
            "INSERT INTO fnm_diagnostic_notes
             (doc_id, note_id, section_id, section_title, section_start_page,
              section_end_page, kind, original_marker, start_page, pages_json,
              source_text, translated_text, translate_status, region_id,
              created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16)",
        )?;
        for dn in &payload.diagnostic_notes {
            stmt_dn.execute(rusqlite::params![
                doc_id,
                dn.note_id,
                dn.section_id,
                dn.section_title,
                dn.section_start_page,
                dn.section_end_page,
                dn.kind,
                dn.original_marker,
                dn.start_page,
                serde_json::to_string(&dn.pages).ok(),
                dn.source_text,
                dn.translated_text,
                dn.translate_status,
                dn.region_id,
                ts,
                ts,
            ])?;
        }

        Ok(())
    }

    // ── Phase 6 ──────────────────────────────────────────────────

    fn list_fnm_export_chapters(&self, doc_id: &str) -> Result<Vec<ExportChapterRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT section_id, order_idx, title, path, content,
                    start_page, end_page, pages_json
             FROM fnm_export_chapters WHERE doc_id = ?1 ORDER BY order_idx",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(ExportChapterRecord {
                section_id: row.get(0)?,
                order: row.get(1)?,
                title: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                path: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                content: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                start_page: row.get::<_, Option<i64>>(5)?.unwrap_or(0),
                end_page: row.get::<_, Option<i64>>(6)?.unwrap_or(0),
                pages: row
                    .get::<_, Option<String>>(7)?
                    .and_then(|s| serde_json::from_str(&s).ok())
                    .unwrap_or_default(),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_export_audit(&self, doc_id: &str) -> Result<Option<ExportAuditReportRecord>> {
        let conn = self.get_conn()?;
        let mut stmt =
            conn.prepare("SELECT report_json FROM fnm_export_audit WHERE doc_id = ?1")?;
        let mut rows = stmt.query_map([doc_id], |row| {
            let json_str: String = row.get(0)?;
            serde_json::from_str::<ExportAuditReportRecord>(&json_str)
                .map_err(|e| rusqlite::Error::ToSqlConversionFailure(Box::new(e)))
        })?;
        match rows.next() {
            Some(Ok(record)) => Ok(Some(record)),
            Some(Err(e)) => Err(e.into()),
            None => Ok(None),
        }
    }

    fn replace_fnm_phase6_products(&self, doc_id: &str, payload: &Phase6Products) -> Result<()> {
        let conn = self.get_conn()?;
        let ts = Self::now_ts();

        conn.execute(
            "DELETE FROM fnm_export_chapters WHERE doc_id = ?1",
            [doc_id],
        )?;
        conn.execute("DELETE FROM fnm_export_audit WHERE doc_id = ?1", [doc_id])?;
        conn.execute("DELETE FROM fnm_export_bundle WHERE doc_id = ?1", [doc_id])?;

        let mut stmt_ec = conn.prepare(
            "INSERT INTO fnm_export_chapters
             (doc_id, section_id, order_idx, title, path, content,
              start_page, end_page, pages_json, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
        )?;
        for ec in &payload.export_chapters {
            stmt_ec.execute(rusqlite::params![
                doc_id,
                ec.section_id,
                ec.order,
                ec.title,
                ec.path,
                ec.content,
                ec.start_page,
                ec.end_page,
                serde_json::to_string(&ec.pages).ok(),
                ts,
                ts,
            ])?;
        }

        let report_json = serde_json::to_string(&payload.export_audit)?;
        conn.execute(
            "INSERT INTO fnm_export_audit (doc_id, report_json, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4)",
            rusqlite::params![doc_id, report_json, ts, ts],
        )?;

        let bundle_json = serde_json::to_string(&payload.export_bundle)?;
        conn.execute(
            "INSERT INTO fnm_export_bundle (doc_id, bundle_json, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4)",
            rusqlite::params![doc_id, bundle_json, ts, ts],
        )?;

        Ok(())
    }

    fn list_fnm_export_bundle(&self, doc_id: &str) -> Result<Option<ExportBundleRecord>> {
        let conn = self.get_conn()?;
        let mut stmt =
            conn.prepare("SELECT bundle_json FROM fnm_export_bundle WHERE doc_id = ?1")?;
        let mut rows = stmt.query_map([doc_id], |row| {
            let json_str: String = row.get(0)?;
            serde_json::from_str::<ExportBundleRecord>(&json_str)
                .map_err(|e| rusqlite::Error::ToSqlConversionFailure(Box::new(e)))
        })?;
        match rows.next() {
            Some(Ok(record)) => Ok(Some(record)),
            Some(Err(e)) => Err(e.into()),
            None => Ok(None),
        }
    }

    fn upsert_document(&self, doc_id: &str, slug: &str) -> Result<()> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare("PRAGMA table_info(documents)")?;
        let columns = stmt
            .query_map([], |row| row.get::<_, String>(1))?
            .collect::<std::result::Result<std::collections::HashSet<_>, _>>()?;

        let existing = conn.query_row(
            "SELECT COUNT(1) FROM documents WHERE id = ?1",
            [doc_id],
            |row| row.get::<_, i64>(0),
        )? > 0;
        if existing {
            if columns.contains("slug") {
                conn.execute(
                    "UPDATE documents SET slug = ?2 WHERE id = ?1",
                    rusqlite::params![doc_id, slug],
                )?;
            }
            return Ok(());
        }

        let now = Self::now_ts();
        if columns.contains("slug") {
            conn.execute(
                "INSERT INTO documents (id, slug, state) VALUES (?1, ?2, 'idle')",
                rusqlite::params![doc_id, slug],
            )?;
        } else {
            conn.execute(
                "INSERT INTO documents (id, name, created_at, updated_at) VALUES (?1, ?2, ?3, ?3)",
                rusqlite::params![doc_id, slug, now],
            )?;
        }
        Ok(())
    }

    fn get_latest_fnm_run(&self, doc_id: &str) -> Result<Option<FnmRunRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, doc_id, status, error_msg, page_count, section_count, note_count, unit_count,
                    validation_json, structure_state, review_counts_json, blocking_reasons_json,
                    link_summary_json, page_partition_summary_json, chapter_mode_summary_json,
                    created_at, updated_at
             FROM fnm_runs
             WHERE doc_id = ?1
             ORDER BY updated_at DESC, id DESC
             LIMIT 1",
        )?;
        let mut rows = stmt.query_map([doc_id], |row| {
            Ok(FnmRunRecord {
                id: row.get(0)?,
                doc_id: row.get(1)?,
                status: row.get(2)?,
                error_msg: row.get(3)?,
                page_count: row.get(4)?,
                section_count: row.get(5)?,
                note_count: row.get(6)?,
                unit_count: row.get(7)?,
                validation_json: row.get(8)?,
                structure_state: row.get(9)?,
                review_counts_json: row.get(10)?,
                blocking_reasons_json: row.get(11)?,
                link_summary_json: row.get(12)?,
                page_partition_summary_json: row.get(13)?,
                chapter_mode_summary_json: row.get(14)?,
                created_at: row.get(15)?,
                updated_at: row.get(16)?,
            })
        })?;
        match rows.next() {
            Some(Ok(record)) => Ok(Some(record)),
            Some(Err(e)) => Err(e.into()),
            None => Ok(None),
        }
    }

    // ── Input bridge (M3) ──────────────────────────────────────────

    fn load_raw_pages_for_doc(&self, doc_id: &str) -> Result<Vec<RawPage>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT payload_json, book_page FROM pages WHERE doc_id = ?1 ORDER BY book_page ASC",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            let payload: Option<String> = row.get(0)?;
            let book_page: i64 = row.get(1)?;
            // 非法 JSON 跳过+警告，NULL / 空字符串跳过；DB 行错误仍传播
            let page: RawPage = match payload {
                Some(ref s) if !s.trim().is_empty() => match serde_json::from_str(s) {
                    Ok(p) => p,
                    Err(e) => {
                        eprintln!(
                            "[WARNING] load_raw_pages_for_doc: book_page={} \
                             invalid payload_json: {}",
                            book_page, e
                        );
                        return Ok(None);
                    }
                },
                _ => return Ok(None),
            };
            Ok(Some(page))
        })?;
        let mut pages = Vec::new();
        for row in rows {
            match row {
                Ok(Some(page)) => pages.push(page),
                Ok(None) => {} // 跳过非法 JSON / NULL payload
                Err(e) => return Err(e.into()),
            }
        }
        Ok(pages)
    }

    fn load_toc_items_for_doc(&self, doc_id: &str) -> Result<Vec<TocItem>> {
        let conn = self.get_conn()?;

        // 优先级：toc_user_json（最高）> toc_auto_visual_json > toc_auto_pdf_json（最低）
        let mut stmt = conn.prepare(
            "SELECT toc_user_json, toc_auto_visual_json, toc_auto_pdf_json
             FROM documents WHERE id = ?1",
        )?;
        let mut rows = stmt.query_map(
            [doc_id],
            |row| -> std::result::Result<(Value, Value, Value), rusqlite::Error> {
                let parse = |idx: usize| -> rusqlite::Result<Value> {
                    let raw: Option<String> = row.get(idx)?;
                    Ok(raw
                        .and_then(|s| serde_json::from_str(&s).ok())
                        .unwrap_or(Value::Null))
                };
                Ok((parse(0)?, parse(1)?, parse(2)?))
            },
        )?;

        let (_user, _visual, _pdf) = match rows.next() {
            Some(Ok(triple)) => triple,
            Some(Err(e)) => return Err(e.into()),
            None => return Ok(vec![]),
        };

        // 选第一个非空数据源（按优先级）
        let source_json = _user
            .as_array()
            .filter(|a| !a.is_empty())
            .or_else(|| _visual.as_array().filter(|a| !a.is_empty()))
            .or_else(|| _pdf.as_array().filter(|a| !a.is_empty()));

        let items: Vec<TocItem> = match source_json {
            Some(arr) => arr
                .iter()
                .filter_map(|v| serde_json::from_value(v.clone()).ok())
                .collect(),
            None => vec![],
        };
        Ok(items)
    }

    fn create_fnm_run(&self, doc_id: &str, page_count: i64) -> Result<i64> {
        let conn = self.get_conn()?;
        let now = Self::now_ts();
        conn.execute(
            "INSERT INTO fnm_runs (doc_id, status, page_count, created_at, updated_at) VALUES (?1, 'running', ?2, ?3, ?3)",
            rusqlite::params![doc_id, page_count, now],
        )?;
        Ok(conn.last_insert_rowid())
    }

    fn update_fnm_run(&self, params: UpdateFnmRunParams<'_>) -> Result<()> {
        let conn = self.get_conn()?;
        let now = Self::now_ts();
        conn.execute(
            "UPDATE fnm_runs SET status = ?1, section_count = ?2, note_count = ?3, unit_count = ?4, structure_state = ?5, blocking_reasons_json = ?6, error_msg = ?7, updated_at = ?8 WHERE id = ?9",
            rusqlite::params![params.status, params.section_count, params.note_count, params.unit_count, params.structure_state, params.blocking_reasons_json, params.error_msg, now, params.run_id],
        )?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db::schema;

    fn setup_repo() -> SqliteRepository {
        let manager = r2d2_sqlite::SqliteConnectionManager::memory();
        let pool = Pool::builder().build(manager).unwrap();
        let conn = pool.get().unwrap();
        conn.execute_batch("PRAGMA foreign_keys=ON;").unwrap();
        schema::run_migrations(&conn).unwrap();
        // 创建 pages 表（Python 侧建表，Rust 迁移不包含）
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS pages (
                row_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id       TEXT NOT NULL,
                book_page    INTEGER NOT NULL,
                payload_json TEXT
            );",
        )
        .unwrap();
        // 添加 TOC 列（Python 侧 ALTER TABLE 加列，Rust 迁移不包含）
        for col in &["toc_user_json", "toc_auto_visual_json", "toc_auto_pdf_json"] {
            let sql = format!("ALTER TABLE documents ADD COLUMN {} TEXT DEFAULT '[]'", col);
            let _ = conn.execute_batch(&sql); // 忽略已存在错误
        }
        SqliteRepository::new(pool)
    }

    fn seed_page(repo: &SqliteRepository, doc_id: &str, book_page: i64, markdown: &str) {
        let conn = repo.get_conn().unwrap();
        let payload = serde_json::json!({
            "bookPage": book_page,
            "markdown": markdown,
        });
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?1, ?2, ?3)",
            rusqlite::params![doc_id, book_page, payload.to_string()],
        )
        .unwrap();
    }

    // ── Tests ──────────────────────────────────────────────────────

    #[test]
    fn load_raw_pages_empty_when_no_pages() {
        let repo = setup_repo();
        let pages = repo.load_raw_pages_for_doc("no-such-doc").unwrap();
        assert!(pages.is_empty(), "expected empty vec for unknown doc_id");
    }

    #[test]
    fn load_raw_pages_returns_pages_ordered_by_book_page() {
        let repo = setup_repo();
        seed_page(&repo, "doc-1", 3, "page three");
        seed_page(&repo, "doc-1", 1, "page one");
        seed_page(&repo, "doc-1", 2, "page two");

        let pages = repo.load_raw_pages_for_doc("doc-1").unwrap();
        assert_eq!(pages.len(), 3);
        assert_eq!(pages[0].book_page, 1);
        assert_eq!(pages[0].markdown, "page one");
        assert_eq!(pages[1].book_page, 2);
        assert_eq!(pages[1].markdown, "page two");
        assert_eq!(pages[2].book_page, 3);
        assert_eq!(pages[2].markdown, "page three");
    }

    #[test]
    fn load_raw_pages_handles_optional_fields() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        let payload = serde_json::json!({
            "bookPage": 1,
            "markdown": "body",
            "enriched_markdown": "enriched",
            "pdfPage": 42,
            "fileIdx": 7,
            "prunedResult": {"key": "val"},
        });
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json)
             VALUES (?1, 1, ?2)",
            rusqlite::params!["doc-opt", payload.to_string()],
        )
        .unwrap();

        let pages = repo.load_raw_pages_for_doc("doc-opt").unwrap();
        assert_eq!(pages.len(), 1);
        assert_eq!(pages[0].book_page, 1);
        assert_eq!(pages[0].markdown, "body");
        assert_eq!(pages[0].enriched_markdown.as_deref(), Some("enriched"));
        assert_eq!(pages[0].pdf_page, Some(42));
        assert_eq!(pages[0].file_idx, Some(7));
        assert_eq!(pages[0].pruned_result["key"], "val");
        // 未设置的字段应为默认值
        assert!(pages[0].note_scan.is_none());
        assert!(pages[0].target_pdf_page.is_none());
    }

    #[test]
    fn load_raw_pages_skips_null_payload() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?1, 1, NULL)",
            rusqlite::params!["doc-null"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?1, 2, '')",
            rusqlite::params!["doc-null"],
        )
        .unwrap();
        let payload = serde_json::json!({"bookPage": 3, "markdown": "valid"});
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?1, 3, ?2)",
            rusqlite::params!["doc-null", payload.to_string()],
        )
        .unwrap();

        let pages = repo.load_raw_pages_for_doc("doc-null").unwrap();
        assert_eq!(pages.len(), 1, "NULL and empty rows should be skipped");
        assert_eq!(pages[0].book_page, 3);
    }

    #[test]
    fn load_toc_items_pdf_fallback() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO documents (id, slug, toc_auto_pdf_json)
             VALUES (?1, 'test',
               '[{\"item_id\":\"pdf-1\",\"title\":\"Pdf Ch\",\"level\":1,\"depth\":0,\"role_hint\":\"chapter\"}]')",
            rusqlite::params!["doc-pdf-fb"],
        )
        .unwrap();

        let items = repo.load_toc_items_for_doc("doc-pdf-fb").unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].item_id, "pdf-1");
    }

    #[test]
    fn load_toc_items_skips_invalid_json_in_user_col() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO documents (id, slug, toc_user_json, toc_auto_visual_json)
             VALUES (?1, 'test',
               'not valid json',
               '[{\"item_id\":\"vis-1\",\"title\":\"Vis Ch\",\"level\":1,\"depth\":0,\"role_hint\":\"chapter\"}]')",
            rusqlite::params!["doc-bad-json"],
        )
        .unwrap();

        let items = repo.load_toc_items_for_doc("doc-bad-json").unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].item_id, "vis-1");
    }

    #[test]
    fn load_toc_items_prefers_user_over_visual() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO documents (id, slug, toc_user_json, toc_auto_visual_json, toc_auto_pdf_json)
             VALUES (?1, 'test',
               '[{\"item_id\":\"user-1\",\"title\":\"User Ch\",\"level\":1,\"depth\":0,\"role_hint\":\"chapter\"}]',
               '[{\"item_id\":\"vis-1\",\"title\":\"Vis Ch\",\"level\":1,\"depth\":0,\"role_hint\":\"chapter\"}]',
               '[{\"item_id\":\"pdf-1\",\"title\":\"Pdf Ch\",\"level\":1,\"depth\":0,\"role_hint\":\"chapter\"}]')",
            rusqlite::params!["doc-toc-prio"],
        )
        .unwrap();

        let items = repo.load_toc_items_for_doc("doc-toc-prio").unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].item_id, "user-1");
        assert_eq!(items[0].title, "User Ch");
    }

    #[test]
    fn load_toc_items_falls_back_visual_when_user_empty() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO documents (id, slug, toc_user_json, toc_auto_visual_json)
             VALUES (?1, 'test',
               '[]',
               '[{\"item_id\":\"vis-1\",\"title\":\"Vis Ch\",\"level\":1,\"depth\":0,\"role_hint\":\"chapter\"}]')",
            rusqlite::params!["doc-toc-fb"],
        )
        .unwrap();

        let items = repo.load_toc_items_for_doc("doc-toc-fb").unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].item_id, "vis-1");
    }

    #[test]
    fn load_toc_items_returns_empty_when_no_toc() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO documents (id, slug) VALUES (?1, 'no-toc')",
            rusqlite::params!["doc-no-toc"],
        )
        .unwrap();

        let items = repo.load_toc_items_for_doc("doc-no-toc").unwrap();
        assert!(items.is_empty());
    }

    // ── documents schema 兼容性 ──────────────────────────────────────

    fn setup_schema_custom(documents_ddl: &str) -> SqliteRepository {
        let manager = r2d2_sqlite::SqliteConnectionManager::memory();
        let pool = Pool::builder().build(manager).unwrap();
        let conn = pool.get().unwrap();
        conn.execute_batch("PRAGMA foreign_keys=ON;").unwrap();
        conn.execute_batch(documents_ddl).unwrap();
        // 跑 fnm_* 迁移（`schema::run_migrations` 会 CREATE TABLE IF NOT EXISTS documents，
        // 但我们的 documents 已经定义好了，migrations 会因 IF NOT EXISTS 而跳过）
        schema::run_migrations(&conn).unwrap();
        SqliteRepository::new(pool)
    }

    #[test]
    fn upsert_document_legacy_schema_insert() {
        let repo = setup_schema_custom(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, slug TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'idle');",
        );
        repo.upsert_document("legacy-1", "legacy-book").unwrap();

        let conn = repo.get_conn().unwrap();
        let (id, slug, state): (String, String, String) = conn
            .query_row(
                "SELECT id, slug, state FROM documents WHERE id = ?1",
                ["legacy-1"],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        assert_eq!(id, "legacy-1");
        assert_eq!(slug, "legacy-book");
        assert_eq!(state, "idle");
    }

    #[test]
    fn upsert_document_legacy_schema_update() {
        let repo = setup_schema_custom(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, slug TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'idle');",
        );
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO documents (id, slug, state) VALUES ('legacy-2', 'old-slug', 'done')",
            [],
        )
        .unwrap();

        repo.upsert_document("legacy-2", "new-slug").unwrap();

        let slug: String = conn
            .query_row(
                "SELECT slug FROM documents WHERE id = ?1",
                ["legacy-2"],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(slug, "new-slug");
        // 原有 state 不应被覆盖
        let state: String = conn
            .query_row(
                "SELECT state FROM documents WHERE id = ?1",
                ["legacy-2"],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(state, "done");
    }

    #[test]
    fn upsert_document_app_schema_insert() {
        let repo = setup_schema_custom(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', created_at TEXT, updated_at TEXT);",
        );
        repo.upsert_document("app-1", "app-book").unwrap();

        let conn = repo.get_conn().unwrap();
        let (id, name): (String, String) = conn
            .query_row(
                "SELECT id, name FROM documents WHERE id = ?1",
                ["app-1"],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(id, "app-1");
        assert_eq!(name, "app-book");
        // created_at / updated_at 应该是同一个时间戳
        let created: String = conn
            .query_row(
                "SELECT created_at FROM documents WHERE id = ?1",
                ["app-1"],
                |r| r.get(0),
            )
            .unwrap();
        let updated: String = conn
            .query_row(
                "SELECT updated_at FROM documents WHERE id = ?1",
                ["app-1"],
                |r| r.get(0),
            )
            .unwrap();
        assert!(!created.is_empty());
        assert_eq!(created, updated);
    }

    #[test]
    fn upsert_document_app_schema_update() {
        let repo = setup_schema_custom(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', created_at TEXT, updated_at TEXT);",
        );
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO documents (id, name) VALUES ('app-2', 'old-name')",
            [],
        )
        .unwrap();

        repo.upsert_document("app-2", "new-name").unwrap();

        let name: String = conn
            .query_row("SELECT name FROM documents WHERE id = ?1", ["app-2"], |r| {
                r.get(0)
            })
            .unwrap();
        // app schema 无 slug 列，upsert 不会覆盖 name
        assert_eq!(
            name, "old-name",
            "app schema without slug column should not modify name"
        );
    }

    // ── 3.3a: fnm_run CRUD ──

    fn seed_doc(repo: &SqliteRepository, doc_id: &str) {
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT OR IGNORE INTO documents (id, slug) VALUES (?1, ?1)",
            rusqlite::params![doc_id],
        )
        .unwrap();
    }

    #[test]
    fn create_fnm_run_returns_nonzero_id() {
        let repo = setup_repo();
        seed_doc(&repo, "run-doc-1");

        let run_id = repo.create_fnm_run("run-doc-1", 42).unwrap();
        assert!(run_id > 0, "run_id should be positive, got {}", run_id);
    }

    #[test]
    fn update_fnm_run_changes_status() {
        let repo = setup_repo();
        seed_doc(&repo, "run-doc-2");

        let run_id = repo.create_fnm_run("run-doc-2", 10).unwrap();

        repo.update_fnm_run(UpdateFnmRunParams {
            run_id,
            status: "done",
            section_count: 3,
            note_count: 15,
            unit_count: 8,
            structure_state: "needs_review",
            blocking_reasons_json: "[]",
            error_msg: "",
        })
        .unwrap();

        // 读回来验证
        let run = repo
            .get_latest_fnm_run("run-doc-2")
            .unwrap()
            .expect("run exists");
        assert_eq!(run.status, "done");
        assert_eq!(run.page_count, 10);
        assert_eq!(run.section_count, 3);
        assert_eq!(run.note_count, 15);
        assert_eq!(run.unit_count, 8);
        assert_eq!(run.structure_state.as_deref(), Some("needs_review"));
        assert!(run.updated_at > 0);
    }

    #[test]
    fn invalid_note_kind_reads_back_as_unknown() {
        let repo = setup_repo();
        seed_doc(&repo, "kind-test");
        let conn = repo.get_conn().unwrap();

        conn.execute(
            "INSERT INTO fnm_note_regions (doc_id, region_id, region_kind, start_page, end_page, pages_json, region_scope, region_source, start_reason, end_reason, review_required, created_at, updated_at) VALUES ('kind-test', 'r1', 'garbage_kind', 1, 2, '[]', 'chapter', 'heading_scan', '', '', 0, 0, 0)",
            [],
        ).unwrap();
        conn.execute(
            "INSERT INTO fnm_note_items (doc_id, note_item_id, note_kind, marker_type, item_source, source_page_label, is_reconstructed, review_required, page_no, created_at, updated_at) VALUES ('kind-test', 'n1', 'garbage_kind', '', '', '', 0, 0, 1, 0, 0)",
            [],
        ).unwrap();
        conn.execute(
            "INSERT INTO fnm_note_links (doc_id, link_id, status, note_kind, created_at, updated_at) VALUES ('kind-test', 'l1', 'matched', 'garbage_kind', 0, 0)",
            [],
        ).unwrap();

        let regions = repo.list_fnm_note_regions("kind-test").unwrap();
        assert_eq!(regions.len(), 1);
        assert_eq!(regions[0].note_kind, NoteKind::Unknown);

        let items = repo.list_fnm_note_items("kind-test").unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].note_kind, NoteKind::Unknown);

        let links = repo.list_fnm_note_links("kind-test").unwrap();
        assert_eq!(links.len(), 1);
        assert_eq!(links[0].note_kind, NoteKind::Unknown);
    }

    #[test]
    fn load_raw_pages_skips_invalid_json() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES ('json-skip', 1, 'not-valid-json')",
            [],
        ).unwrap();

        let result = repo.load_raw_pages_for_doc("json-skip");
        assert!(
            result.is_ok(),
            "invalid JSON should be skipped with warning, not error out"
        );
        assert!(
            result.unwrap().is_empty(),
            "invalid JSON should produce no pages"
        );
    }

    #[test]
    fn load_raw_pages_propagates_db_row_error() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        // 插入 blob 类型的 payload_json，触发 DB 行读取错误
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES ('row-err', 1, ?1)",
            [rusqlite::types::Value::Blob(vec![0xFF, 0xFE])],
        )
        .unwrap();

        let result = repo.load_raw_pages_for_doc("row-err");
        assert!(
            result.is_err(),
            "DB row read error (type mismatch) should propagate as error"
        );
    }

    #[test]
    fn load_toc_items_fails_on_blob_in_toc_col() {
        let repo = setup_repo();
        let conn = repo.get_conn().unwrap();
        conn.execute(
            "INSERT INTO documents (id, slug, toc_user_json) VALUES ('toc-blob', 'test', ?1)",
            rusqlite::params![rusqlite::types::Value::Blob(vec![0xFF, 0xFE])],
        )
        .unwrap();

        let result = repo.load_toc_items_for_doc("toc-blob");
        assert!(
            result.is_err(),
            "BLOB in TOC col should cause row.get error to propagate"
        );
    }
}
