-- 补充 _create_core_tables 中的 fnm 表（0001 遗漏）

CREATE TABLE IF NOT EXISTS fnm_translation_units (
    unit_id            TEXT PRIMARY KEY,
    doc_id             TEXT NOT NULL,
    kind               TEXT NOT NULL,
    owner_kind         TEXT,
    owner_id           TEXT,
    section_id         TEXT NOT NULL,
    section_title      TEXT,
    section_start_page INTEGER,
    section_end_page   INTEGER,
    note_id            TEXT,
    page_start         INTEGER,
    page_end           INTEGER,
    char_count         INTEGER NOT NULL DEFAULT 0,
    source_text        TEXT,
    translated_text    TEXT,
    status             TEXT NOT NULL DEFAULT 'pending',
    error_msg          TEXT,
    target_ref         TEXT,
    page_segments_json TEXT,
    source_hash        TEXT DEFAULT '',
    segment_plan_hash  TEXT DEFAULT '',
    pipeline_run_id    TEXT DEFAULT '',
    stale_reason       TEXT DEFAULT '',
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL,
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_units_doc_status
    ON fnm_translation_units(doc_id, status, kind, page_start, page_end);
CREATE INDEX IF NOT EXISTS idx_fnm_units_doc_section
    ON fnm_translation_units(doc_id, section_id, kind, page_start, page_end);

-- 补充 _migrate_fnm_schema 中的 pdf 字体候选表

CREATE TABLE IF NOT EXISTS fnm_pdf_font_candidates (
    row_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id          TEXT NOT NULL,
    pdf_hash        TEXT NOT NULL,
    page_indices    TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    UNIQUE(doc_id, pdf_hash, page_indices),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- 补充 fnm_runs（pipeline meta 追踪）

CREATE TABLE IF NOT EXISTS fnm_runs (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id                      TEXT NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'pending',
    error_msg                   TEXT,
    page_count                  INTEGER NOT NULL DEFAULT 0,
    section_count               INTEGER NOT NULL DEFAULT 0,
    note_count                  INTEGER NOT NULL DEFAULT 0,
    unit_count                  INTEGER NOT NULL DEFAULT 0,
    validation_json             TEXT,
    structure_state             TEXT,
    review_counts_json          TEXT,
    blocking_reasons_json       TEXT,
    link_summary_json           TEXT,
    page_partition_summary_json TEXT,
    chapter_mode_summary_json   TEXT,
    created_at                  INTEGER NOT NULL,
    updated_at                  INTEGER NOT NULL,
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fnm_runs_doc_updated
    ON fnm_runs(doc_id, updated_at);
