//! Phase 4 输出类型契约。
//!
//! 薄包装 fnm-core 已有类型。
//!
//! 待实现：M1.1 任务

use fnm_core::records::{FrozenRefEntry, FrozenUnits};
use serde_json::Value;

/// ←→ Python `ModuleResult[FrozenUnits]`
pub struct Phase4Output {
    pub frozen_units: FrozenUnits,
    pub frozen_refs: Vec<FrozenRefEntry>,
    pub freeze_summary: Value,
}
