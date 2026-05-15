//! Parity 测试：types enum 的 from_str 行为与 Python is_valid_* 函数一致。
use fnm_core::types::*;
use serde_json::Value;
use std::collections::HashMap;
use std::str::FromStr;

#[test]
fn matches_python_is_valid_functions() {
    let cases: HashMap<String, Vec<Value>> =
        serde_json::from_str(include_str!("fixtures/types_validity_cases.json"))
            .expect("load fixture");

    type Validator = (&'static str, fn(&str) -> bool);
    let funcs: Vec<Validator> = vec![
        ("is_valid_page_role", |s| PageRole::from_str(s).is_ok()),
        ("is_valid_chapter_source", |s| {
            ChapterSource::from_str(s).is_ok()
        }),
        ("is_valid_boundary_state", |s| {
            BoundaryState::from_str(s).is_ok()
        }),
        ("is_valid_note_kind", |s| NoteKind::from_str(s).is_ok()),
        ("is_valid_region_scope", |s| {
            RegionScope::from_str(s).is_ok()
        }),
        ("is_valid_region_source", |s| {
            RegionSource::from_str(s).is_ok()
        }),
        ("is_valid_note_mode", |s| NoteMode::from_str(s).is_ok()),
        ("is_valid_anchor_kind", |s| AnchorKind::from_str(s).is_ok()),
        ("is_valid_link_status", |s| LinkStatus::from_str(s).is_ok()),
        ("is_valid_link_resolver", |s| {
            LinkResolver::from_str(s).is_ok()
        }),
        ("is_valid_pipeline_state", |s| {
            PipelineState::from_str(s).is_ok()
        }),
    ];

    let mut failures: Vec<String> = Vec::new();
    for (name, rust_fn) in &funcs {
        let entries = match cases.get(*name) {
            Some(v) => v,
            None => {
                failures.push(format!("missing fixture key: {name}"));
                continue;
            }
        };
        for entry in entries {
            let input = entry["input"].as_str().unwrap();
            let expected = entry["expected"].as_bool().unwrap();
            let actual = rust_fn(input);
            if actual != expected {
                failures.push(format!("{name}({input:?}) = {actual}, expected {expected}"));
            }
        }
    }

    if !failures.is_empty() {
        panic!("parity failures:\n{}", failures.join("\n"));
    }
}
