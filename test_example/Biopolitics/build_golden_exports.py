#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx
from openai import OpenAI


ROOT = Path("/Users/hao/OCRandTranslation")
BOOK_DIR = ROOT / "test_example" / "Biopolitics"
GOLDEN_DIR = BOOK_DIR / "golden_exports"
FNM_DIR = GOLDEN_DIR / "fnm_obsidian"
SOURCE_DIR = FNM_DIR / "chapters_source"
TRANSLATED_DIR = FNM_DIR / "chapters"
BILINGUAL_DIR = FNM_DIR / "chapters_bilingual"
CACHE_PATH = GOLDEN_DIR / "note_translation_cache.json"
MANIFEST_PATH = GOLDEN_DIR / "golden_note_manifest.json"
REPORT_PATH = GOLDEN_DIR / "AUDIT_REPORT.md"
CONFIG_PATH = ROOT / "local_data" / "user_data" / "config.json"
BUNDLE_PATH = ROOT / "local_data" / "user_data" / "data" / "documents" / "43bd9b83b99c" / "fnm_export_bundle.json"
API_BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"

NOTES_HEADER_RE = re.compile(r"(?m)^\*NOTES\*\s*$|^###\s+NOTES\s*$|^###\s+笔记\s*$")
NOTE_DEF_RE = re.compile(r"(?ms)^\[\^(\d+)\]:\s*(.*?)(?=^\[\^\d+\]:|\Z)")
TITLE_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
SUBTITLE_RE = re.compile(r"(?m)^###\s+(.+?)\s*$")
TRAILING_NOTE_SECTION_RE = re.compile(r"(?ms)\n###\s*(?:NOTES|笔记|尾注|脚注|注释)\s*\n.*$")
TRAILING_NOTE_DEFS_RE = re.compile(r"(?ms)\n\[\^\d+\]:.*$")
JSON_FENCE_RE = re.compile(r"```(?:json)?\s*|\s*```", re.IGNORECASE)


@dataclass
class Note:
    chapter_order: int
    chapter_title: str
    chapter_file: str
    note_no: int
    source: str

    @property
    def key(self) -> str:
        return f"{self.chapter_order:03d}-{self.note_no:03d}"


@dataclass
class Chapter:
    order: int
    filename: str
    title: str
    source_text: str
    source_body: str
    notes: list[Note]
    translated_subtitle: str
    translated_body: str


