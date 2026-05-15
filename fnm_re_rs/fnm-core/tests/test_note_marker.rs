//! Parity 测试：normalize_note_marker 与 Python 输出一致。
use fnm_core::note_marker::normalize_note_marker;
use serde_json::Value;

#[test]
fn matches_python_output() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/normalize_note_marker_cases.json"))
            .expect("load fixture");
    let mut failures: Vec<String> = Vec::new();
    for case in &cases {
        let input = case["input"].as_str().unwrap();
        let expected = case["expected"].as_str().unwrap();
        let actual = normalize_note_marker(input);
        if actual != expected {
            failures.push(format!(
                "input={input:?} expected={expected:?} got={actual:?}"
            ));
        }
    }
    if !failures.is_empty() {
        panic!("parity failures:\n{}", failures.join("\n"));
    }
}
