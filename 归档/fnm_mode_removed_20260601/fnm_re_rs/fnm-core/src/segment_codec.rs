//! ←→ FNM_RE/shared/segment_codec.py
//! UnitPageSegmentRecord / UnitParagraphRecord 的压缩序列化/反序列化。
//!
//! DB 存储用短键名 + 省略可推导字段，反序列化时还原为完整 dict（消费方零修改）。

use serde_json::{Map, Value};

/// 压缩序列化 page_segments 列表。与 Python `serialize_segments` 一致。
pub fn serialize_segments(segments: &[Value]) -> Vec<Value> {
    segments.iter().map(serialize_segment).collect()
}

/// 反序列化 page_segments 列表为完整 dict 格式（兼容旧格式）。
/// 与 Python `deserialize_segments_to_dicts` 一致。
pub fn deserialize_segments_to_dicts(raw: &[Value]) -> Vec<Value> {
    raw.iter().map(deserialize_segment_to_dict).collect()
}

// ── Segment ──

fn serialize_segment(seg: &Value) -> Value {
    let paragraphs_raw = seg
        .get("paragraphs")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let paragraphs: Vec<Value> = paragraphs_raw.iter().map(serialize_paragraph).collect();
    let source_text = seg
        .get("source_text")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let display_text = seg
        .get("display_text")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let mut d = Map::new();
    d.insert(
        "p".into(),
        seg.get("page_no")
            .cloned()
            .unwrap_or(Value::Number(0.into())),
    );
    if !paragraphs.is_empty() {
        d.insert("ps".into(), Value::Array(paragraphs));
    } else {
        // 段落为空但顶层正文非空时保留 source_text / display_text
        let has_source = !source_text.is_empty();
        let has_display = !display_text.is_empty() && display_text != source_text;
        if has_source {
            d.insert("st".into(), Value::String(source_text.to_string()));
        }
        if has_display {
            d.insert("dt".into(), Value::String(display_text.to_string()));
        }
        // 保留 paragraph_count 以便反序列化时还原
        let pc = seg
            .get("paragraph_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        if pc != 0 {
            d.insert("pc".into(), Value::Number(pc.into()));
        }
    }
    Value::Object(d)
}

