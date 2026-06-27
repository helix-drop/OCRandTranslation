//! ←→ Python `ref_freeze.py:_compute_unit_hash` (L184)
//! Frozen unit 的 SHA-256 哈希（source_hash + segment_plan_hash）。

use sha2::{Digest, Sha256};

/// 计算 unit 的 source_hash 和 segment_plan_hash。
///
/// ←→ Python `_compute_unit_hash` (ref_freeze.py:184-193)
///
/// - source_hash: source_text 前 200 字符的 SHA-256 前 16 位 hex
/// - segment_plan_hash: "{page_start}|{page_end}|{char_count}|{sorted_page_nos}" 的 SHA-256 前 16 位 hex
pub fn compute_unit_hash(
    source_text: &str,
    page_start: i64,
    page_end: i64,
    char_count: i64,
    page_nos: &[i64],
) -> (String, String) {
    let source_fp = {
        let slice: String = source_text.chars().take(200).collect();
        let mut hasher = Sha256::new();
        hasher.update(slice.as_bytes());
        format!("{:x}", hasher.finalize())[..16].to_string()
    };

    let mut sorted_nos = page_nos.to_vec();
    sorted_nos.sort();
    let plan_key = format!(
        "{}|{}|{}|{}",
        page_start,
        page_end,
        char_count,
        sorted_nos
            .iter()
            .map(|n| n.to_string())
            .collect::<Vec<_>>()
            .join(",")
    );
    let plan_fp = {
        let mut hasher = Sha256::new();
        hasher.update(plan_key.as_bytes());
        format!("{:x}", hasher.finalize())[..16].to_string()
    };

    (source_fp, plan_fp)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_unit_hash_consistent() {
        let (h1, h2) = compute_unit_hash("hello world", 1, 5, 100, &[1, 3, 5]);
        assert_eq!(h1.len(), 16);
        assert_eq!(h2.len(), 16);
    }

    #[test]
    fn test_compute_unit_hash_deterministic() {
        let (a1, a2) = compute_unit_hash("same text", 1, 1, 10, &[1]);
        let (b1, b2) = compute_unit_hash("same text", 1, 1, 10, &[1]);
        assert_eq!(a1, b1);
        assert_eq!(a2, b2);
    }

    #[test]
    fn test_compute_unit_hash_different_input() {
        let (a1, _a2) = compute_unit_hash("text a", 1, 1, 10, &[1]);
        let (b1, _b2) = compute_unit_hash("text b", 1, 1, 10, &[1]);
        assert_ne!(a1, b1);
    }
}
