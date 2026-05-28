//! SPEC 测试翻译——对应 Python `tests/unit/test_llm_repair_*.py`。
//!
//! 3 个 Python SPEC 文件 → Rust 集成测试：
//! - test_llm_repair_fuzzy_tier1.py → fuzzy_tier1::*
//! - test_llm_repair_chapter_fallback.py → chapter_fallback::*
//! - test_llm_repair_footnote_coverage.py → footnote_coverage::*

use fnm_core::note_marker::normalize_note_marker;
use fnm_llm_repair::cluster::build_unresolved_clusters;
use fnm_llm_repair::override_materializer::{
    enrich_synthesize_anchor_actions, resolve_chapter_id_for_page,
};
use fnm_llm_repair::page_context::build_chapter_body_text;
use fnm_llm_repair::prompt_builder::{
    should_attach_repair_images, should_request_llm_for_cluster, slice_cluster_for_request,
    SliceCaps,
};
use fnm_llm_repair::response_parser::{
    parse_llm_repair_actions, select_auto_applicable_actions, RepairAction, SelectParams,
};
use fnm_llm_repair::strategies::fuzzy::locate_anchor_phrase_in_body;
use fnm_llm_repair::{
    FUZZY_SCORE_THRESHOLD, LLM_REPAIR_IMAGE_SCALE, MIN_CHAPTER_UNMATCHED_FOR_AUTO,
};
use fnm_phase1::input::RawPage;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

// ───────────────────────── fuzzy_tier1 ─────────────────────────

mod parse_synthesize_anchor {
    use super::*;

    #[test]
    fn test_synthesize_anchor_action_accepted() {
        let raw = r#"[{"action":"synthesize_anchor","note_item_id":"n-1","anchor_phrase":"the last words of the body","confidence":0.92,"reason":"clear context"}]"#;
        let actions = parse_llm_repair_actions(raw);
        assert_eq!(actions.len(), 1);
        let a = &actions[0];
        assert_eq!(a.action, "synthesize_anchor");
        assert_eq!(a.note_item_id, "n-1");
        assert_eq!(a.anchor_phrase, "the last words of the body");
        assert!((a.confidence - 0.92).abs() < 1e-9);
    }

    #[test]
    fn test_synthesize_anchor_without_phrase_is_dropped() {
        let raw = r#"[{"action":"synthesize_anchor","note_item_id":"n-1","confidence":0.9}]"#;
        let actions = parse_llm_repair_actions(raw);
        assert!(actions.is_empty());
    }

    #[test]
    fn test_match_action_still_has_no_phrase_field() {
        let raw = r#"[{"action":"match","note_item_id":"n-1","anchor_id":"a-1","confidence":0.95,"reason":""}]"#;
        let actions = parse_llm_repair_actions(raw);
        assert_eq!(actions.len(), 1);
        assert_eq!(actions[0].action, "match");
        assert!(actions[0].anchor_phrase.is_empty());
    }

    #[test]
    fn test_synthesize_note_item_dropped_by_parser() {
        let raw = r#"[{"action":"synthesize_note_item","anchor_id":"a-1","marker":"1","note_text":"Visible note text.","confidence":0.96,"reason":"clear"}]"#;
        let actions = parse_llm_repair_actions(raw);
        assert!(actions.is_empty());
    }
}

mod locate_anchor_phrase_in_body_test {
    use super::*;

    #[test]
    fn test_exact_match_returns_position() {
        let body = "Chapter text with a unique landmark phrase here. Another paragraph follows.";
        let result = locate_anchor_phrase_in_body(body, "unique landmark phrase");
        assert!(result.hit);
        assert!(result.score >= 95.0);
        let body_chars: Vec<char> = body.chars().collect();
        let matched: String = body_chars[result.char_start as usize..result.char_end as usize]
            .iter()
            .collect();
        assert_eq!(matched, "unique landmark phrase");
        assert!(!result.ambiguous);
    }

    #[test]
    fn test_ocr_noisy_match_still_hits() {
        let body = "Chapter text with a uniqe landmark phrese here. End.";
        let result = locate_anchor_phrase_in_body(body, "unique landmark phrase");
        assert!(result.hit);
        assert!(result.score >= FUZZY_SCORE_THRESHOLD);
    }

