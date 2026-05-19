//! ←→ FNM_RE/stages/export.py `build_export_zip()` (export.py:723)
//!
//! ZIP 归档创建：将 ExportBundleRecord 的 files 字典写入 ZIP 字节流。

use std::io::{Cursor, Write};

use anyhow::Result;
use zip::write::FileOptions;
use zip::ZipWriter;

use fnm_core::export_constants::OBSIDIAN_EXPORT_INDEX_MD;
use fnm_core::records::ExportBundleRecord;

use super::index_render::build_index_markdown;
use super::markdown_clean::normalize_markdown_content;

/// 将 ExportBundleRecord 的 files 写入 ZIP 归档，返回 bytes。
///
/// ←→ Python `build_export_zip()` (export.py:723)
pub fn build_export_zip(bundle: &ExportBundleRecord) -> Result<Vec<u8>> {
    let mut files: std::collections::HashMap<String, String> = bundle.files.clone();

    // 确保 index.md 存在
    let index_path = if bundle.index_path.trim().is_empty() {
        OBSIDIAN_EXPORT_INDEX_MD.to_string()
    } else {
        bundle.index_path.trim().to_string()
    };
    if !files.contains_key(&index_path) && !bundle.chapters.is_empty() {
        files.insert(index_path.clone(), build_index_markdown(&bundle.chapters));
    }

    let payload = Cursor::new(Vec::new());
    let mut archive = ZipWriter::new(payload);

    let options = FileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated)
        .unix_permissions(0o644);

    // 按路径排序写入
    let mut sorted_paths: Vec<&String> = files.keys().collect();
    sorted_paths.sort();

    for path in sorted_paths {
        let raw_path = path
            .replace('\\', "/")
            .trim()
            .trim_start_matches('/')
            .to_string();
        let segments: Vec<&str> = raw_path
            .split('/')
            .filter(|s| !s.is_empty() && *s != "." && *s != "..")
            .collect();
        if segments.is_empty() {
            continue;
        }
        let safe_path = segments.join("/");

        let content = files.get(path).map(|s| s.as_str()).unwrap_or("");
        let normalized = normalize_markdown_content(content);

        archive.start_file(&safe_path, options)?;
        archive.write_all(normalized.as_bytes())?;
    }

    let writer = archive.finish()?;
    let result = writer.into_inner();
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::records::ExportChapterRecord;

    fn make_bundle(
        chapters: Vec<ExportChapterRecord>,
        files: std::collections::HashMap<String, String>,
    ) -> ExportBundleRecord {
        ExportBundleRecord {
            index_path: "index.md".to_string(),
            chapters_dir: "chapters".to_string(),
            chapters,
            chapter_files: files.clone(),
            files,
            export_semantic_contract_ok: true,
            ..Default::default()
        }
    }

    #[test]
    fn zip_empty_bundle() {
        let bundle = make_bundle(vec![], std::collections::HashMap::new());
        let bytes = build_export_zip(&bundle).unwrap();
        assert!(!bytes.is_empty());
        // 空 ZIP 至少有 22 字节的 EOCD 记录
        assert!(bytes.len() >= 22);
    }

    #[test]
    fn zip_single_chapter() {
        let ch = ExportChapterRecord {
            order: 1,
            section_id: "ch-1".into(),
            title: "Chapter 1".into(),
            path: "chapters/ch001.md".into(),
            content: "# Chapter 1\n\nBody text.\n".into(),
            start_page: 1,
            end_page: 5,
            pages: vec![1, 2, 3, 4, 5],
        };
        let mut files = std::collections::HashMap::new();
        files.insert("chapters/ch001.md".to_string(), ch.content.clone());
        let bundle = make_bundle(vec![ch], files);
        let bytes = build_export_zip(&bundle).unwrap();
        assert!(bytes.len() > 22);

        // 验证可以读取
        let reader = Cursor::new(&bytes);
        let mut archive = zip::ZipArchive::new(reader).unwrap();
        assert_eq!(archive.len(), 2); // chapter + index.md
    }

    #[test]
    fn zip_safe_path_dotdot() {
        let mut files = std::collections::HashMap::new();
        files.insert("../escape.md".to_string(), "content".to_string());
        let bundle = make_bundle(vec![], files);
        let bytes = build_export_zip(&bundle).unwrap();
        let reader = Cursor::new(&bytes);
        let archive = zip::ZipArchive::new(reader).unwrap();
        // ../ 段被过滤，文件应为 escape.md
        assert_eq!(archive.len(), 1);
    }
}
