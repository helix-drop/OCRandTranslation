//! 容器章节检测（Part I / Book II 等不直接导出，其子章需正确归属）。

use fnm_core::records::ChapterRecord;

/// 判断 chapter 是否是容器（Part I / Book II 等）。
pub fn is_container_chapter(ch: &ChapterRecord) -> bool {
    let t = ch.title.to_lowercase();
    (t.starts_with("part ") || t.starts_with("book ") || t.starts_with("livre "))
        && !t.contains("chapter")
}

/// 将容器章的子章 start_page 调整到容器章之后。
pub fn expand_container_chapters(chapters: &mut [ChapterRecord]) {
    let mut skip_until: Option<i64> = None;
    for ch in chapters.iter_mut() {
        if let Some(skip) = skip_until {
            if ch.start_page <= skip {
                ch.start_page = skip + 1;
            }
        }
        if is_container_chapter(ch) {
            skip_until = Some(ch.end_page);
        }
    }
}