fn deserialize_segment_to_dict(seg: &Value) -> Value {
    if !seg.is_object() {
        return Value::Object(Map::new());
    }
    let obj = seg.as_object().unwrap();

    // 旧格式兼容：有 "paragraphs" 或 "page_no" 键
    if obj.contains_key("paragraphs") || obj.contains_key("page_no") {
        let paragraphs_raw = seg
            .get("paragraphs")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let paragraphs: Vec<Value> = paragraphs_raw.iter().map(deserialize_paragraph).collect();
        let visible: Vec<&Value> = paragraphs
            .iter()
            .filter(|p| {
                !p.get("consumed_by_prev")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
            })
            .collect();
        let source_text = visible
            .iter()
            .filter_map(|p| {
                let t = p
                    .get("source_text")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim();
                if t.is_empty() {
                    None
                } else {
                    Some(t)
                }
            })
            .collect::<Vec<_>>()
            .join("\n\n");
        let display_text = visible
            .iter()
            .filter_map(|p| {
                let t = (p.get("display_text").or(p.get("source_text")))
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim();
                if t.is_empty() {
                    None
                } else {
                    Some(t)
                }
            })
            .collect::<Vec<_>>()
            .join("\n\n");
        let page_no = seg.get("page_no").and_then(|v| v.as_i64()).unwrap_or(0);
        let paragraph_count = seg
            .get("paragraph_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(visible.len() as i64);

        let mut d = Map::new();
        d.insert("page_no".into(), Value::Number(page_no.into()));
        d.insert(
            "paragraph_count".into(),
            Value::Number(paragraph_count.into()),
        );
        d.insert("source_text".into(), Value::String(source_text));
        d.insert("display_text".into(), Value::String(display_text));
        d.insert("paragraphs".into(), Value::Array(paragraphs));
        return Value::Object(d);
    }

    // 新格式：短键名
    let paragraphs: Vec<Value> = seg
        .get("ps")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .iter()
        .map(deserialize_paragraph)
        .collect();
    let visible: Vec<&Value> = paragraphs
        .iter()
        .filter(|p| {
            !p.get("consumed_by_prev")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
        })
        .collect();
    let page_no = seg.get("p").and_then(|v| v.as_i64()).unwrap_or(0);
    // 从 st/dt 短键还原顶层正文（paragraphs 为空时使用）
    let top_source = seg.get("st").and_then(|v| v.as_str()).unwrap_or("");
    let top_display = seg.get("dt").and_then(|v| v.as_str()).unwrap_or("");
    let paragraph_count = seg
        .get("pc")
        .and_then(|v| v.as_i64())
        .unwrap_or(visible.len() as i64);
    let source_text = if !visible.is_empty() {
        visible
            .iter()
            .filter_map(|p| {
                let t = p
                    .get("source_text")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim();
                if t.is_empty() {
                    None
                } else {
                    Some(t)
                }
            })
            .collect::<Vec<_>>()
            .join("\n\n")
    } else if !top_source.is_empty() {
        top_source.to_string()
    } else {
        String::new()
    };
    let display_text = if !visible.is_empty() {
        visible
            .iter()
            .filter_map(|p| {
                let t = (p.get("display_text").or(p.get("source_text")))
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .trim();
                if t.is_empty() {
                    None
                } else {
                    Some(t)
                }
            })
            .collect::<Vec<_>>()
            .join("\n\n")
    } else if !top_display.is_empty() {
        top_display.to_string()
    } else if !top_source.is_empty() {
        top_source.to_string()
    } else {
        String::new()
    };

    let mut d = Map::new();
    d.insert("page_no".into(), Value::Number(page_no.into()));
    d.insert(
        "paragraph_count".into(),
        Value::Number(paragraph_count.into()),
    );
    d.insert("source_text".into(), Value::String(source_text));
    d.insert("display_text".into(), Value::String(display_text));
    d.insert("paragraphs".into(), Value::Array(paragraphs));
    Value::Object(d)
}

// ── Paragraph ──

fn serialize_paragraph(p: &Value) -> Value {
    let source = p.get("source_text").and_then(|v| v.as_str()).unwrap_or("");
    let display = p.get("display_text").and_then(|v| v.as_str()).unwrap_or("");

    let mut d = Map::new();
    let order = p.get("order").and_then(|v| v.as_i64()).unwrap_or(0);
    if order != 0 {
        d.insert("o".into(), Value::Number(order.into()));
    }
    let kind = p.get("kind").and_then(|v| v.as_str()).unwrap_or("body");
    if kind != "body" {
        d.insert("k".into(), Value::String(kind.to_string()));
    }
    d.insert("s".into(), Value::String(source.to_string()));

    let hl = p.get("heading_level").and_then(|v| v.as_i64()).unwrap_or(0);
    if hl != 0 {
        d.insert("hl".into(), Value::Number(hl.into()));
    }
    if !display.is_empty() && display != source {
        d.insert("d".into(), Value::String(display.to_string()));
    }
    if let Some(cp) = p.get("cross_page") {
        if !cp.is_null() {
            d.insert("cp".into(), cp.clone());
        }
    }
    if p.get("consumed_by_prev")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        d.insert("cbp".into(), Value::Bool(true));
    }
    if let Some(sp) = p.get("section_path") {
        if !sp.is_null() {
            d.insert("sp".into(), sp.clone());
        }
    }
    let ppl = p
        .get("print_page_label")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if !ppl.is_empty() {
        d.insert("ppl".into(), Value::String(ppl.to_string()));
    }
    let tt = p
        .get("translated_text")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if !tt.is_empty() {
        d.insert("tt".into(), Value::String(tt.to_string()));
    }
    let ts = p
        .get("translation_status")
        .and_then(|v| v.as_str())
        .unwrap_or("pending");
    if ts != "pending" {
        d.insert("ts".into(), Value::String(ts.to_string()));
    }
    let ac = p.get("attempt_count").and_then(|v| v.as_i64()).unwrap_or(0);
    if ac != 0 {
        d.insert("ac".into(), Value::Number(ac.into()));
    }
    let le = p.get("last_error").and_then(|v| v.as_str()).unwrap_or("");
    if !le.is_empty() {
        d.insert("le".into(), Value::String(le.to_string()));
    }
    if p.get("manual_resolved")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        d.insert("mr".into(), Value::Bool(true));
    }
    Value::Object(d)
}

