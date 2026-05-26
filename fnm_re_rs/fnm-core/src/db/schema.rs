//! Schema 迁移加载。在首次连接时按序执行 migrations/*.sql。

use anyhow::Result;
use rusqlite::Connection;

const MIGRATION_0001: &str = include_str!("../../migrations/0001_initial.sql");
const MIGRATION_0002: &str = include_str!("../../migrations/0002_add_missing_tables.sql");
const MIGRATION_0003: &str = include_str!("../../migrations/0003_phase56_tables.sql");

/// 在给定的 SQLite 连接上执行所有迁移（按版本号顺序）。
pub fn run_migrations(conn: &Connection) -> Result<()> {
    conn.execute_batch(MIGRATION_0001)?;
    conn.execute_batch(MIGRATION_0002)?;
    conn.execute_batch(MIGRATION_0003)?;
    ensure_contract_columns(conn)?;
    Ok(())
}

/// 为旧数据库补充合同列，但不为既有行猜测事实值。
///
/// 旧行在这些列上保持 `NULL`，repository 读回时会明确失败，从而要求重新生成
/// Phase1-3，而不是以伪造默认值进入下游回放。
fn ensure_contract_columns(conn: &Connection) -> Result<()> {
    for (table, columns) in [
        ("fnm_section_heads", &[("level", "INTEGER")][..]),
        (
            "fnm_note_regions",
            &[
                ("region_scope", "TEXT"),
                ("region_source", "TEXT"),
                ("start_reason", "TEXT"),
                ("end_reason", "TEXT"),
                ("review_required", "INTEGER"),
            ][..],
        ),
        (
            "fnm_chapter_note_modes",
            &[
                ("region_ids_json", "TEXT"),
                ("primary_region_scope", "TEXT"),
                ("has_footnote_band", "INTEGER"),
                ("has_endnote_region", "INTEGER"),
            ][..],
        ),
        (
            "fnm_note_items",
            &[
                ("marker_type", "TEXT"),
                ("item_source", "TEXT"),
                ("source_page_label", "TEXT"),
                ("is_reconstructed", "INTEGER"),
                ("review_required", "INTEGER"),
                ("projection_mode", "TEXT"),
                ("owner_chapter_id", "TEXT"),
            ][..],
        ),
        (
            "fnm_body_anchors",
            &[
                ("anchor_source", "TEXT"),
                ("synthetic", "INTEGER"),
                ("ocr_repaired_from_marker", "TEXT"),
                ("coordinate_unit", "TEXT"),
            ][..],
        ),
    ] {
        for (column, sql_type) in columns {
            ensure_column(conn, table, column, sql_type)?;
        }
    }
    Ok(())
}

fn ensure_column(conn: &Connection, table: &str, column: &str, sql_type: &str) -> Result<()> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info({table})"))?;
    let present = stmt
        .query_map([], |row| row.get::<_, String>(1))?
        .collect::<rusqlite::Result<Vec<_>>>()?
        .iter()
        .any(|existing| existing == column);
    if !present {
        conn.execute_batch(&format!(
            "ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
        ))?;
    }
    Ok(())
}