def normalize_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def normalize_spaces(text: str) -> str:
    text = normalize_newlines(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_source_chapter(text: str) -> tuple[str, str, list[tuple[int, str]]]:
    text = normalize_newlines(text).strip()
    title_match = TITLE_RE.search(text)
    if not title_match:
        raise RuntimeError("source chapter missing ## title")
    title = title_match.group(1).strip()
    remainder = text[title_match.end():].lstrip("\n")
    notes_match = NOTES_HEADER_RE.search(remainder)
    if notes_match:
        body = remainder[:notes_match.start()].strip()
        notes_blob = remainder[notes_match.end():].strip()
    else:
        body = remainder.strip()
        notes_blob = ""
    notes: list[tuple[int, str]] = []
    if notes_blob:
        for match in NOTE_DEF_RE.finditer(notes_blob):
            note_no = int(match.group(1))
            note_text = normalize_spaces(match.group(2))
            notes.append((note_no, note_text))
    return title, body, notes


def parse_translated_bundle_chapter(text: str) -> tuple[str, str]:
    text = normalize_newlines(text).strip()
    lines = text.splitlines()
    idx = 0
    if idx < len(lines) and lines[idx].startswith("## "):
        idx += 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
    subtitle = ""
    if idx < len(lines) and lines[idx].startswith("### "):
        subtitle = lines[idx][4:].strip()
        idx += 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
    body = "\n".join(lines[idx:]).strip()
    body = TRAILING_NOTE_SECTION_RE.sub("", "\n" + body).strip()
    body = TRAILING_NOTE_DEFS_RE.sub("", "\n" + body).strip()
    return subtitle, body


def load_chapters() -> list[Chapter]:
    bundle = load_json(BUNDLE_PATH)
    files = bundle["files"]
    chapters: list[Chapter] = []
    for order, path in enumerate(sorted(SOURCE_DIR.glob("*.md")), start=1):
        source_text = path.read_text(encoding="utf-8")
        title, source_body, note_pairs = split_source_chapter(source_text)
        bundle_key = f"chapters/{path.name}"
        if bundle_key not in files:
            raise RuntimeError(f"missing translated bundle chapter: {bundle_key}")
        translated_subtitle, translated_body = parse_translated_bundle_chapter(files[bundle_key])
        notes = [
            Note(
                chapter_order=order,
                chapter_title=title,
                chapter_file=path.name,
                note_no=no,
                source=src,
            )
            for no, src in note_pairs
        ]
        chapters.append(
            Chapter(
                order=order,
                filename=path.name,
                title=title,
                source_text=source_text,
                source_body=source_body,
                notes=notes,
                translated_subtitle=translated_subtitle,
                translated_body=translated_body,
            )
        )
    return chapters


def extract_json_object(text: str) -> dict | None:
    cleaned = JSON_FENCE_RE.sub("", str(text or "")).strip()
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start = cleaned.find("{")
    while start >= 0:
        depth = 0
        for idx in range(start, len(cleaned)):
            ch = cleaned[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = cleaned[start:idx + 1]
                    try:
                        obj = json.loads(chunk)
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        break
        start = cleaned.find("{", start + 1)
    return None


def load_reusable_cache(notes: Iterable[Note]) -> dict[str, dict]:
    wanted = {note.key: note for note in notes}
    if not CACHE_PATH.exists():
        return {}
    raw = load_json(CACHE_PATH)
    items = raw.get("items", raw if isinstance(raw, dict) else {})
    reusable: dict[str, dict] = {}
    for key, payload in items.items():
        if key not in wanted or not isinstance(payload, dict):
            continue
        translation = normalize_spaces(payload.get("translation", ""))
        source = normalize_spaces(payload.get("source", ""))
        method = str(payload.get("method", "") or "")
        if not translation or source != wanted[key].source:
            continue
        if method != "llm_exact":
            continue
        reusable[key] = {
            "title": wanted[key].chapter_title,
            "note": wanted[key].note_no,
            "source": wanted[key].source,
            "translation": translation,
            "method": method,
            "model": str(payload.get("model", MODEL) or MODEL),
            "generated_at": str(payload.get("generated_at", "") or ""),
        }
    return reusable


def build_batches(notes: list[Note], max_items: int = 2, max_chars: int = 3200) -> list[list[Note]]:
    batches: list[list[Note]] = []
    current: list[Note] = []
    current_chars = 0
    for note in notes:
        note_chars = len(note.source)
        if current and (len(current) >= max_items or current_chars + note_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(note)
        current_chars += note_chars
    if current:
        batches.append(current)
    return batches


def make_client() -> OpenAI:
    config = load_json(CONFIG_PATH)
    api_key = str(config.get("deepseek_key", "") or "").strip()
    if not api_key:
        raise RuntimeError("deepseek_key missing in config")
    return OpenAI(
        api_key=api_key,
        base_url=API_BASE_URL,
        timeout=httpx.Timeout(90.0, connect=20.0, read=90.0, write=20.0),
        max_retries=1,
    )


SYSTEM_PROMPT = """你是一位严谨的法语学术注释翻译员。你的任务是把法语讲末尾注逐条完整翻译成简体中文。

硬性要求：
1. 只翻译，不总结，不删节，不改写为提要。
2. 不得改动编号，不得漏掉任何一条。
3. 书名、人名、刊名、引文、年份、页码、卷号、括号、引号、破折号都要保留。
4. 引文中的法语/拉丁语/英语原文保留原样，整体译成中文。
5. 遇到 OCR 噪声、缺字、问号方括号等可疑处，按原文保留并尽量译出，不得擅自补造。
6. 输出必须是严格 JSON 对象，不要 markdown，不要解释。

输出格式：
{"items":[{"key":"001-001","translation":"中文译文"}]}"""


def request_batch_translation(client: OpenAI, batch: list[Note], attempt: int = 1) -> dict[str, str]:
    payload = {
        "items": [
            {
                "key": note.key,
                "title": note.chapter_title,
                "note": note.note_no,
                "source": note.source,
            }
            for note in batch
        ]
    }
    user_msg = (
        "请把下面这些《Naissance de la biopolitique》的法语讲末尾注逐条完整翻译成简体中文。\n"
        "不得遗漏任何一条，不得合并，不得解释。\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.1,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
    text = response.choices[0].message.content if response.choices else ""
    obj = extract_json_object(text)
    if not isinstance(obj, dict) or not isinstance(obj.get("items"), list):
        raise RuntimeError(f"batch json parse failed on attempt {attempt}")
    results: dict[str, str] = {}
    for item in obj["items"]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "") or "").strip()
        translation = normalize_spaces(item.get("translation", ""))
        if key and translation:
            results[key] = translation
    missing = [note.key for note in batch if note.key not in results]
    if missing:
        raise RuntimeError(f"batch missing translations: {missing}")
    return results


def request_single_translation_plain(client: OpenAI, note: Note, attempt: int = 1) -> str:
    user_msg = (
        "请把下面这条《Naissance de la biopolitique》的法语讲末尾注完整翻译成简体中文。\n"
        "只输出译文正文，不要 JSON，不要解释，不要编号。\n"
        f"标题：{note.chapter_title}\n"
        f"注释编号：{note.note_no}\n"
        f"原文：{note.source}"
    )
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.1,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": "你是一位严谨的法语学术注释翻译员。把法语注释完整翻译成简体中文。只输出译文，不要任何说明。"},
            {"role": "user", "content": user_msg},
        ],
    )
    text = response.choices[0].message.content if response.choices else ""
    translation = normalize_spaces(text)
    translation = re.sub(r"^(?:译文|翻译)\s*[:：]\s*", "", translation)
    if not translation:
        raise RuntimeError(f"single plain translation empty on attempt {attempt}")
    return translation


