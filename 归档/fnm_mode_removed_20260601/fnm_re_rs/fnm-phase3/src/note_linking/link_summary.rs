//! ←→ Python `note_linking.py:_summarize_links / _link_quality_gate`

use fnm_core::records::NoteLinkRecord;

/// Link 统计摘要。
#[derive(Debug, Clone, Default)]
pub struct LinkSummary {
    pub matched: usize,
    pub footnote_orphan_note: usize,
    pub footnote_orphan_anchor: usize,
    pub endnote_orphan_note: usize,
    pub endnote_orphan_anchor: usize,
    pub ambiguous: usize,
    pub ignored: usize,
    pub fallback_count: usize,
    pub repair_count: usize,
    pub fallback_matched_count: usize,
    pub fallback_match_ratio: f64,
}

/// 聚合 link 统计。
///
/// ←→ Python `_summarize_links`
pub fn summarize_links(links: &[NoteLinkRecord]) -> LinkSummary {
    let mut summary = LinkSummary::default();

    for row in links {
        let status = row.status.as_str();
        let kind = row.note_kind.as_str();
        let resolver = row.resolver.as_str();

        if status == "matched" {
            summary.matched += 1;
            if resolver == "fallback" {
                summary.fallback_matched_count += 1;
            }
        }
        if kind == "footnote" && status == "orphan_note" {
            summary.footnote_orphan_note += 1;
        }
        if kind == "footnote" && status == "orphan_anchor" {
            summary.footnote_orphan_anchor += 1;
        }
        if kind == "endnote" && status == "orphan_note" {
            summary.endnote_orphan_note += 1;
        }
        if kind == "endnote" && status == "orphan_anchor" {
            summary.endnote_orphan_anchor += 1;
        }
        if status == "ambiguous" {
            summary.ambiguous += 1;
        }
        if status == "ignored" {
            summary.ignored += 1;
        }
        if resolver == "fallback" {
            summary.fallback_count += 1;
        }
        if resolver == "repair" {
            summary.repair_count += 1;
        }
    }

    summary.fallback_match_ratio = if summary.matched > 0 {
        summary.fallback_matched_count as f64 / summary.matched as f64
    } else {
        0.0
    };

    summary
}

/// 质量门判定。
///
/// ←→ Python `_link_quality_gate`
pub struct QualityGateResult {
    pub quality_ok: bool,
    pub fallback_match_ratio: f64,
    pub orphan_anchor_total: usize,
    pub footnote_orphan_anchor_total: usize,
    pub endnote_orphan_anchor_total: usize,
}

pub fn link_quality_gate(
    links: &[NoteLinkRecord],
    fallback_threshold: f64,
    orphan_threshold: usize,
) -> QualityGateResult {
    let summary = summarize_links(links);
    let orphan_anchor_total = summary.footnote_orphan_anchor + summary.endnote_orphan_anchor;

    // fallback 率只在存在尾注孤儿 anchor 时才有质量含义。
    let quality_ok = summary.endnote_orphan_anchor <= orphan_threshold
        && (summary.endnote_orphan_anchor == 0
            || summary.fallback_match_ratio <= fallback_threshold);

    QualityGateResult {
        quality_ok,
        fallback_match_ratio: summary.fallback_match_ratio,
        orphan_anchor_total,
        footnote_orphan_anchor_total: summary.footnote_orphan_anchor,
        endnote_orphan_anchor_total: summary.endnote_orphan_anchor,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use fnm_core::types::{LinkResolver, LinkStatus, NoteKind};

    fn make_link(status: LinkStatus, resolver: LinkResolver, kind: NoteKind) -> NoteLinkRecord {
        NoteLinkRecord {
            status,
            resolver,
            note_kind: kind,
            ..Default::default()
        }
    }

    #[test]
    fn test_summarize_links() {
        let links = vec![
            make_link(LinkStatus::Matched, LinkResolver::Rule, NoteKind::Footnote),
            make_link(
                LinkStatus::Matched,
                LinkResolver::Fallback,
                NoteKind::Footnote,
            ),
            make_link(
                LinkStatus::OrphanNote,
                LinkResolver::Rule,
                NoteKind::Endnote,
            ),
            make_link(
                LinkStatus::OrphanAnchor,
                LinkResolver::Rule,
                NoteKind::Endnote,
            ),
            make_link(
                LinkStatus::Ambiguous,
                LinkResolver::Rule,
                NoteKind::Footnote,
            ),
            make_link(LinkStatus::Ignored, LinkResolver::Rule, NoteKind::Footnote),
        ];

        let summary = summarize_links(&links);
        assert_eq!(summary.matched, 2);
        assert_eq!(summary.fallback_matched_count, 1);
        assert_eq!(summary.fallback_match_ratio, 0.5);
        assert_eq!(summary.footnote_orphan_note, 0);
        assert_eq!(summary.endnote_orphan_note, 1);
        assert_eq!(summary.endnote_orphan_anchor, 1);
        assert_eq!(summary.ambiguous, 1);
        assert_eq!(summary.ignored, 1);
        assert_eq!(summary.fallback_count, 1);
    }

    #[test]
    fn test_link_quality_gate() {
        // 尾注 orphan_anchor = 0 → 永远 quality_ok
        let links = vec![make_link(
            LinkStatus::Matched,
            LinkResolver::Fallback,
            NoteKind::Footnote,
        )];
        let result = link_quality_gate(&links, 0.1, 10);
        assert!(result.quality_ok);

        // 尾注 orphan_anchor > threshold → quality_ok = false
        let links = vec![
            make_link(
                LinkStatus::OrphanAnchor,
                LinkResolver::Rule,
                NoteKind::Endnote,
            ),
            make_link(
                LinkStatus::OrphanAnchor,
                LinkResolver::Rule,
                NoteKind::Endnote,
            ),
            make_link(
                LinkStatus::OrphanAnchor,
                LinkResolver::Rule,
                NoteKind::Endnote,
            ),
        ];
        let result = link_quality_gate(&links, 0.3, 2);
        assert!(!result.quality_ok);
        assert_eq!(result.endnote_orphan_anchor_total, 3);
    }
}
