//! DB 访问层：Repository trait + SQLite 实现 + 连接池。

pub mod pool;
pub mod repository;
pub mod schema;

pub use pool::{open_pool, SqlitePool};
pub use repository::{
    Phase1Products, Phase2Products, Phase3Products, Phase4Products, Phase5Products, Phase6Products,
    Repository, SqliteRepository, UpdateFnmRunParams,
};
