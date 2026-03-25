"""文本处理基础工具：HTML清理、标题提取、元数据检测。"""
import re


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

def ends_mid(text: str) -> bool:
    if not text or len(text.strip()) < 10:
        return False
    c = text.strip()[-1]
    return c not in ".;:?!»\"')"


def starts_low(text: str) -> bool:
    if not text or len(text.strip()) < 3:
        return False
    c = text.strip()[0]
    return c.islower() or c in "àâäéèêëïîôùûüÿçœæ"
