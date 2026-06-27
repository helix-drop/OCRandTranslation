//! ←→ FNM_RE/modules/_pdf_render_worker.py (88 行)
//!
//! 转发到 fnm_core::vision（C1 抽取后统一入口）。
//! 保留此文件作为兼容 re-export，避免已有测试和模块的 import 路径断裂。

pub use fnm_core::vision::{render_page_to_base64_png, PDFIUM};
