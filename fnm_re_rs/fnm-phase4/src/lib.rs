//! `fnm-phase4` — FNM_RE Phase 4: 引用冻结 + 翻译单元 + 结构复核。
//!
//! ←→ Python:
//! - `FNM_RE/modules/ref_freeze.py` (~678 行) → `ref_freeze.rs`
//! - `FNM_RE/stages/units.py` (~868 行) → `units.rs`
//! - `FNM_RE/stages/reviews.py` (~210 行) → `reviews.rs`
//!
//! # 状态：**骨架（kickoff）**
//!
//! 当前是 Phase 4 启动占位 — 仅 Cargo.toml + lib.rs + 子模块声明。
//! 完整任务清单见 [`FNM_RE/FNM_PHASE4_PLAN.md`](../../../FNM_RE/FNM_PHASE4_PLAN.md)。
//!
//! # 上游依赖
//!
//! - Phase 3 已完成（14/14 任务，commit `346f437` + `3ff8cdf`）
//! - 已知 Phase 2 cascade 影响 5 个 Phase 3 parity 测试 `#[ignore]`——
//!   不阻塞 Phase 4 启动（Phase 4 消费 Phase 3 effective_links + body_anchors，
//!   即使数量略多于 Python golden，业务逻辑仍可推进）
//!
//! # 模块占位（待实现）
//!
//! - `input` / `output`: 类型契约
//! - `ref_freeze`: build_frozen_units 编排（最大头，~600 行）
//! - `units`: build_translation_units（~800 行）
//! - `reviews`: build_structure_reviews（~200 行）

#![deny(unused_must_use)]

// 待实现：
// pub mod input;
// pub mod output;
// pub mod ref_freeze;
// pub mod units;
// pub mod reviews;

/// 占位入口——签名稳定后展开为完整 build_phase4_structure。
pub fn placeholder() {
    // 待 FNM_PHASE4_PLAN.md P4.0 完成后删除。
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn placeholder_runs() {
        placeholder();
    }
}