def translate_notes(chapters: list[Chapter]) -> dict[str, dict]:
    all_notes = [note for chapter in chapters for note in chapter.notes]
    cache = load_reusable_cache(all_notes)
    client = make_client()
    pending = [note for note in all_notes if note.key not in cache]
    print(f"notes total={len(all_notes)} reusable={len(cache)} pending={len(pending)}", flush=True)
    batches = build_batches(pending)
    completed = len(cache)

    def persist() -> None:
        payload = {
            "items": cache,
            "model": MODEL,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_json(CACHE_PATH, payload)

    persist()

    for idx, batch in enumerate(batches, start=1):
        print(
            f"requesting batch {idx}/{len(batches)} size={len(batch)} keys={[note.key for note in batch]}",
            flush=True,
        )
        try:
            translations = request_batch_translation(client, batch, attempt=1)
        except Exception as exc:
            print(f"batch {idx}/{len(batches)} failed, falling back to singles: {exc}", flush=True)
            translations = {}
            for note in batch:
                single = [note]
                success = False
                last_exc: Exception | None = None
                for attempt in range(1, 4):
                    try:
                        piece = request_single_translation_plain(client, note, attempt=attempt)
                        translations[note.key] = piece
                        success = True
                        break
                    except Exception as inner_exc:
                        last_exc = inner_exc
                        time.sleep(min(10, attempt * 2))
                if not success:
                    raise RuntimeError(f"single note translation failed for {note.key}: {last_exc}") from last_exc
        for note in batch:
            cache[note.key] = {
                "title": note.chapter_title,
                "note": note.note_no,
                "source": note.source,
                "translation": normalize_spaces(translations[note.key]),
                "method": "llm_exact",
                "model": MODEL,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        completed += len(batch)
        persist()
        print(f"translated {completed}/{len(all_notes)}", flush=True)
    return cache


def source_index_text(chapters: list[Chapter]) -> str:
    lines = ["# Naissance de la biopolitique - source", ""]
    lines.extend(f"- [{chapter.title}](chapters_source/{chapter.filename})" for chapter in chapters)
    return "\n".join(lines).strip() + "\n"


def translated_index_text(chapters: list[Chapter]) -> str:
    lines = ["# Naissance de la biopolitique - translation", ""]
    lines.extend(f"- [{chapter.title}](chapters/{chapter.filename})" for chapter in chapters)
    return "\n".join(lines).strip() + "\n"


def bilingual_index_text(chapters: list[Chapter]) -> str:
    lines = ["# Naissance de la biopolitique - bilingual", ""]
    lines.extend(f"- [{chapter.title}](chapters_bilingual/{chapter.filename})" for chapter in chapters)
    return "\n".join(lines).strip() + "\n"


def all_index_text() -> str:
    return (
        "# 导出目录\n\n"
        "- [纯译文](index.md)\n"
        "- [纯原文](index.source.md)\n"
        "- [双语对照](index.bilingual.md)\n"
    )


def quote_block(text: str) -> str:
    lines = normalize_newlines(text).splitlines()
    return "\n".join("> " + line if line else ">" for line in lines).strip()


def build_translated_chapter(chapter: Chapter, cache: dict[str, dict]) -> str:
    parts = [f"## {chapter.title}", ""]
    if chapter.translated_subtitle:
        parts.extend([f"### {chapter.translated_subtitle}", ""])
    parts.append(chapter.translated_body.strip())
    if chapter.notes:
        parts.extend(["", "### 笔记", ""])
        for note in chapter.notes:
            translated = cache[note.key]["translation"]
            parts.append(f"[^{note.note_no}]: {translated}")
    return "\n".join(parts).strip() + "\n"


def build_bilingual_chapter(chapter: Chapter, cache: dict[str, dict]) -> str:
    parts = [f"## {chapter.title}", ""]
    if chapter.translated_subtitle:
        parts.extend([f"### {chapter.translated_subtitle}", ""])
    parts.extend(["### 原文", "", quote_block(chapter.source_body), "", "### 译文", "", chapter.translated_body.strip()])
    if chapter.notes:
        parts.extend(["", "### NOTES / 笔记", ""])
        for note in chapter.notes:
            parts.extend([
                quote_block(f"[^{note.note_no}]: {note.source}"),
                "",
                f"[^{note.note_no}]: {cache[note.key]['translation']}",
                "",
            ])
        while parts and not parts[-1].strip():
            parts.pop()
    return "\n".join(parts).strip() + "\n"


def write_exports(chapters: list[Chapter], cache: dict[str, dict]) -> None:
    ensure_dir(TRANSLATED_DIR)
    ensure_dir(BILINGUAL_DIR)
    for chapter in chapters:
        translated = build_translated_chapter(chapter, cache)
        bilingual = build_bilingual_chapter(chapter, cache)
        (TRANSLATED_DIR / chapter.filename).write_text(translated, encoding="utf-8")
        (BILINGUAL_DIR / chapter.filename).write_text(bilingual, encoding="utf-8")
    (FNM_DIR / "index.md").write_text(translated_index_text(chapters), encoding="utf-8")
    (FNM_DIR / "index.bilingual.md").write_text(bilingual_index_text(chapters), encoding="utf-8")
    (FNM_DIR / "index.source.md").write_text(source_index_text(chapters), encoding="utf-8")
    (FNM_DIR / "index.all.md").write_text(all_index_text(), encoding="utf-8")


def update_manifest(cache: dict[str, dict], chapters: list[Chapter]) -> None:
    manifest = load_json(MANIFEST_PATH)
    all_keys = {note.key for chapter in chapters for note in chapter.notes}
    missing = sorted(key for key in all_keys if key not in cache or not normalize_spaces(cache[key].get("translation", "")))
    manifest["translation_cache"] = str(CACHE_PATH.relative_to(ROOT))
    manifest["translation_model"] = MODEL
    manifest["translation_missing"] = missing
    manifest["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_json(MANIFEST_PATH, manifest)


def update_report(chapters: list[Chapter], cache: dict[str, dict]) -> None:
    source_total = sum(len(chapter.notes) for chapter in chapters)
    translated_total = sum(1 for payload in cache.values() if normalize_spaces(payload.get("translation", "")))
    text = REPORT_PATH.read_text(encoding="utf-8")
    replacement = (
        "## 当前状态\n\n"
        "- 已撤销先前由错误测试链条引出的 FNM_RE 源码/单测改动。\n"
        "- 已删除错误的 golden_exports，并从 PDF/raw_source 重新建立纯原文标准版。\n"
        "- 已基于标准原文重译全部讲末尾注，生成纯译文版与双语版，不再复用错误的页内手稿脚注映射。\n"
        "- 双语版现为“法语原文 + 中文译文”；第一讲尾注 1-18 已按 PDF NOTES 页重建。\n"
    )
    text = re.sub(r"## 当前状态\n\n(?:- .*\n)+", replacement, text, count=1)
    appendix = (
        "\n## 译文/双语生成\n\n"
        f"- 讲末尾注译文覆盖：{translated_total}/{source_total}\n"
        "- 纯译文正文底稿：当前数据库导出的章节中文正文。\n"
        "- 纯译文尾注来源：标准原文逐条重译。\n"
        "- 双语版结构：原文章节正文 + 中文正文，NOTES 区逐条提供法语原注与中文译注。\n"
    )
    if "## 译文/双语生成" in text:
        text = re.sub(r"\n## 译文/双语生成\n.*", appendix.rstrip() + "\n", text, flags=re.S)
    else:
        text = text.rstrip() + "\n" + appendix
    REPORT_PATH.write_text(text, encoding="utf-8")


def validate_exports(chapters: list[Chapter], cache: dict[str, dict]) -> None:
    if len(list(SOURCE_DIR.glob("*.md"))) != 14:
        raise RuntimeError("source chapter count mismatch")
    if len(list(TRANSLATED_DIR.glob("*.md"))) != 14:
        raise RuntimeError("translated chapter count mismatch")
    if len(list(BILINGUAL_DIR.glob("*.md"))) != 14:
        raise RuntimeError("bilingual chapter count mismatch")

    first_translated = (TRANSLATED_DIR / "001-Leçon du 10 janvier 1979.md").read_text(encoding="utf-8")
    if "Acceptation du principe" in first_translated:
        raise RuntimeError("wrong first chapter endnote leaked into translated export")
    if "[^1]: 维吉尔" not in first_translated and "[^1]: 维吉尔（Virgile）" not in first_translated:
        raise RuntimeError("first chapter note 1 translation missing expected Virgil lead")

    first_bilingual = (BILINGUAL_DIR / "001-Leçon du 10 janvier 1979.md").read_text(encoding="utf-8")
    if "### 原文" not in first_bilingual or "### 译文" not in first_bilingual:
        raise RuntimeError("bilingual headings missing")
    if "Citation de Virgile" not in first_bilingual:
        raise RuntimeError("bilingual French note missing")
    if "维吉尔" not in first_bilingual:
        raise RuntimeError("bilingual Chinese note missing")

    placeholder_hits: list[str] = []
    for path in list(TRANSLATED_DIR.glob("*.md")) + list(BILINGUAL_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for token in ("[待翻译]", "法语+法语", "未能翻译", "TODO"):
            if token in text:
                placeholder_hits.append(f"{path.name}:{token}")
    if placeholder_hits:
        raise RuntimeError(f"placeholder hits: {placeholder_hits[:10]}")

    for chapter in chapters:
        translated_text = (TRANSLATED_DIR / chapter.filename).read_text(encoding="utf-8")
        bilingual_text = (BILINGUAL_DIR / chapter.filename).read_text(encoding="utf-8")
        translated_nums = [int(x) for x in re.findall(r"^\[\^(\d+)\]:", translated_text, flags=re.M)]
        bilingual_nums = [int(x) for x in re.findall(r"^\[\^(\d+)\]:", bilingual_text, flags=re.M)]
        expected = [note.note_no for note in chapter.notes]
        if translated_nums != expected:
            raise RuntimeError(f"translated note numbering mismatch in {chapter.filename}")
        if bilingual_nums != expected:
            raise RuntimeError(f"bilingual note numbering mismatch in {chapter.filename}")
        for note in chapter.notes:
            translated = normalize_spaces(cache[note.key]["translation"])
            if not translated:
                raise RuntimeError(f"empty translation for {note.key}")


def main() -> int:
    ensure_dir(TRANSLATED_DIR)
    ensure_dir(BILINGUAL_DIR)
    chapters = load_chapters()
    cache = translate_notes(chapters)
    write_exports(chapters, cache)
    update_manifest(cache, chapters)
    update_report(chapters, cache)
    validate_exports(chapters, cache)
    print("golden exports generated successfully", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
