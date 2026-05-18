//! `fnm-phase4` — FNM_RE Phase 4: 引用冻结 + 翻译单元 + 结构复核。
//!
//! ←→ Python:
//! - `FNM_RE/modules/ref_freeze.py` (~678 行) → `ref_freeze/`
//! - `FNM_RE/stages/units.py` (~868 行) → `segments/`
//! - `FNM_RE/stages/reviews.py` (~210 行) → 待 M3
//! - `document/text_processing.py` (~350 行) → `text/`
//!
//! # 上游依赖
//!
//! - Phase 3 已完成（14/14 任务）
//! - 已知 Phase 2 cascade 影响 5 个 Phase 3 parity 测试 `#[ignore]`——
//!   不阻塞 Phase 4 启动

#![deny(unused_must_use)]

pub mod input;
pub mod output;
pub mod text;
pub mod segments;
pub mod ref_freeze;

// re-export 主入口（等实现完成后启用）
// pub use ref_freeze::build_frozen_units;