    #[test]
    fn test_below_threshold_no_hit() {
        let body = "Completely different chapter content. Nothing remotely related here.";
        let result = locate_anchor_phrase_in_body(body, "unique landmark phrase");
        assert!(!result.hit);
    }

    #[test]
    fn test_repeated_phrase_is_flagged_ambiguous() {
        let body = "First paragraph with landmark phrase one. Second paragraph with landmark phrase two. Third paragraph with landmark phrase three.";
        let result = locate_anchor_phrase_in_body(body, "landmark phrase");
        assert!(result.hit);
        assert!(result.ambiguous);
    }

    #[test]
    fn test_empty_inputs_are_safe() {
        assert!(!locate_anchor_phrase_in_body("", "foo").hit);
        assert!(!locate_anchor_phrase_in_body("some body", "").hit);
    }
}

mod select_auto_applicable_synthesize {
    use super::*;

    fn make_action(overrides: &[(&str, Value)]) -> RepairAction {
        let mut action = RepairAction {
            action: "synthesize_anchor".to_string(),
            note_item_id: "n-1".to_string(),
            anchor_id: String::new(),
            anchor_phrase: "some unique landmark phrase".to_string(),
            confidence: 0.95,
            fuzzy_score: 92.0,
            ambiguous: false,
            confidence_numeric: true,
            ..Default::default()
        };
        for (key, value) in overrides {
            match *key {
                "confidence" => action.confidence = value.as_f64().unwrap(),
                "fuzzy_score" => action.fuzzy_score = value.as_f64().unwrap(),
                "ambiguous" => action.ambiguous = value.as_bool().unwrap(),
                _ => panic!("unknown override key: {key}"),
            }
        }
        action
    }

    #[test]
    fn test_auto_applies_when_all_thresholds_met() {
        let actions = vec![make_action(&[])];
        let selected = select_auto_applicable_actions(
            &actions,
            SelectParams {
                confidence_threshold: 0.9,
                chapter_unmatched_count: MIN_CHAPTER_UNMATCHED_FOR_AUTO,
                ..Default::default()
            },
        );
        assert_eq!(selected.len(), 1);
        assert_eq!(selected[0].action, "synthesize_anchor");
    }

    #[test]
    fn test_low_confidence_rejected() {
        let actions = vec![make_action(&[("confidence", json!(0.85))])];
        let selected = select_auto_applicable_actions(
            &actions,
            SelectParams {
                confidence_threshold: 0.9,
                chapter_unmatched_count: 5,
                ..Default::default()
            },
        );
        assert!(selected.is_empty());
    }

    #[test]
    fn test_low_fuzzy_score_rejected() {
        let actions = vec![make_action(&[("fuzzy_score", json!(70.0))])];
        let selected = select_auto_applicable_actions(
            &actions,
            SelectParams {
                confidence_threshold: 0.9,
                chapter_unmatched_count: 5,
                ..Default::default()
            },
        );
        assert!(selected.is_empty());
    }

    #[test]
    fn test_singleton_cluster_now_allowed() {
        let actions = vec![make_action(&[])];
        let selected = select_auto_applicable_actions(
            &actions,
            SelectParams {
                confidence_threshold: 0.9,
                chapter_unmatched_count: 1,
                ..Default::default()
            },
        );
        assert_eq!(selected.len(), 1);
    }

    #[test]
    fn test_empty_cluster_rejected() {
        let actions = vec![make_action(&[])];
        let selected = select_auto_applicable_actions(
            &actions,
            SelectParams {
                confidence_threshold: 0.9,
                chapter_unmatched_count: 0,
                ..Default::default()
            },
        );
        assert!(selected.is_empty());
    }

    #[test]
    fn test_ambiguous_flag_rejected() {
        let actions = vec![make_action(&[("ambiguous", json!(true))])];
        let selected = select_auto_applicable_actions(
            &actions,
            SelectParams {
                confidence_threshold: 0.9,
                chapter_unmatched_count: 5,
                ..Default::default()
            },
        );
        assert!(selected.is_empty());
    }

