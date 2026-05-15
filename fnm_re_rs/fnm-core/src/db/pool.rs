//! r2d2_sqlite 连接池封装。

use crate::db::schema;
use anyhow::{Context, Result};
use r2d2::Pool;
use r2d2_sqlite::SqliteConnectionManager;
use std::path::Path;

pub type SqlitePool = Pool<SqliteConnectionManager>;

/// 打开数据库连接池，同时运行迁移。
pub fn open_pool(db_path: &Path) -> Result<SqlitePool> {
    let manager = SqliteConnectionManager::file(db_path);
    let pool = Pool::builder()
        .max_size(4)
        .build(manager)
        .context("failed to create SQLite connection pool")?;

    // 运行迁移
    {
        let conn = pool.get()?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
        schema::run_migrations(&conn)?;
    }

    Ok(pool)
}
