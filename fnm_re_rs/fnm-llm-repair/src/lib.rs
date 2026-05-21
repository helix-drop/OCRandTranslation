//! `fnm-llm-repair` — FNM Step 3.5: LLM 修补未解析 cluster。
//!
//! ←→ Python `FNM_RE/modules/llm_repair.py`（2087 行 / 51 函数）
//!
//! 模块组织（按数据流顺序）：
//! - `usage` — token 用量统计 + 超时保护
//! - `cluster` — build_unresolved_clusters：从 note_links 收集未解析簇
//! - `page_context` — 页面上下文构建（章节正文 + OCR 摘录 + 图像）
//! - `prompt_builder` — system / user prompt 组装
//! - `response_parser` — LLM JSON 响应解析 + 自动应用筛选
//! - `strategies::fuzzy` — Tier 1 fuzzy anchor synthesis
//! - `override_materializer` — LLM action → ReviewOverride 物化
//! - `llm_client` — vision/text LLM 调用 + 降级
//! - `run` — `run_llm_repair` 顶层编排
//!
//! # 上游依赖
//!
//! - Phase 3 已完成（提供 note_links 和 orphan candidates）
//! - fnm-core ResolvedModelSpec 已就绪（5 家 provider）

#![deny(unused_must_use)]

pub mod cluster;
pub mod llm_client;
pub mod override_materializer;
pub mod page_context;
pub mod prompt_builder;
pub mod render;
pub mod response_parser;
pub mod run;
pub mod strategies;
pub mod trace;
pub mod usage;

mod constants;

pub use constants::*;
pub use run::{run_llm_repair, LlmRepairReport, RunLlmRepairParams};
