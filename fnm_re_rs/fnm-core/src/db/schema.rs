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
    Ok(())
}
