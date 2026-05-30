//! Typed accessor wrappers for `serde_json::Value` objects flowing through the LLM repair pipeline.
//!
//! These wrappers preserve the original `.get().unwrap_or(default)` semantics —
//! they never panic and never change behavior compared to raw `.get()` chains.
//! They exist purely to reduce boilerplate and improve readability.

use serde_json::Value;

// ── ClusterView ────────────────────────────────────────────────

/// Typed accessor wrapper for a cluster / request_cluster Value.
pub struct ClusterView<'a>(pub &'a Value);

impl<'a> ClusterView<'a> {
    /// Wrap a `&Value` as a `ClusterView`.
    pub fn new(v: &'a Value) -> Self {
        Self(v)
    }

    // ── scalar getters ────────────────────────────────────────

    pub fn cluster_id(&self) -> &str {
        self.0.get("cluster_id").and_then(|v| v.as_str()).unwrap_or("")
    }

    pub fn chapter_title(&self) -> &str {
        self.0.get("chapter_title").and_then(|v| v.as_str()).unwrap_or("")
    }

    pub fn page_start(&self) -> i64 {
        self.0.get("page_start").and_then(|v| v.as_i64()).unwrap_or(0)
    }

    pub fn page_end(&self) -> i64 {
        self.0.get("page_end").and_then(|v| v.as_i64()).unwrap_or(0)
    }

    pub fn note_system(&self) -> &str {
        self.0.get("note_system").and_then(|v| v.as_str()).unwrap_or("")
    }

    pub fn request_mode(&self) -> &str {
        self.0.get("request_mode").and_then(|v| v.as_str()).unwrap_or("")
    }

    pub fn chapter_body_text(&self) -> &str {
        self.0
            .get("chapter_body_text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
    }

    // ── value clone getters (for JSON payload construction) ────

    pub fn cluster_id_val(&self) -> Value {
        self.0.get("cluster_id").cloned().unwrap_or(Value::Null)
    }

    pub fn chapter_title_val(&self) -> Value {
        self.0.get("chapter_title").cloned().unwrap_or(Value::Null)
    }

    pub fn page_start_val(&self) -> Value {
        self.0.get("page_start").cloned().unwrap_or(Value::Null)
    }

    pub fn page_end_val(&self) -> Value {
        self.0.get("page_end").cloned().unwrap_or(Value::Null)
    }

    pub fn note_system_val(&self) -> Value {
        self.0.get("note_system").cloned().unwrap_or(Value::Null)
    }

    pub fn request_mode_val(&self) -> Value {
        self.0.get("request_mode").cloned().unwrap_or(Value::Null)
    }

    // ── array getters ─────────────────────────────────────────

    pub fn allowed_actions(&self) -> impl Iterator<Item = &str> {
        self.0
            .get("allowed_actions")
            .and_then(|v| v.as_array())
            .into_iter()
            .flat_map(|arr| arr.iter().filter_map(|v| v.as_str()))
    }

    pub fn page_contexts(&self) -> std::slice::Iter<'_, Value> {
        self.0
            .get("page_contexts")
            .and_then(|v| v.as_array())
            .map(|a| a.as_slice())
            .unwrap_or(&[])
            .iter()
    }

    pub fn matched_examples(&self) -> std::slice::Iter<'_, Value> {
        self.0
            .get("matched_examples")
            .and_then(|v| v.as_array())
            .map(|a| a.as_slice())
            .unwrap_or(&[])
            .iter()
    }

    pub fn unmatched_note_items(&self) -> std::slice::Iter<'_, Value> {
        self.0
            .get("unmatched_note_items")
            .and_then(|v| v.as_array())
            .map(|a| a.as_slice())
            .unwrap_or(&[])
            .iter()
    }

    pub fn unmatched_anchors(&self) -> std::slice::Iter<'_, Value> {
        self.0
            .get("unmatched_anchors")
            .and_then(|v| v.as_array())
            .map(|a| a.as_slice())
            .unwrap_or(&[])
            .iter()
    }

    pub fn rebind_candidates(&self) -> std::slice::Iter<'_, Value> {
        self.0
            .get("rebind_candidates")
            .and_then(|v| v.as_array())
            .map(|a| a.as_slice())
            .unwrap_or(&[])
            .iter()
    }

    // ── convenience ───────────────────────────────────────────

    /// Returns true if `allowed_actions` contains the given action string.
    pub fn has_action(&self, action: &str) -> bool {
        self.allowed_actions().any(|a| a == action)
    }

    /// Returns the underlying `&Value`.
    pub fn inner(&self) -> &'a Value {
        self.0
    }
}

// ── Item views ─────────────────────────────────────────────────

/// Typed accessor wrapper for a page_context item Value.
pub struct PageContextView<'a>(pub &'a Value);

