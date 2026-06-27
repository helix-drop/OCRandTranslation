-- FNM_RE SQLite schema — 初始迁移
-- 来源：persistence/sqlite_schema.py _migrate_fnm_schema (SCHEMA_VERSION 25)

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '25');

-- 最小 documents 表（满足外键约束）
CREATE TABLE IF NOT EXISTS documents (
    id    TEXT PRIMARY KEY,
    slug  TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'idle'
);

-- Phase 1 ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fnm_pages (
    row_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id               TEXT NOT NULL,
    page_no              INTEGER NOT NULL,
    target_pdf_page      INTEGER,
    page_role            TEXT NOT NULL,
    role_confidence      REAL NOT NULL DEFAULT 0,
    role_reason          TEXT,
    section_hint         TEXT,
    has_note_heading     INTEGER NOT NULL DEFAULT 0,
    note_scan_summary_json TEXT,
    created_at           INTEGER NOT NULL,
    updated_at           INTEGER NOT NULL,
    UNIQUE(doc_id, page_no),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_pages_doc_role
    ON fnm_pages(doc_id, page_no, page_role);

CREATE TABLE IF NOT EXISTS fnm_chapters (
    row_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id          TEXT NOT NULL,
    chapter_id      TEXT NOT NULL,
    title           TEXT,
    start_page      INTEGER NOT NULL,
    end_page        INTEGER NOT NULL,
    pages_json      TEXT,
    source          TEXT,
    boundary_state  TEXT NOT NULL DEFAULT 'ready',
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    UNIQUE(doc_id, chapter_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_chapters_doc_page
    ON fnm_chapters(doc_id, start_page, end_page);

CREATE TABLE IF NOT EXISTS fnm_heading_candidates (
    row_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id               TEXT NOT NULL,
    heading_id           TEXT NOT NULL,
    page_no              INTEGER NOT NULL,
    text                 TEXT NOT NULL,
    normalized_text      TEXT NOT NULL,
    source               TEXT NOT NULL CHECK(source IN ('visual_toc','ocr_block','pdf_font_band','markdown_heading','note_heading')),
    block_label          TEXT,
    top_band             INTEGER NOT NULL DEFAULT 0,
    font_height          REAL,
    x                    REAL,
    y                    REAL,
    width_estimate       REAL,
    confidence           REAL NOT NULL DEFAULT 0,
    heading_family_guess TEXT NOT NULL CHECK(heading_family_guess IN ('book','chapter','section','note','other','unknown')),
    suppressed_as_chapter INTEGER NOT NULL DEFAULT 0,
    reject_reason        TEXT,
    font_name            TEXT,
    font_weight_hint     TEXT,
    align_hint           TEXT,
    width_ratio          REAL,
    heading_level_hint   INTEGER,
    created_at           INTEGER NOT NULL,
    updated_at           INTEGER NOT NULL,
    UNIQUE(doc_id, heading_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_heading_candidates_doc_page
    ON fnm_heading_candidates(doc_id, page_no, source, heading_family_guess);

CREATE TABLE IF NOT EXISTS fnm_section_heads (
    row_id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id                    TEXT NOT NULL,
    section_head_id           TEXT NOT NULL,
    chapter_id                TEXT,
    page_no                   INTEGER NOT NULL,
    text                      TEXT NOT NULL,
    normalized_text           TEXT NOT NULL,
    level                     INTEGER NOT NULL DEFAULT 0,
    source                    TEXT NOT NULL CHECK(source IN ('visual_toc','ocr_block','pdf_font_band','markdown_heading','note_heading')),
    confidence                REAL NOT NULL DEFAULT 0,
    heading_family_guess      TEXT NOT NULL CHECK(heading_family_guess IN ('book','chapter','section','note','other','unknown')),
    rejected_chapter_candidate INTEGER NOT NULL DEFAULT 0,
    reject_reason             TEXT,
    derived_from_heading_id   TEXT,
    created_at                INTEGER NOT NULL,
    updated_at                INTEGER NOT NULL,
    UNIQUE(doc_id, section_head_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_section_heads_doc_page
    ON fnm_section_heads(doc_id, page_no, chapter_id, rejected_chapter_candidate);

-- Phase 2 ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fnm_note_regions (
    row_id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id                         TEXT NOT NULL,
    region_id                      TEXT NOT NULL,
    region_kind                    TEXT NOT NULL,
    start_page                     INTEGER NOT NULL,
    end_page                       INTEGER NOT NULL,
    pages_json                     TEXT,
    title_hint                     TEXT,
    bound_chapter_id               TEXT,
    region_scope                   TEXT NOT NULL,
    region_source                  TEXT NOT NULL,
    start_reason                   TEXT NOT NULL,
    end_reason                     TEXT NOT NULL,
    review_required                INTEGER NOT NULL,
    region_start_first_source_marker TEXT,
    region_first_note_item_marker  TEXT,
    region_marker_alignment_ok     INTEGER NOT NULL DEFAULT 0,
    created_at                     INTEGER NOT NULL,
    updated_at                     INTEGER NOT NULL,
    UNIQUE(doc_id, region_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_note_regions_doc_page
    ON fnm_note_regions(doc_id, start_page, end_page, region_kind);

CREATE TABLE IF NOT EXISTS fnm_chapter_note_modes (
    row_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id               TEXT NOT NULL,
    chapter_id           TEXT NOT NULL,
    chapter_title        TEXT,
    note_mode            TEXT NOT NULL,
    region_ids_json      TEXT NOT NULL,
    primary_region_scope TEXT NOT NULL,
    has_footnote_band    INTEGER NOT NULL,
    has_endnote_region   INTEGER NOT NULL,
    sampled_pages_json   TEXT,
    detection_confidence REAL NOT NULL DEFAULT 0,
    created_at           INTEGER NOT NULL,
    updated_at           INTEGER NOT NULL,
    UNIQUE(doc_id, chapter_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_chapter_note_modes_doc_mode
    ON fnm_chapter_note_modes(doc_id, note_mode);

CREATE TABLE IF NOT EXISTS fnm_note_items (
    row_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id            TEXT NOT NULL,
    note_item_id      TEXT NOT NULL,
    note_kind         TEXT NOT NULL,
    chapter_id        TEXT,
    region_id         TEXT,
    marker            TEXT,
    marker_type       TEXT NOT NULL,
    normalized_marker TEXT,
    occurrence        INTEGER NOT NULL DEFAULT 0,
    source_text       TEXT,
    item_source       TEXT NOT NULL,
    source_page_label TEXT NOT NULL,
    is_reconstructed  INTEGER NOT NULL,
    review_required   INTEGER NOT NULL,
    projection_mode   TEXT,
    owner_chapter_id  TEXT,
    page_no           INTEGER NOT NULL,
    display_marker    TEXT,
    source_marker     TEXT,
    title_hint        TEXT,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL,
    UNIQUE(doc_id, note_item_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_note_items_doc_kind
    ON fnm_note_items(doc_id, note_kind, chapter_id, region_id, page_no);

-- Phase 3 ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fnm_body_anchors (
    row_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id             TEXT NOT NULL,
    anchor_id          TEXT NOT NULL,
    chapter_id         TEXT,
    page_no            INTEGER NOT NULL,
    paragraph_index    INTEGER NOT NULL DEFAULT 0,
    char_start         INTEGER NOT NULL DEFAULT 0,
    char_end           INTEGER NOT NULL DEFAULT 0,
    source_marker      TEXT,
    normalized_marker  TEXT,
    anchor_kind        TEXT NOT NULL,
    certainty          REAL NOT NULL DEFAULT 0,
    source_text        TEXT,
    anchor_source      TEXT NOT NULL,
    synthetic          INTEGER NOT NULL,
    ocr_repaired_from_marker TEXT NOT NULL,
    coordinate_unit    TEXT NOT NULL,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL,
    UNIQUE(doc_id, anchor_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_body_anchors_doc_page
    ON fnm_body_anchors(doc_id, chapter_id, page_no, normalized_marker);

CREATE TABLE IF NOT EXISTS fnm_note_links (
    row_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id          TEXT NOT NULL,
    link_id         TEXT NOT NULL,
    chapter_id      TEXT,
    region_id       TEXT,
    note_item_id    TEXT,
    anchor_id       TEXT,
    status          TEXT NOT NULL,
    resolver        TEXT,
    confidence      REAL NOT NULL DEFAULT 0,
    note_kind       TEXT,
    marker          TEXT,
    page_no_start   INTEGER,
    page_no_end     INTEGER,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    UNIQUE(doc_id, link_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_note_links_doc_status
    ON fnm_note_links(doc_id, status, chapter_id, region_id);

CREATE TABLE IF NOT EXISTS fnm_chapter_anchor_alignment (
    row_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id             TEXT NOT NULL,
    chapter_id         TEXT NOT NULL,
    alignment_status   TEXT NOT NULL DEFAULT 'misaligned',
    body_anchor_count  INTEGER NOT NULL DEFAULT 0,
    endnote_count      INTEGER NOT NULL DEFAULT 0,
    mismatch_json      TEXT,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL,
    UNIQUE(doc_id, chapter_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- Phase 4-6 辅助表 ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fnm_structure_reviews (
    row_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id       TEXT NOT NULL,
    review_type  TEXT NOT NULL,
    chapter_id   TEXT,
    page_start   INTEGER,
    page_end     INTEGER,
    payload_json TEXT,
    severity     TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_structure_reviews_doc_type
    ON fnm_structure_reviews(doc_id, review_type, severity);

CREATE TABLE IF NOT EXISTS fnm_chapter_body_pages (
    row_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id           TEXT NOT NULL,
    chapter_id       TEXT NOT NULL,
    body_pages_json  TEXT NOT NULL,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fnm_chapter_body_pages_doc_ch
    ON fnm_chapter_body_pages(doc_id, chapter_id);

CREATE TABLE IF NOT EXISTS fnm_chapter_endnotes (
    row_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id             TEXT NOT NULL,
    chapter_id         TEXT NOT NULL,
    ordinal            INTEGER NOT NULL,
    marker             TEXT,
    numbering_scheme   TEXT NOT NULL DEFAULT 'per_chapter',
    text               TEXT,
    source_page_no     INTEGER,
    is_reconstructed   INTEGER NOT NULL DEFAULT 0,
    review_required    INTEGER NOT NULL DEFAULT 1,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL,
    UNIQUE(doc_id, chapter_id, ordinal),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_chapter_endnotes_doc_chapter
    ON fnm_chapter_endnotes(doc_id, chapter_id, ordinal);

CREATE TABLE IF NOT EXISTS fnm_paragraph_footnotes (
    row_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id           TEXT NOT NULL,
    chapter_id       TEXT NOT NULL,
    page_no          INTEGER NOT NULL,
    paragraph_index  INTEGER NOT NULL DEFAULT 0,
    attachment_kind  TEXT NOT NULL DEFAULT 'page_tail',
    source_marker    TEXT,
    text             TEXT,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_paragraph_footnotes_doc_chapter
    ON fnm_paragraph_footnotes(doc_id, chapter_id, page_no);

CREATE TABLE IF NOT EXISTS fnm_review_overrides_v2 (
    row_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id       TEXT NOT NULL,
    scope        TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    UNIQUE(doc_id, scope, target_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_review_overrides_v2_doc_scope
    ON fnm_review_overrides_v2(doc_id, scope, target_id);