    #[test]
    fn test_match_action_unaffected_by_new_gates() {
        let match_action = RepairAction {
            action: "match".to_string(),
            note_item_id: "n-1".to_string(),
            anchor_id: "a-1".to_string(),
            confidence: 0.95,
            confidence_numeric: true,
            ..Default::default()
        };
        let selected = select_auto_applicable_actions(
            &[match_action],
            SelectParams {
                confidence_threshold: 0.9,
                chapter_unmatched_count: 1,
                allowed_note_ids: {
                    let mut s = HashSet::new();
                    s.insert("n-1".to_string());
                    Some(s)
                },
                allowed_anchor_ids: {
                    let mut s = HashSet::new();
                    s.insert("a-1".to_string());
                    Some(s)
                },
                ..Default::default()
            },
        );
        assert_eq!(selected.len(), 1);
        assert_eq!(selected[0].action, "match");
    }
}

// ───────────────────────── chapter_fallback ─────────────────────────

mod resolve_chapter_id_for_page_test {
    use super::*;

    fn chapters() -> Vec<Value> {
        vec![
            json!({"chapter_id": "ch-intro", "start_page": 18, "end_page": 37}),
            json!({"chapter_id": "ch-1", "start_page": 38, "end_page": 76}),
            json!({"chapter_id": "ch-epilogue", "start_page": 333, "end_page": 347}),
        ]
    }

    #[test]
    fn test_page_inside_chapter_returns_that_id() {
        assert_eq!(resolve_chapter_id_for_page(&chapters(), 50), "ch-1");
    }

    #[test]
    fn test_page_before_first_chapter_returns_nearest() {
        assert_eq!(resolve_chapter_id_for_page(&chapters(), 10), "ch-intro");
    }

    #[test]
    fn test_page_after_last_chapter_returns_nearest() {
        assert_eq!(resolve_chapter_id_for_page(&chapters(), 400), "ch-epilogue");
    }

    #[test]
    fn test_page_in_gap_returns_closer_side() {
        let chs = vec![
            json!({"chapter_id": "a", "start_page": 10, "end_page": 20}),
            json!({"chapter_id": "b", "start_page": 40, "end_page": 50}),
        ];
        assert_eq!(resolve_chapter_id_for_page(&chs, 25), "a");
        assert_eq!(resolve_chapter_id_for_page(&chs, 35), "b");
    }

    #[test]
    fn test_empty_chapters_returns_empty() {
        assert_eq!(resolve_chapter_id_for_page(&[], 10), "");
    }

    #[test]
    fn test_invalid_page_returns_empty() {
        assert_eq!(resolve_chapter_id_for_page(&chapters(), 0), "");
        assert_eq!(resolve_chapter_id_for_page(&chapters(), -3), "");
    }

    #[test]
    fn test_chapter_with_missing_range_is_skipped() {
        let chs = vec![
            json!({"chapter_id": "bad", "start_page": 0, "end_page": 0}),
            json!({"chapter_id": "ok", "start_page": 100, "end_page": 120}),
        ];
        assert_eq!(resolve_chapter_id_for_page(&chs, 50), "ok");
    }
}

mod build_chapter_body_text_test {
    use super::*;