fn deserialize_paragraph(d: &Value) -> Value {
    if !d.is_object() {
        return Value::Object(Map::new());
    }
    let obj = d.as_object().unwrap();

    let source = obj
        .get("s")
        .or(obj.get("source_text"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let display = obj
        .get("d")
        .or(obj.get("display_text"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    // 每个字段统一走 `短键.or(长键).<取值>.unwrap_or(默认)`：
    // 缺键 → get None → unwrap_or 默认；键存在但类型不符 → and_then None → 默认。
    // 与原先逐字段的 `has_*` + `if/else` 分支逐一等价（含「键存在且为 null」时两者都保留 null），
    // 故可删除 12 个 has_* 标志（省去每段 24 次冗余 contains_key）。
    let mut map = Map::new();
    map.insert(
        "order".into(),
        obj.get("o")
            .or(obj.get("order"))
            .cloned()
            .unwrap_or(Value::Number(0.into())),
    );
    map.insert(
        "kind".into(),
        Value::String(
            obj.get("k")
                .or(obj.get("kind"))
                .and_then(|v| v.as_str())
                .unwrap_or("body")
                .to_string(),
        ),
    );
    map.insert(
        "heading_level".into(),
        obj.get("hl")
            .or(obj.get("heading_level"))
            .cloned()
            .unwrap_or(Value::Number(0.into())),
    );
    map.insert("source_text".into(), Value::String(source.to_string()));
    map.insert(
        "display_text".into(),
        Value::String(if display.is_empty() {
            source.to_string()
        } else {
            display.to_string()
        }),
    );
    map.insert(
        "cross_page".into(),
        obj.get("cp")
            .or(obj.get("cross_page"))
            .cloned()
            .unwrap_or(Value::Null),
    );
    let consumed = obj
        .get("cbp")
        .or(obj.get("consumed_by_prev"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    map.insert("consumed_by_prev".into(), Value::Bool(consumed));
    map.insert(
        "section_path".into(),
        obj.get("sp")
            .or(obj.get("section_path"))
            .cloned()
            .unwrap_or(Value::Array(vec![])),
    );
    map.insert(
        "print_page_label".into(),
        Value::String(
            obj.get("ppl")
                .or(obj.get("print_page_label"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        ),
    );
    map.insert(
        "translated_text".into(),
        Value::String(
            obj.get("tt")
                .or(obj.get("translated_text"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        ),
    );
    map.insert(
        "translation_status".into(),
        Value::String(
            obj.get("ts")
                .or(obj.get("translation_status"))
                .and_then(|v| v.as_str())
                .unwrap_or("pending")
                .to_string(),
        ),
    );
    map.insert(
        "attempt_count".into(),
        obj.get("ac")
            .or(obj.get("attempt_count"))
            .cloned()
            .unwrap_or(Value::Number(0.into())),
    );
    map.insert(
        "last_error".into(),
        Value::String(
            obj.get("le")
                .or(obj.get("last_error"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        ),
    );
    let manual_resolved = obj
        .get("mr")
        .or(obj.get("manual_resolved"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    map.insert("manual_resolved".into(), Value::Bool(manual_resolved));

    Value::Object(map)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn segment_roundtrip() {
        let segment = json!({
            "page_no": 1,
            "paragraphs": [
                {
                    "order": 1,
                    "kind": "body",
                    "heading_level": 0,
                    "source_text": "hello world",
                    "display_text": "hello world",
                    "consumed_by_prev": false
                }
            ]
        });
        let compressed = serialize_segment(&segment);
        let restored = deserialize_segment_to_dict(&compressed);
        assert_eq!(restored["page_no"], json!(1));
        assert_eq!(restored["paragraphs"][0]["source_text"], "hello world");
    }

    #[test]
    fn segment_roundtrip_full() {
        let segments = vec![json!({
            "page_no": 5,
            "paragraphs": [
                {"order": 1, "kind": "heading", "heading_level": 2,
                 "source_text": "Title", "display_text": "Title", "consumed_by_prev": false}
            ]
        })];
        let serialized = serialize_segments(&segments);
        let deserialized = deserialize_segments_to_dicts(&serialized);
        assert_eq!(deserialized.len(), 1);
        assert_eq!(deserialized[0]["page_no"], json!(5));
        assert_eq!(deserialized[0]["paragraphs"][0]["kind"], "heading");
    }

    #[test]
    fn old_format_compat() {
        let old_seg = json!({
            "page_no": 3,
            "paragraph_count": 1,
            "source_text": "old text",
            "display_text": "old text",
            "paragraphs": [
                {"order": 1, "source_text": "old text", "display_text": "old text"}
            ]
        });
        let restored = deserialize_segment_to_dict(&old_seg);
        assert_eq!(restored["page_no"], json!(3));
        assert_eq!(restored["source_text"], "old text");
    }

    #[test]
    fn empty_paragraphs_preserves_top_text() {
        // 段落为空但顶层正文非空时，source_text/display_text 不丢失
        let segment = json!({
            "page_no": 7,
            "paragraph_count": 1,
            "source_text": "top source",
            "display_text": "top display",
            "paragraphs": []
        });
        let compressed = serialize_segment(&segment);
        let restored = deserialize_segment_to_dict(&compressed);
        assert_eq!(restored["page_no"], json!(7));
        assert_eq!(restored["source_text"], "top source");
        assert_eq!(restored["display_text"], "top display");
        assert_eq!(restored["paragraph_count"], json!(1));
    }

    #[test]
    fn empty_paragraphs_no_top_text() {
        // 段落为空且顶层正文也为空时不应 panic
        let segment = json!({
            "page_no": 5,
            "paragraph_count": 0,
            "source_text": "",
            "display_text": "",
            "paragraphs": []
        });
        let compressed = serialize_segment(&segment);
        let restored = deserialize_segment_to_dict(&compressed);
        assert_eq!(restored["page_no"], json!(5));
        assert_eq!(restored["source_text"], "");
    }
}
