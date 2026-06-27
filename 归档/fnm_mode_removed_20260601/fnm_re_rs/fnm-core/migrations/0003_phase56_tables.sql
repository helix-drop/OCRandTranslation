-- Phase 5/6 tables: chapter_markdowns, diagnostic_pages, diagnostic_notes,
-- export_chapters, export_audit, export_bundle

CREATE TABLE IF NOT EXISTS fnm_chapter_markdowns (
    doc_id          TEXT NOT NULL,
    chapter_id      TEXT NOT NULL,
    order_idx       INTEGER NOT NULL,
    title           TEXT,
    path            TEXT,
    markdown_text   TEXT,
    start_page      INTEGER,
    end_page        INTEGER,
    pages_json      TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    PRIMARY KEY(doc_id, chapter_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fnm_diagnostic_pages (
    doc_id           TEXT NOT NULL,
    page_bp          INTEGER NOT NULL,
    status           TEXT,
    pages            TEXT,
    page_entries_json TEXT,
    fnm_source_json  TEXT,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    PRIMARY KEY(doc_id, page_bp),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fnm_diagnostic_notes (
    doc_id              TEXT NOT NULL,
    note_id             TEXT NOT NULL,
    section_id          TEXT,
    section_title       TEXT,
    section_start_page  INTEGER,
    section_end_page    INTEGER,
    kind                TEXT,
    original_marker     TEXT,
    start_page          INTEGER,
    pages_json          TEXT,
    source_text         TEXT,
    translated_text     TEXT,
    translate_status    TEXT,
    region_id           TEXT,
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL,
    PRIMARY KEY(doc_id, note_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fnm_export_chapters (
    doc_id          TEXT NOT NULL,
    section_id      TEXT NOT NULL,
    order_idx       INTEGER NOT NULL,
    title           TEXT,
    path            TEXT,
    content         TEXT,
    start_page      INTEGER,
    end_page        INTEGER,
    pages_json      TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    PRIMARY KEY(doc_id, section_id),
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fnm_export_audit (
    doc_id          TEXT PRIMARY KEY,
    report_json     TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fnm_export_bundle (
    doc_id          TEXT PRIMARY KEY,
    bundle_json     TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