    fn make_raw_page(book_page: i64, markdown: &str) -> RawPage {
        RawPage {
            book_page,
            markdown: markdown.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn test_note_pages_are_not_used_as_chapter_body() {
        let chapter = json!({"chapter_id": "ch-1", "start_page": 10, "end_page": 11});
        let pages = vec![
            make_raw_page(10, "body page marker 40"),
            make_raw_page(11, "note definition should stay out"),
        ];
        let mut roles = HashMap::new();
        roles.insert(10_i64, "body".to_string());
        roles.insert(11_i64, "note".to_string());
        let (text, spans) = build_chapter_body_text(&chapter, &pages, Some(&roles), None);
        assert!(text.contains("body page marker 40"));
        assert!(!text.contains("note definition should stay out"));
        assert_eq!(spans, vec![(10, 0, "body page marker 40".len())]);
    }
}

mod enrich_synthesize_anchor_actions_test {
    use super::*;

    #[test]
    fn test_global_chapter_offset_is_converted_to_page_local_offset() {
        let first_page = "first page without target";
        let second_page = "second page has anchor phrase here";
        let body_text = format!("{first_page}\n\n{second_page}");
        let spans = vec![
            (10_i64, 0_usize, first_page.len()),
            (11_i64, first_page.len() + 2, body_text.len()),
        ];

        let action = RepairAction {
            action: "synthesize_anchor".to_string(),
            note_item_id: "en-1".to_string(),
            anchor_phrase: "anchor phrase".to_string(),
            confidence: 0.95,
            ..Default::default()
        };
        let cluster = json!({"chapter_body_text": body_text});
        let enriched = enrich_synthesize_anchor_actions(vec![action], &cluster, &spans);

        let expected_start = second_page.find("anchor phrase").unwrap() as i64;
        let expected_end = expected_start + "anchor phrase".len() as i64;
        assert_eq!(enriched[0].page_no, 11);
        assert_eq!(enriched[0].char_start, expected_start);
        assert_eq!(enriched[0].char_end, expected_end);
        assert_eq!(enriched[0].matched_text, "anchor phrase");
    }
}

mod synthesize_anchor_auto_apply_gate_test {
    use super::*;

    #[test]
    fn test_footnote_synthesize_anchor_must_stay_in_note_page_window() {
        let action = RepairAction {
            action: "synthesize_anchor".to_string(),
            note_item_id: "fn-00008".to_string(),
            anchor_phrase: "l'homme d'État anglais Walpole".to_string(),
            page_no: 17,
            confidence: 0.95,
            fuzzy_score: 100.0,
            ambiguous: false,
            ..Default::default()
        };
        let mut note_pages = HashMap::new();
        note_pages.insert("fn-00008".to_string(), 37_i64);
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                confidence_threshold: 0.9,
                chapter_unmatched_count: 1,
                note_system: "footnote",
                note_page_by_id: Some(&note_pages),
                allowed_synthesize_pages: None,
                allowed_note_ids: None,
                allowed_anchor_ids: None,
            },
        );
        assert!(selected.is_empty());
    }

    #[test]
    fn test_endnote_synthesize_anchor_must_stay_in_candidate_body_pages() {
        let action = RepairAction {
            action: "synthesize_anchor".to_string(),
            note_item_id: "en-00216".to_string(),
            anchor_phrase: "Autant les ordolibéraux cherchent".to_string(),
            page_no: 174,
            confidence: 0.95,
            fuzzy_score: 100.0,
            ambiguous: false,
            ..Default::default()
        };
        let allowed: HashSet<i64> = [158_i64, 159].into_iter().collect();
        let selected = select_auto_applicable_actions(
            &[action],
            SelectParams {
                confidence_threshold: 0.9,
                chapter_unmatched_count: 1,
                note_system: "endnote",
                note_page_by_id: None,
                allowed_synthesize_pages: Some(&allowed),
                allowed_note_ids: None,
                allowed_anchor_ids: None,
            },
        );
        assert!(selected.is_empty());
    }
}

// ───────────────────────── footnote_coverage ─────────────────────────

mod build_cluster_includes_footnote {
    use super::*;

    fn minimal_inputs(note_kind: &str) -> (Vec<Value>, Vec<Value>, Vec<Value>, Vec<Value>) {
        let chapters = vec![json!({"chapter_id": "ch-1", "title": "Chapter 1"})];
        let notes = vec![json!({
            "note_item_id": "n-1",
            "chapter_id": "ch-1",
            "region_id": "r-1",
            "marker": "1",
            "normalized_marker": "1",
            "page_no": 5,
            "source_text": "definition of note 1",
        })];
        let anchors: Vec<Value> = vec![];
        let links = vec![json!({
            "link_id": "L-1",
            "chapter_id": "ch-1",
            "region_id": "r-1",
            "note_kind": note_kind,
            "status": "orphan_note",
            "note_item_id": "n-1",
            "anchor_id": "",
            "marker": "1",
        })];
        (chapters, notes, anchors, links)
    }

    #[test]
    fn test_endnote_cluster_still_built() {
        let (c, n, b, l) = minimal_inputs("endnote");
        let clusters = build_unresolved_clusters(&c, &n, &b, &l);
        assert_eq!(clusters.len(), 1);
        assert_eq!(clusters[0]["note_system"], "endnote");
    }

