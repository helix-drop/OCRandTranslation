//! Repository trait + SQLite 实现。
//!
//! 封装所有 `fnm_*` 表的读写，后续 phase crate 通过此 trait 操作 DB。

use crate::records::*;
use crate::types::*;
use anyhow::{Context, Result};
use r2d2::Pool;
use r2d2_sqlite::SqliteConnectionManager;
use std::str::FromStr;

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

// ── Repository trait ─────────────────────────────────────────────

pub trait Repository {
    // ── Phase 1 ──
    fn list_fnm_pages(&self, doc_id: &str) -> Result<Vec<PagePartitionRecord>>;
    fn list_fnm_chapters(&self, doc_id: &str) -> Result<Vec<ChapterRecord>>;
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
    fn replace_fnm_phase3_products(&self, doc_id: &str, payload: &Phase3Products) -> Result<()>;
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
             normalized_text, source, block_label, top_band, confidence,
             heading_family_guess, suppressed_as_chapter, reject_reason,
             created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
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
                hc.confidence,
                hc.heading_family_guess,
                hc.suppressed_as_chapter as i64,
                hc.reject_reason,
                ts,
                ts,
            ])?;
        }

        // 插入 section_heads
        let mut stmt = conn.prepare(
            "INSERT INTO fnm_section_heads (doc_id, section_head_id, chapter_id, page_no,
             text, normalized_text, source, confidence, heading_family_guess,
             rejected_chapter_candidate, reject_reason, derived_from_heading_id,
             created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
        )?;
        for sh in section_heads {
            stmt.execute(rusqlite::params![
                doc_id,
                sh.section_head_id,
                sh.chapter_id,
                sh.page_no,
                sh.title,
                sh.title,
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
                pages: row
                    .get::<_, Option<String>>(4)?
                    .and_then(|s| serde_json::from_str(&s).ok())
                    .unwrap_or_default(),
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
            "SELECT section_head_id, chapter_id, text, page_no, 0, source
             FROM fnm_section_heads WHERE doc_id = ?1 ORDER BY page_no",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(SectionHeadRecord {
                section_head_id: row.get(0)?,
                chapter_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                title: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                page_no: row.get(3)?,
                level: 0,
                source: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
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
                    region_kind, 'chapter', 'heading_scan', title_hint, '', '',
                    region_marker_alignment_ok, region_start_first_source_marker,
                    region_first_note_item_marker, 0
             FROM fnm_note_regions WHERE doc_id = ?1 ORDER BY start_page",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(NoteRegionRecord {
                region_id: row.get(0)?,
                chapter_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                page_start: row.get(2)?,
                page_end: row.get(3)?,
                pages: row
                    .get::<_, Option<String>>(4)?
                    .and_then(|s| serde_json::from_str(&s).ok())
                    .unwrap_or_default(),
                note_kind: NoteKind::from_str(&row.get::<_, String>(5)?)
                    .unwrap_or(NoteKind::Footnote),
                scope: RegionScope::Chapter,
                source: RegionSource::HeadingScan,
                heading_text: row.get::<_, Option<String>>(8)?.unwrap_or_default(),
                start_reason: String::new(),
                end_reason: String::new(),
                region_marker_alignment_ok: row.get::<_, i64>(11)? != 0,
                region_start_first_source_marker: row
                    .get::<_, Option<String>>(12)?
                    .unwrap_or_default(),
                region_first_note_item_marker: row
                    .get::<_, Option<String>>(13)?
                    .unwrap_or_default(),
                review_required: false,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_note_items(&self, doc_id: &str) -> Result<Vec<NoteItemRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT note_item_id, region_id, chapter_id, page_no, marker,
                    note_kind, source_text, display_marker, source_marker, 0, 0
             FROM fnm_note_items WHERE doc_id = ?1 ORDER BY page_no, marker",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(NoteItemRecord {
                note_item_id: row.get(0)?,
                region_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                chapter_id: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                page_no: row.get(3)?,
                marker: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                marker_type: String::new(),
                text: row.get::<_, Option<String>>(6)?.unwrap_or_default(),
                source: row.get::<_, Option<String>>(7)?.unwrap_or_default(),
                source_page_label: row.get::<_, Option<String>>(8)?.unwrap_or_default(),
                is_reconstructed: row.get::<_, Option<i64>>(9)?.unwrap_or(0) != 0,
                review_required: row.get::<_, Option<i64>>(10)?.unwrap_or(0) != 0,
                note_kind: NoteKind::from_str(&row.get::<_, String>(5)?)
                    .unwrap_or(NoteKind::Footnote),
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn list_fnm_chapter_note_modes(&self, doc_id: &str) -> Result<Vec<ChapterNoteModeRecord>> {
        let conn = self.get_conn()?;
        let mut stmt = conn.prepare(
            "SELECT chapter_id, note_mode
             FROM fnm_chapter_note_modes WHERE doc_id = ?1 ORDER BY chapter_id",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
            Ok(ChapterNoteModeRecord {
                chapter_id: row.get(0)?,
                note_mode: NoteMode::from_str(&row.get::<_, String>(1)?)
                    .unwrap_or(NoteMode::ReviewRequired),
                region_ids: vec![],
                primary_region_scope: String::new(),
                has_footnote_band: false,
                has_endnote_region: false,
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
             region_start_first_source_marker, region_first_note_item_marker,
             region_marker_alignment_ok, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13)",
        )?;
        for r in &payload.note_regions {
            stmt_region.execute(rusqlite::params![
                doc_id,
                r.region_id,
                r.note_kind.as_str(),
                r.page_start,
                r.page_end,
                serde_json::to_string(&r.pages).ok(),
                r.heading_text,
                r.chapter_id,
                r.region_start_first_source_marker,
                r.region_first_note_item_marker,
                r.region_marker_alignment_ok as i64,
                ts,
                ts,
            ])?;
        }

        let mut stmt_mode = conn.prepare(
            "INSERT INTO fnm_chapter_note_modes (doc_id, chapter_id, chapter_title,
             note_mode, sampled_pages_json, detection_confidence, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        )?;
        for cm in &payload.chapter_note_modes {
            stmt_mode.execute(rusqlite::params![
                doc_id,
                cm.chapter_id,
                "",
                cm.note_mode.as_str(),
                serde_json::to_string(&cm.region_ids).ok(),
                1.0_f64,
                ts,
                ts,
            ])?;
        }

        let mut stmt_item = conn.prepare(
            "INSERT INTO fnm_note_items (doc_id, note_item_id, note_kind,
             chapter_id, region_id, marker, normalized_marker, occurrence,
             source_text, page_no, display_marker, source_marker, title_hint,
             created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
        )?;
        for item in &payload.note_items {
            stmt_item.execute(rusqlite::params![
                doc_id,
                item.note_item_id,
                item.note_kind.as_str(),
                item.chapter_id,
                item.region_id,
                item.marker,
                item.marker,
                1_i64,
                item.text,
                item.page_no,
                item.source,
                item.source_page_label,
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
                    source_text, '', 0, ''
             FROM fnm_body_anchors WHERE doc_id = ?1 ORDER BY page_no, paragraph_index",
        )?;
        let rows = stmt.query_map([doc_id], |row| {
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
                source: row.get::<_, Option<String>>(11)?.unwrap_or_default(),
                synthetic: row.get::<_, i64>(12)? != 0,
                ocr_repaired_from_marker: row.get::<_, Option<String>>(13)?.unwrap_or_default(),
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
                .unwrap_or(NoteKind::Footnote),
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
             anchor_kind, certainty, source_text, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
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
}