impl<'a> PageContextView<'a> {
    pub fn page_no(&self) -> i64 {
        self.0.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0)
    }

    pub fn ocr_excerpt(&self) -> &str {
        self.0.get("ocr_excerpt").and_then(|v| v.as_str()).unwrap_or("")
    }

    pub fn page_no_val(&self) -> Value {
        self.0.get("page_no").cloned().unwrap_or(Value::Null)
    }
}

/// Typed accessor wrapper for a matched_example item Value.
pub struct MatchedExampleView<'a>(pub &'a Value);

impl<'a> MatchedExampleView<'a> {
    pub fn note_item_id(&self) -> Value {
        self.0.get("note_item_id").cloned().unwrap_or(Value::Null)
    }

    pub fn anchor_id(&self) -> Value {
        self.0.get("anchor_id").cloned().unwrap_or(Value::Null)
    }

    pub fn marker(&self) -> Value {
        self.0.get("marker").cloned().unwrap_or(Value::Null)
    }

    pub fn note_excerpt(&self) -> &str {
        self.0.get("note_excerpt").and_then(|v| v.as_str()).unwrap_or("")
    }

    pub fn anchor_excerpt(&self) -> &str {
        self.0.get("anchor_excerpt").and_then(|v| v.as_str()).unwrap_or("")
    }
}

/// Typed accessor wrapper for an unmatched_note_item Value.
pub struct UnmatchedNoteView<'a>(pub &'a Value);

impl<'a> UnmatchedNoteView<'a> {
    pub fn note_item_id(&self) -> Value {
        self.0.get("note_item_id").cloned().unwrap_or(Value::Null)
    }

    pub fn marker(&self) -> Value {
        self.0.get("marker").cloned().unwrap_or(Value::Null)
    }

    pub fn page_no(&self) -> i64 {
        self.0.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0)
    }

    pub fn page_no_val(&self) -> Value {
        self.0.get("page_no").cloned().unwrap_or(Value::Null)
    }

    pub fn source_text(&self) -> &str {
        self.0.get("source_text").and_then(|v| v.as_str()).unwrap_or("")
    }
}

/// Typed accessor wrapper for an unmatched_anchor item Value.
pub struct UnmatchedAnchorView<'a>(pub &'a Value);

impl<'a> UnmatchedAnchorView<'a> {
    pub fn anchor_id(&self) -> Value {
        self.0.get("anchor_id").cloned().unwrap_or(Value::Null)
    }

    pub fn page_no(&self) -> i64 {
        self.0.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0)
    }

    pub fn page_no_val(&self) -> Value {
        self.0.get("page_no").cloned().unwrap_or(Value::Null)
    }

    pub fn paragraph_index(&self) -> Value {
        self.0.get("paragraph_index").cloned().unwrap_or(Value::Null)
    }

    pub fn source_text(&self) -> &str {
        self.0.get("source_text").and_then(|v| v.as_str()).unwrap_or("")
    }

    /// Returns `normalized_marker` if present and non-null, otherwise `source_marker`.
    pub fn marker(&self) -> Value {
        self.0
            .get("normalized_marker")
            .filter(|v| !matches!(v, Value::Null))
            .cloned()
            .or_else(|| self.0.get("source_marker").cloned())
            .unwrap_or(Value::Null)
    }
}

/// Typed accessor wrapper for a rebind_candidate item Value.
pub struct RebindCandidateView<'a>(pub &'a Value);

impl<'a> RebindCandidateView<'a> {
    pub fn link_id(&self) -> Value {
        self.0.get("link_id").cloned().unwrap_or(Value::Null)
    }

    pub fn note_item_id(&self) -> Value {
        self.0.get("note_item_id").cloned().unwrap_or(Value::Null)
    }

    pub fn current_anchor_id(&self) -> Value {
        self.0.get("current_anchor_id").cloned().unwrap_or(Value::Null)
    }

    pub fn marker(&self) -> Value {
        self.0.get("marker").cloned().unwrap_or(Value::Null)
    }

    pub fn note_page_no(&self) -> Value {
        self.0.get("note_page_no").cloned().unwrap_or(Value::Null)
    }

    pub fn anchor_page_no(&self) -> Value {
        self.0.get("anchor_page_no").cloned().unwrap_or(Value::Null)
    }

    pub fn current_anchor_marker(&self) -> Value {
        self.0.get("current_anchor_marker").cloned().unwrap_or(Value::Null)
    }

    pub fn current_anchor_synthetic(&self) -> Value {
        self.0.get("current_anchor_synthetic").cloned().unwrap_or(Value::Null)
    }

    pub fn note_excerpt(&self) -> &str {
        self.0.get("note_excerpt").and_then(|v| v.as_str()).unwrap_or("")
    }

    pub fn anchor_excerpt(&self) -> &str {
        self.0.get("anchor_excerpt").and_then(|v| v.as_str()).unwrap_or("")
    }
}