    #[test]
    fn test_footnote_cluster_now_built() {
        let (c, n, b, l) = minimal_inputs("footnote");
        let clusters = build_unresolved_clusters(&c, &n, &b, &l);
        assert_eq!(clusters.len(), 1);
        assert_eq!(clusters[0]["note_system"], "footnote");
        assert_eq!(
            clusters[0]["unmatched_note_items"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
    }

    #[test]
    fn test_unknown_note_system_still_filtered() {
        let (c, n, b, l) = minimal_inputs("sidenote");
        let clusters = build_unresolved_clusters(&c, &n, &b, &l);
        assert!(clusters.is_empty());
    }
}

mod footnote_note_only_with_body {
    use super::*;

    #[test]
    fn test_footnote_cluster_routes_to_synthesize() {
        let cluster = json!({
            "cluster_id": "ch-1:r-1:footnote",
            "chapter_id": "ch-1",
            "chapter_title": "Chapter 1",
            "region_id": "r-1",
            "note_system": "footnote",
            "matched_examples": [],
            "unmatched_note_items": [
                {"note_item_id": "n-1", "marker": "1"},
                {"note_item_id": "n-2", "marker": "2"},
                {"note_item_id": "n-3", "marker": "3"},
            ],
            "unmatched_anchors": [],
            "chapter_body_text": "body with some unique landmark phrase here.",
        });
        let sliced = slice_cluster_for_request(&cluster, SliceCaps::default());
        assert_eq!(sliced["request_mode"], "note_only_with_body");
        let actions: Vec<&str> = sliced["allowed_actions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        assert!(actions.contains(&"synthesize_anchor"));
    }

    #[test]
    fn test_orphan_anchor_with_rebind_candidates_routes_to_match() {
        let chapters = vec![json!({"chapter_id": "ch-1", "title": "Chapter 1"})];
        let note_items = vec![json!({
            "note_item_id": "n-65",
            "chapter_id": "ch-1",
            "region_id": "r-1",
            "marker": "65",
            "normalized_marker": "65",
            "page_no": 10,
            "source_text": "definition of note 65",
        })];
        let anchors = vec![
            json!({
                "anchor_id": "a-orphan",
                "chapter_id": "ch-1",
                "page_no": 10,
                "normalized_marker": "4",
                "source_marker": "4",
                "source_text": "broken superscript in body",
                "synthetic": false,
            }),
            json!({
                "anchor_id": "synthetic-footnote-1",
                "chapter_id": "ch-1",
                "page_no": 10,
                "normalized_marker": "65",
                "source_marker": "65",
                "source_text": "synthetic fallback anchor",
            }),
        ];
        let links = vec![
            json!({
                "link_id": "L-orphan",
                "chapter_id": "ch-1",
                "region_id": "",
                "note_kind": "footnote",
                "status": "orphan_anchor",
                "note_item_id": "",
                "anchor_id": "a-orphan",
                "marker": "4",
            }),
            json!({
                "link_id": "L-match",
                "chapter_id": "ch-1",
                "region_id": "r-1",
                "note_kind": "footnote",
                "status": "matched",
                "note_item_id": "n-65",
                "anchor_id": "synthetic-footnote-1",
                "marker": "65",
            }),
        ];
        let clusters = build_unresolved_clusters(&chapters, &note_items, &anchors, &links);
        assert_eq!(clusters.len(), 1);
        let rebinds = clusters[0]["rebind_candidates"].as_array().unwrap();
        assert_eq!(rebinds.len(), 1);
        assert!(rebinds[0]["current_anchor_synthetic"].as_bool().unwrap());

        let sliced = slice_cluster_for_request(&clusters[0], SliceCaps::default());
        assert_eq!(sliced["request_mode"], "paired");
        let actions: Vec<&str> = sliced["allowed_actions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        assert!(actions.contains(&"match"));
    }

    #[test]
    fn test_matched_synthetic_anchor_is_reopened_as_note_only_cluster() {
        let chapters = vec![json!({"chapter_id": "ch-1", "title": "Chapter 1"})];
        let note_items = vec![json!({
            "note_item_id": "n-1",
            "chapter_id": "ch-1",
            "region_id": "r-1",
            "marker": "1",
            "normalized_marker": "1",
            "page_no": 10,
            "source_text": "definition of note 1",
        })];
        let anchors = vec![json!({
            "anchor_id": "synthetic-footnote-1",
            "chapter_id": "ch-1",
            "page_no": 10,
            "normalized_marker": "1",
            "source_marker": "1",
            "source_text": "synthetic fallback anchor",
            "synthetic": true,
        })];
        let links = vec![json!({
            "link_id": "L-match",
            "chapter_id": "ch-1",
            "region_id": "r-1",
            "note_kind": "footnote",
            "status": "matched",
            "note_item_id": "n-1",
            "anchor_id": "synthetic-footnote-1",
            "marker": "1",
        })];
        let clusters = build_unresolved_clusters(&chapters, &note_items, &anchors, &links);
        assert_eq!(clusters.len(), 1);
        assert_eq!(
            clusters[0]["unmatched_note_items"][0]["note_item_id"],
            "n-1"
        );
        assert_eq!(
            clusters[0]["rebind_candidates"][0]["current_anchor_id"],
            "synthetic-footnote-1"
        );
    }

    #[test]
    fn test_ref_only_visual_allowed_actions() {
        let cluster = json!({
            "cluster_id": "ch-1:r-1:endnote",
            "chapter_id": "ch-1",
            "chapter_title": "Chapter 1",
            "region_id": "r-1",
            "note_system": "endnote",
            "matched_examples": [],
            "unmatched_note_items": [],
            "unmatched_anchors": [
                {"anchor_id": "a-1", "marker": "1", "page_no": 10},
            ],
            "page_contexts": [{"page_no": 10, "ocr_excerpt": "page excerpt"}],
        });
        let sliced = slice_cluster_for_request(&cluster, SliceCaps::default());
        assert_eq!(sliced["request_mode"], "ref_only_visual");
        let actions: Vec<&str> = sliced["allowed_actions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        assert_eq!(actions, vec!["ignore_ref", "needs_review"]);
    }

    #[test]
    fn test_needs_review_only_cluster_is_not_sent_to_llm() {
        let cluster = json!({
            "cluster_id": "ch-1:r-1:endnote",
            "chapter_id": "ch-1",
            "chapter_title": "Chapter 1",
            "region_id": "r-1",
            "note_system": "endnote",
            "matched_examples": [],
            "unmatched_note_items": [
                {"note_item_id": "n-1", "marker": "1", "page_no": 20},
            ],
            "unmatched_anchors": [],
            "page_contexts": [{"page_no": 20, "ocr_excerpt": "already known note text"}],
        });
        let sliced = slice_cluster_for_request(&cluster, SliceCaps::default());
        let actions: Vec<&str> = sliced["allowed_actions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        assert_eq!(actions, vec!["needs_review"]);
        assert!(!should_request_llm_for_cluster(&sliced));
    }

    #[test]
    fn test_synthesize_anchor_clusters_attach_images() {
        let rebind_cluster = json!({
            "cluster_id": "ch-1:r-1:footnote",
            "chapter_id": "ch-1",
            "note_system": "footnote",
            "unmatched_note_items": [],
            "unmatched_anchors": [{"anchor_id": "a-1", "page_no": 10}],
            "rebind_candidates": [{"note_item_id": "n-1", "current_anchor_id": "synthetic-1"}],
            "page_contexts": [{"page_no": 10, "ocr_excerpt": "page excerpt"}],
        });
        let note_only_cluster = json!({
            "cluster_id": "ch-1:r-1:footnote",
            "chapter_id": "ch-1",
            "note_system": "footnote",
            "unmatched_note_items": [{"note_item_id": "n-1", "marker": "1", "page_no": 10}],
            "unmatched_anchors": [],
            "chapter_body_text": "Some chapter body text with enough words for the body text detection. More words here to pass the threshold.",
            "page_contexts": [{"page_no": 10, "ocr_excerpt": "page excerpt"}],
        });
        assert!(!should_attach_repair_images(&slice_cluster_for_request(
            &rebind_cluster,
            SliceCaps::default()
        )));
        assert!(should_attach_repair_images(&slice_cluster_for_request(
            &note_only_cluster,
            SliceCaps::default()
        )));
    }

    #[test]
    fn test_repair_image_scale_keeps_small_note_markers_legible() {
        let scale = LLM_REPAIR_IMAGE_SCALE;
        assert!(scale >= 1.2);
    }

    #[test]
    fn test_normalize_marker_consistency() {
        // 回归：normalize_note_marker 去除空白/方括号
        assert_eq!(normalize_note_marker(" 1 "), "1");
        assert_eq!(normalize_note_marker("[1]"), "1");
    }
}
