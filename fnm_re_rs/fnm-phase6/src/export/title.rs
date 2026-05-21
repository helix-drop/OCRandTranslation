//! ←→ FNM_RE/stages/export.py `_format_chapter_title()`
//!
//! **审计 #2 修复（2026-05-21）**：
//! 原先对 `leçon du` 开头的标题强制全大写以对齐 Python golden（Foucault Collège de
//! France 课程系列的印刷体例）。该规则违反 CLAUDE.md §7「不写逐书修补」——
//! 印刷体例属单一书系特征，不应硬编码到通用 export 路径。
//!
//! 决策：完全移除该规则，无条件透传原标题。
//!
//! **影响**：
//! - Biopolitics e2e byte-equal Python golden 在章节标题大小写一项失效；
//!   `scripts/smoke_post_m2.py` 现仅验证章数 / contract_ok，不验证 byte-equal
//!   章标题大小写。
//! - 调用方若需要"原书印刷体例"样式，应通过 TOC 项的元数据（如 `title_style`）
//!   或 caller 端 post-processing 实现，而非 export 阶段硬编码。

/// 透传章节标题（不做大小写转换或体例对齐）。
///
/// caller 已通过 `normalize_title()` 处理过的标题直接进入此函数；本函数仅
/// 调用 `to_string` 复制——保留以维持调用方接口稳定，未来如需统一格式化
/// (trim / NFKD / etc.) 可在此扩展。
pub fn format_chapter_title(title: &str, _chapter_id: &str) -> String {
    title.to_string()
}
