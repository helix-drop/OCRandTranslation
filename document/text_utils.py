"""文本处理基础工具：HTML清理、标题提取、元数据检测、类型安全。"""
import re


def ensure_str(val) -> str:
    """确保值为字符串（API有时返回列表）。"""
    if val is None:
        return ""
    if isinstance(val, list):
        return "\n".join(str(v) for v in val)
    return str(val)


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def extract_heading_level(s: str) -> tuple[int, str]:
    """提取 markdown 标题层级和纯文本。

    Returns:
        (heading_level, clean_text)
        heading_level: 0=正文, 1=一级标题, 2=二级, ... 6=六级
    """
    m = re.match(r"^(#{1,6})\s+", s)
    if m:
        level = len(m.group(1))
        clean = s[m.end():].strip()
        return level, clean
    return 0, s.strip()


# ============ 元数据与噪音过滤 ============

# 元数据行正则（逐行检测）
_META_LINE_RE = [
    re.compile(r"^https?://", re.I),
    re.compile(r"^doi:\s*10\.", re.I),
    re.compile(r"^10\.\d{4,}/"),
    re.compile(r"sagepub\.com|journals\.sagepub|springer\.com|wiley\.com", re.I),
    re.compile(r"©.*\d{4}"),
    re.compile(r"^article\s*reuse\s*guidelines", re.I),
    re.compile(r"^SAGE$", re.I),
    re.compile(r"^Article$", re.I),
    re.compile(r"^\d{1,4}[–\-]\d{1,4}$"),  # "1–14"
    re.compile(r"^Vol\.\s*\d+", re.I),
    re.compile(r"^Accepted:|^Received:|^Published:", re.I),
    re.compile(r"^Corresponding\s+author", re.I),
    re.compile(r"^(E-?mail:\s*)?\S+@\S+\.\S+$", re.I),
]

# 期刊名模式（单独检测短行）
_JOURNAL_RE = re.compile(
    r"^(History|Journal|Annals|Bulletin|Review|Archives|Proceedings|"
    r"Quarterly|American|British|European|International)\s+(of|for)\s+\w+",
    re.I,
)


def _is_meta_line(line: str) -> bool:
    """判断单行文本是否为元数据。"""
    t = line.strip()
    if len(t) < 2:
        return True
    for pat in _META_LINE_RE:
        if pat.search(t):
            return True
    # 短行期刊名
    if len(t) < 60 and _JOURNAL_RE.match(t):
        return True
    return False


def _is_metadata(text: str) -> bool:
    """判断文本块是否为纯元数据（兼容旧接口）。"""
    return _is_meta_line(text)


# ============ 句子边界判断 ============

# Unicode 上标数字（脚注常见），如 ⁶⁹、⁷⁰
_SUPERSCRIPT_DIGITS_RE = re.compile(
    r"[\u2070\u00B9\u00B2\u00B3\u2074\u2075\u2076\u2077\u2078\u2079]+$"
)
# 行末方括号脚注，如 [70]、[^70]
_BRACKET_FOOTNOTE_TAIL_RE = re.compile(r"\[\^?\d{1,4}\]\s*$", re.I)
# LaTeX \textsuperscript{n}
_TEXTSUPERSCRIPT_TAIL_RE = re.compile(r"\\textsuperscript\{\d+\}\s*$", re.I)
_SENTENCE_END_RE = re.compile(r"[.;:?!。；：！？»\"'\u201d\u00bb)\]]\s*$")
_CONTINUATION_PREFIX_CHARS = ",.;:!?)]}\"'，。；：！？、）》】」』”’"


def strip_trailing_footnote_markers(text: str) -> str:
    """去掉句末脚注/上标标记，便于判断「真实」句末标点。

    学术 PDF OCR 常在句末带上标 ⁶⁹ 等；若不去掉，`ends_mid` 会把上标当成非句末字符而误判为「句中断」，
    进而触发跨页链式合并 (merged_next)。
    """
    s = text.rstrip()
    while s:
        prev_len = len(s)
        m = _SUPERSCRIPT_DIGITS_RE.search(s)
        if m and m.end() == len(s):
            s = s[: m.start()].rstrip()
            continue
        m = _BRACKET_FOOTNOTE_TAIL_RE.search(s)
        if m and m.end() == len(s):
            s = s[: m.start()].rstrip()
            continue
        m = _TEXTSUPERSCRIPT_TAIL_RE.search(s)
        if m and m.end() == len(s):
            s = s[: m.start()].rstrip()
            continue
        if len(s) == prev_len:
            break
    return s


def has_explicit_sentence_end(text: str) -> bool:
    """判断文本在剥离脚注尾标后，是否带有明确句终信号。"""
    core = strip_trailing_footnote_markers((text or "").strip())
    if not core:
        return False
    return bool(_SENTENCE_END_RE.search(core))


def ends_mid(text: str) -> bool:
    if not text or len(text.strip()) < 10:
        return False
    core = strip_trailing_footnote_markers(text.strip())
    if len(core) < 10:
        return False
    return not has_explicit_sentence_end(core)


def starts_low(text: str) -> bool:
    if not text or len(text.strip()) < 3:
        return False
    c = text.strip()[0]
    return c.islower() or c in "àâäéèêëïîôùûüÿçœæ"


def starts_with_continuation_punctuation(text: str) -> bool:
    stripped = (text or "").lstrip()
    return bool(stripped) and stripped[0] in _CONTINUATION_PREFIX_CHARS


def is_mid_sentence_continuation(
    prev_text: str,
    next_text: str,
    *,
    allow_uppercase: bool = False,
) -> bool:
    """判断 next_text 是否像是 prev_text 跨页后的续句。"""
    prev = (prev_text or "").rstrip()
    nxt = (next_text or "").lstrip()
    if not prev or not nxt:
        return False
    if prev.endswith("-"):
        return True
    if not ends_mid(prev):
        return False
    if starts_low(nxt) or starts_with_continuation_punctuation(nxt):
        return True
    if allow_uppercase and nxt[0].isupper() and not has_explicit_sentence_end(prev):
        return True
    return False
