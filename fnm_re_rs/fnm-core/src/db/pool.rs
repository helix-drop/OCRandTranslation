//! r2d2_sqlite 连接池封装。

use crate::db::schema;
use anyhow::{Context, Result};
use r2d2::Pool;
use r2d2_sqlite::SqliteConnectionManager;
use std::path::Path;

pub type SqlitePool = Pool<SqliteConnectionManager>;

/// 打开数据库连接池，同时运行迁移。
pub fn open_pool(db_path: &Path) -> Result<SqlitePool> {
    let manager = SqliteConnectionManager::file(db_path)
        .with_init(|c| c.execute_batch("PRAGMA foreign_keys=ON;"));
    let pool = Pool::builder()
        .max_size(4)
        .build(manager)
        .context("failed to create SQLite connection pool")?;

    // 运行迁移（WAL 是 per-database 设置，设一次即可）
    {
        let conn = pool.get()?;
        conn.execute_batch("PRAGMA journal_mode=WAL;")?;
        schema::run_migrations(&conn)?;
    }

    Ok(pool)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn pool_all_connections_have_fk_enabled() {
        // B1-3: 验证池中每个连接都有 foreign_keys=ON。
        // 旧代码只在迁移连接设 PRAGMA，新建连接默认 OFF。
        let tmp = TempDir::new().unwrap();
        let db_path = tmp.path().join("test_fk.db");
        let pool = open_pool(&db_path).unwrap();

        // 连续取 4 个连接（max_size=4），每个都应有 FK=ON
        for i in 0..4 {
            let conn = pool.get().unwrap();
            let fk: i32 = conn
                .query_row("PRAGMA foreign_keys", [], |r| r.get(0))
                .unwrap();
            assert_eq!(fk, 1, "连接 {} foreign_keys 应为 1（ON）", i);
        }
    }

    #[test]
    fn pool_wal_mode_persisted_across_connections() {
        // WAL 是 per-database 设置，验证所有连接都看到 WAL 模式
        let tmp = TempDir::new().unwrap();
        let db_path = tmp.path().join("test_wal.db");
        let pool = open_pool(&db_path).unwrap();

        let conn = pool.get().unwrap();
        let journal: String = conn
            .query_row("PRAGMA journal_mode", [], |r| r.get(0))
            .unwrap();
        assert_eq!(journal, "wal", "应为 WAL 模式");
    }
}
