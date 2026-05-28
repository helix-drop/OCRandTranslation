//! ZIP 中读取 Markdown 文件。
//!
//! ←→ Python `_read_zip_markdown_files()` (export_audit.py:479)

use std::collections::HashMap;

use anyhow::Result;

/// 从 ZIP 字节中读取 Markdown 文件。
///
/// ←→ Python `_read_zip_markdown_files()` (export_audit.py:479)
pub fn read_zip_markdown_files(zip_bytes: &[u8]) -> Result<HashMap<String, String>> {
    let reader = std::io::Cursor::new(zip_bytes);
    let mut archive = zip::ZipArchive::new(reader)?;
    let mut payload = HashMap::new();

    for i in 0..archive.len() {
        let mut file = archive.by_index(i)?;
        let name = file.name().to_string();
        if name.ends_with(".md") {
            let mut content = String::new();
            std::io::Read::read_to_string(&mut file, &mut content)?;
            payload.insert(name, content);
        }
    }

    Ok(payload)
}
