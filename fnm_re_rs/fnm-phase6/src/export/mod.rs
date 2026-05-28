//! Export helpers 子模块（保留仅供 Phase6 book_assemble 内部使用）。
//!
//! 章节渲染相关模块已移至 fnm-phase5/render/。
//! Phase6 export 仅保留文件打包与语义合同检查。

pub mod contract;
pub mod index_render;
pub mod markdown_clean;
pub mod paragraph_key;
pub mod zip;

#[cfg(test)]
mod tests;
