"""翻译模块：支持 DeepSeek 和 Qwen (DashScope) API。"""
import json
import re
from openai import OpenAI

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class TranslateStreamAborted(RuntimeError):
    """流式翻译被外部停止。"""


class RateLimitedError(RuntimeError):
    """请求触发限流，可等待后重试。"""

    def __init__(self, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class TransientProviderError(RuntimeError):
    """上游服务临时异常，可短暂等待后重试。"""

    def __init__(self, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class QuotaExceededError(RuntimeError):
    """额度耗尽，不应继续自动重试。"""


def _parse_retry_after_seconds(headers) -> float | None:
    if not headers:
        return None
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _extract_exc_status_headers(exc: Exception) -> tuple[int | None, dict | None]:
    status = None
    headers = None
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        headers = getattr(response, "headers", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    return status, headers


def _classify_provider_exception(exc: Exception) -> Exception:
    status, headers = _extract_exc_status_headers(exc)
    retry_after_s = _parse_retry_after_seconds(headers)
    text = str(exc or "")
    normalized = text.lower()

    if status == 429 or "rate limit" in normalized or "too many requests" in normalized:
        return RateLimitedError("触发模型限流，稍后自动重试。", retry_after_s=retry_after_s)

    quota_keywords = (
        "insufficient_quota",
        "quota exceeded",
        "quota is exceeded",
        "exceeded your current quota",
        "余额不足",
        "额度不足",
        "额度已用尽",
        "账户额度已用尽",
    )
    if status == 402 or any(keyword in normalized for keyword in quota_keywords):
        return QuotaExceededError("模型额度已耗尽，请充值或更换 API Key 后重试。")

    if status in (500, 502, 503, 504) or "timeout" in normalized or "temporarily unavailable" in normalized:
        return TransientProviderError("模型服务暂时不可用，稍后自动重试。", retry_after_s=retry_after_s)

    return exc


def _empty_usage() -> dict:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }


def _build_usage(prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int | None = None, request_count: int = 1) -> dict:
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "request_count": int(request_count or 0),
    }


def _normalize_optional_text(val) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        texts = []
        for item in val:
            if isinstance(item, dict):
                text = item.get("text", "")
            elif isinstance(item, str):
                text = item
            else:
                text = getattr(item, "text", "")
            if text:
                texts.append(str(text))
        return "".join(texts)
    return str(val)


def build_prompt(gloss_str: str, content_role: str = "body") -> str:
    lines = [
        "你是一位专业的学术文献翻译专家，擅长将外文学术论文翻译为中文。",
        "硬性要求：所有翻译结果必须使用简体中文，不得输出繁体中文。",
        "",
        "任务：校正原文，翻译为简体中文。",
        "",
        "校正规则：",
        "- 修复OCR造成的断词、多余空格、错字",
        "- 保留原文分段（用\\n\\n分隔段落）",
        "- 专有名词、人名、术语在中文翻译中首次出现时标注原文",
        "- 若术语词典给出了映射，正文出现该术语时必须优先使用词典译法，禁止换成同义词",
        "- 术语词典是硬约束：宁可句子生硬，也不要违背词典映射",
        "- 引用格式(如作者, 年份)保留原样",
        "- 如果当前段落类型是标题，只翻译标题文本本身，绝对不要吸收前后文正文",
        "- 标题段保持标题形态，不要扩写、解释或补出下一段内容",
        "",
        "重要（关于脚注）：",
        "- 正文(===正文===之间的内容)和脚注(===页面脚注===之间的内容)是严格分开的",
        "- \"original\"字段只包含正文，不要把正文内容移入脚注",
        "- \"footnotes\"字段只包含页面底部的脚注(如有)，不要把正文内容放入此字段",
        "- 脚注/尾注编号与出现顺序必须守恒，不得擅自改号、跳号、并号",
        "- 必须保留脚注标记形态（如 1. / [1] / [^1]），不要吞掉标记",
        "- 看不清的脚注宁可原样保留在footnotes，也不要并入正文或编造内容",
        "- 输入中明确标记了\"本页无脚注\"时，footnotes和footnotes_translation必须为空字符串",
        "- 绝对禁止编造、推测或从其他来源引入脚注内容",
        "- 如果你看不到任何脚注内容，就返回空字符串，不要尝试\"补充\"",
        "",
        "仅输出一个JSON对象，不要```json标记或JSON之外的文字：",
        "{",
        '  "pages": "页码",',
        '  "original": "校正后的正文原文",',
        '  "footnotes": "校正后的脚注原文，无则空字符串",',
        '  "translation": "正文的简体中文翻译(段落与原文对应)",',
        '  "footnotes_translation": "脚注的简体中文翻译，无则空字符串"',
        "}",
    ]
    if content_role == "endnote":
        lines.extend([
            "",
            "当前内容角色：尾注条目。",
            "- ===正文=== 中给出的就是单条尾注原文，不是普通正文段落。",
            "- 必须保留尾注编号、标记和顺序，不得吞号、改号、并号。",
            "- 不得把尾注改写成流畅正文或综述句，宁可保守直译。",
            "- footnotes 和 footnotes_translation 继续保持空字符串，尾注正文只写入 original/translation。",
        ])
    if gloss_str.strip():
        lines.extend([
            "",
            "术语词典（硬约束，严格按右侧译法）：",
            gloss_str,
        ])
    return "\n".join(lines)


def _trim_context_text(text: str, limit: int = 200, from_end: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[-limit:] if from_end else text[:limit]


def _build_translate_message(
    para_text: str,
    para_pages: str,
    footnotes: str,
    heading_level: int = 0,
    para_idx: int | None = None,
    para_total: int | None = None,
    prev_context: str = "",
    next_context: str = "",
    section_path: list[str] | None = None,
    cross_page: str | None = None,
    content_role: str = "body",
) -> str:
    parts = [f"页码：{para_pages}"]
    parts.append("导出契约：original=正文原文，translation=正文译文，footnotes=脚注原文，footnotes_translation=脚注译文；字段之间禁止串写")
    parts.append("脚注约束：编号与顺序必须守恒；无法确认时保留到footnotes，不得并入正文")
    parts.append(f"内容角色：{'尾注条目' if content_role == 'endnote' else '正文段落'}")
    if content_role == "endnote":
        parts.append("这是尾注条目：不得正文化，不得吞号、改号、并号，尾注内容只写入 original/translation。")
    parts.append(f"段落类型：{'标题' if heading_level > 0 else '正文'}")
    if heading_level > 0:
        parts.append(f"标题级别：H{heading_level}")

    if para_idx is not None and para_total:
        parts.append(f"段落序号：{para_idx + 1}/{para_total}")
    if section_path:
        parts.append("章节路径：" + " > ".join(str(item).strip() for item in section_path if str(item).strip()))
    if cross_page:
        parts.append(f"跨页标记：{cross_page}")

    msg = "\n".join(parts)
    if prev_context:
        msg += f"\n\n===前文原文片段===\n{_trim_context_text(prev_context, limit=200, from_end=True)}\n===前文结束==="
    msg += f"\n\n===正文===\n{para_text}\n===正文结束==="
    if next_context:
        msg += f"\n\n===后文原文片段===\n{_trim_context_text(next_context, limit=200, from_end=False)}\n===后文结束==="
    if footnotes:
        msg += f"\n\n===页面脚注===\n{footnotes}\n===页面脚注结束==="
    else:
        msg += "\n\n===页面脚注===\n本页无脚注\n===页面脚注结束==="
    return msg


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in re.split(r"\n+", str(text or "")) if line.strip()]


def _normalize_translation_text(translation: str, para_text: str, heading_level: int = 0) -> str:
    translation = str(translation or "").strip()
    if heading_level <= 0 or not translation:
        return translation
    source_lines = _nonempty_lines(para_text)
    translated_lines = _nonempty_lines(translation)
    if not source_lines or not translated_lines:
        return translation
    max_lines = max(1, len(source_lines))
    return "\n".join(translated_lines[:max_lines]).strip()


def _collect_required_glossary(para_text: str, glossary: list) -> list[tuple[str, str]]:
    source = str(para_text or "")
    required: list[tuple[str, str]] = []
    seen = set()
    for item in glossary or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        term = str(item[0] or "").strip()
        defn = str(item[1] or "").strip()
        if not term or not defn:
            continue
        key = term.lower()
        if key in seen:
            continue
        if re.search(re.escape(term), source, flags=re.IGNORECASE):
            required.append((term, defn))
            seen.add(key)
    return required


def _missing_glossary_defs(translation: str, required: list[tuple[str, str]]) -> list[tuple[str, str]]:
    tgt = str(translation or "")
    return [(term, defn) for term, defn in required if defn not in tgt]


def _enforce_glossary_rewrite(
    translation: str,
    para_text: str,
    required: list[tuple[str, str]],
    model_id: str,
    api_key: str,
    provider: str,
    base_url: str | None = None,
    request_overrides: dict | None = None,
) -> str:
    if not required:
        return translation
    required_text = "\n".join(f"- {term} => {defn}" for term, defn in required)
    sys_prompt = (
        "你是术语校对助手。任务：只改写给定中文译文中的术语用法，其他语义和结构尽量保持不变。"
        "必须使用指定术语映射，且输出必须是简体中文。"
        "不要输出解释，不要Markdown，不要JSON，只输出改写后的简体中文译文正文。"
    )
    user_msg = (
        "请按以下术语硬约束改写译文：\n"
        f"{required_text}\n\n"
        f"原文片段：\n{para_text}\n\n"
        f"当前译文：\n{translation}"
    )
    try:
        revised = _call_provider(
            provider,
            sys_prompt,
            user_msg,
            model_id,
            api_key,
            base_url=base_url,
            request_overrides=request_overrides,
        ).get("text", "").strip()
        return revised or translation
    except Exception:
        return translation


def parse_json_response(text: str) -> dict | None:
    """尝试从 API 返回文本中解析 JSON。"""
    if not text:
        return None
    s = re.sub(r"```json\s*", "", text)
    s = re.sub(r"```\s*", "", s).strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # find outermost {}
    depth = 0
    start = -1
    end = -1
    for i, c in enumerate(s):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        if c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if start == -1 or end == -1:
        return None

    sub = s[start : end + 1]
    try:
        return json.loads(sub)
    except json.JSONDecodeError:
        pass

    # fix unescaped newlines
    try:
        fixed = re.sub(
            r'"([^"]*?)"',
            lambda m: '"' + m.group(1).replace("\n", "\\n").replace("\r", "").replace("\t", "\\t") + '"',
            sub,
        )
        return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
        pass

    return None


def _decode_json_string_prefix(text: str) -> tuple[str, bool]:
    """解码 JSON 字符串前缀，允许末尾存在未闭合或未完成的转义。"""
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            return "".join(out), True
        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        i += 1
        if i >= len(text):
            break
        esc = text[i]
        mapping = {
            '"': '"',
            "\\": "\\",
            "/": "/",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        if esc == "u":
            if i + 4 >= len(text):
                break
            hex_part = text[i + 1:i + 5]
            if not re.fullmatch(r"[0-9a-fA-F]{4}", hex_part):
                break
            out.append(chr(int(hex_part, 16)))
            i += 5
            continue
        if esc in mapping:
            out.append(mapping[esc])
            i += 1
            continue
        out.append(esc)
        i += 1
    return "".join(out), False


def _extract_translation_preview(text: str) -> str:
    """从可能未完成的 JSON 文本中提取 translation 字段已生成的可见内容。"""
    if not text:
        return ""
    match = re.search(r'"translation"\s*:\s*"', text)
    if not match:
        return ""
    decoded, _closed = _decode_json_string_prefix(text[match.end():])
    return decoded


def _extract_openai_message_text(message_content) -> str:
    if isinstance(message_content, str):
        return message_content
    return _normalize_optional_text(message_content)


def _call_openai_chat(base_url: str, sys_prompt: str, user_msg: str, model_id: str, api_key: str, request_overrides: dict | None = None) -> dict:
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    create_kwargs = {
        "model": model_id,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ],
    }
    if isinstance(request_overrides, dict):
        create_kwargs.update(request_overrides)
    try:
        response = client.chat.completions.create(**create_kwargs)
    except Exception as exc:
        raise _classify_provider_exception(exc) from exc
    usage = _build_usage(
        prompt_tokens=getattr(response.usage, "prompt_tokens", 0),
        completion_tokens=getattr(response.usage, "completion_tokens", 0),
        total_tokens=getattr(response.usage, "total_tokens", None),
    )
    if response.choices and getattr(response.choices[0], "message", None):
        content = _extract_openai_message_text(getattr(response.choices[0].message, "content", ""))
        return {"text": content, "usage": usage}
    return {"text": "", "usage": usage}


def _call_provider(
    provider: str,
    sys_prompt: str,
    user_msg: str,
    model_id: str,
    api_key: str,
    base_url: str | None = None,
    request_overrides: dict | None = None,
) -> dict:
    resolved_base_url = base_url or (DASHSCOPE_BASE_URL if provider == "qwen" else DEEPSEEK_BASE_URL)
    return _call_openai_chat(
        resolved_base_url,
        sys_prompt,
        user_msg,
        model_id,
        api_key,
        request_overrides=request_overrides,
    )


def _parse_json_array(text: str) -> list | None:
    """从 API 返回中提取 JSON 数组。"""
    if not text:
        return None
    s = re.sub(r"```json\s*", "", text)
    s = re.sub(r"```\s*", "", s).strip()

    try:
        r = json.loads(s)
        if isinstance(r, list):
            return r
    except json.JSONDecodeError:
        pass

    # find outermost []
    depth = 0
    start = -1
    end = -1
    for i, c in enumerate(s):
        if c == "[":
            if depth == 0:
                start = i
            depth += 1
        if c == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if start >= 0 and end > start:
        try:
            r = json.loads(s[start:end + 1])
            if isinstance(r, list):
                return r
        except json.JSONDecodeError:
            pass

    return None


def _check_stream_stop(stop_checker):
    if stop_checker and stop_checker():
        raise TranslateStreamAborted("用户停止流式翻译")


def _close_stream_response(response):
    if response and hasattr(response, "close"):
        try:
            response.close()
        except Exception:
            pass


def _extract_openai_delta_text(chunk) -> str:
    if not getattr(chunk, "choices", None):
        return ""
    delta = getattr(chunk.choices[0], "delta", None)
    if delta is None:
        return ""
    content = getattr(delta, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", "")
            else:
                text = getattr(item, "text", "")
            if text:
                texts.append(text)
        return "".join(texts)
    return ""


def _stream_openai_chat(
    base_url: str,
    sys_prompt: str,
    user_msg: str,
    model_id: str,
    api_key: str,
    stop_checker=None,
    request_overrides: dict | None = None,
):
    """OpenAI 兼容接口流式文本输出。"""
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    create_kwargs = {
        "model": model_id,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if isinstance(request_overrides, dict):
        create_kwargs.update(request_overrides)
    try:
        response = client.chat.completions.create(**create_kwargs)
    except Exception as exc:
        raise _classify_provider_exception(exc) from exc
    full_parts = []
    usage = _empty_usage()
    try:
        try:
            for chunk in response:
                _check_stream_stop(stop_checker)
                text = _extract_openai_delta_text(chunk)
                if text:
                    full_parts.append(text)
                    yield {"type": "delta", "text": text}
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    usage = _build_usage(
                        prompt_tokens=getattr(chunk_usage, "prompt_tokens", 0),
                        completion_tokens=getattr(chunk_usage, "completion_tokens", 0),
                        total_tokens=getattr(chunk_usage, "total_tokens", None),
                    )
            full_text = "".join(full_parts)
            yield {"type": "usage", "usage": usage}
            yield {"type": "done", "text": full_text, "usage": usage}
        except Exception as exc:
            raise _classify_provider_exception(exc) from exc
    except TranslateStreamAborted:
        _close_stream_response(response)
        raise
    finally:
        _close_stream_response(response)


def _stream_provider(
    provider: str,
    sys_prompt: str,
    user_msg: str,
    model_id: str,
    api_key: str,
    stop_checker=None,
    base_url: str | None = None,
    request_overrides: dict | None = None,
):
    resolved_base_url = base_url or (DASHSCOPE_BASE_URL if provider == "qwen" else DEEPSEEK_BASE_URL)
    return _stream_openai_chat(
        resolved_base_url,
        sys_prompt,
        user_msg,
        model_id,
        api_key,
        stop_checker=stop_checker,
        request_overrides=request_overrides,
    )


_STRUCTURE_SYSTEM = """你是文档结构分析专家。

任务：将OCR得到的一页学术文献文本整理为正确的段落结构。

输入说明：
- ===连续文本=== 是该页OCR渲染的markdown文本，文字内容和顺序基本正确。其中 # 标记表示OCR识别出的标题层级。
- [上一页末尾] 和 [下一页开头] 是相邻页的片段，帮助你判断跨页段落。
- ===OCR标签=== 是版面分析的标签信息，仅供参考（文本可能不准确，不要使用其中的文本内容）。

处理规则：
1. 文本来源：只使用 ===连续文本=== 中 [当前页] 部分的文字。不要使用OCR标签中的文字。
2. 去除元数据：删除DOI、URL、版权©、期刊名、"Article reuse guidelines"、"SAGE"等非正文内容。
3. 标题识别：markdown中的 # 标记指示标题。# = heading_level 1, ## = 2, ### = 3, 等等。将标题文本完整保留。
4. 段落划分：正文按照语义段落划分（heading_level=0）。每个段落是一个完整的语义单元。
5. 跨页处理：
   - 如果当前页开头的文字明显是承接上一页的（参考[上一页末尾]的内容），在该段文本开头标注 [承上页]
   - 如果当前页末尾的段落被截断（参考[下一页开头]的内容），在该段文本末尾标注 [续下页]
6. 通讯作者/邮箱：如果出现 "Corresponding author"、邮箱地址等，单独一项，heading_level=-1（表示脚注，不翻译）。
7. 保持完整：每个段落的文本必须是完整的，从 ===连续文本=== 中原样复制，不可截断或省略。
8. 脚注/尾注保真：
   - 遇到 NOTES/Notes/注释/尾注 及其编号条目（如 "1."、"[1]"、"12 "）时，必须保持原有编号顺序，不得重排。
   - 不得把脚注/尾注条目并入普通正文段落；脚注区应独立成段输出。
   - 对看不清或疑似噪声的脚注行，宁可原样保留，也不要改写成正文语句。
9. 编号守恒：页面内已有的脚注/尾注编号及标记（数字、方括号、上标语义）必须尽量原样保留，不得擅自增删编号。

输出：仅JSON数组，不加任何标记：
[
  {"heading_level": 1, "text": "论文完整标题"},
  {"heading_level": 0, "text": "第一个完整正文段落的全部文字..."},
  {"heading_level": 2, "text": "章节标题"},
  {"heading_level": 0, "text": "该章节第一个完整段落的全部文字..."},
  {"heading_level": -1, "text": "Corresponding author: ..."}
]"""

_NOTE_REVIEW_SYSTEM = """你是学术文献的脚注/尾注结构校对助手。

任务：只根据当前页文本，判断这一页是否包含页面脚注或章节尾注，并输出结构化结果。

规则：
1. 只处理当前页，不补全其他页内容。
2. 保留原有编号、标记和顺序，不得改号、并号、跳号。
3. 允许输出 page_kind 为：
   - body
   - body_with_page_footnotes
   - endnote_collection
   - mixed_body_endnotes
4. items 里每条必须包含：
   - kind: footnote 或 endnote
   - marker: 如 1. / [1]
   - number: 数字编号，没有则 null
   - text: 当前页可见的完整条目文本
   - order: 当前页内顺序，从 1 开始
   - confidence: 0 到 1
   - section_title: 该条尾注所属的小节/章节标题，没有则空字符串
5. 如果无法可靠识别，就减少 items，并把原因放进 ambiguity_flags。
6. 只输出一个 JSON 对象，不要输出额外解释。
"""


def structure_page(
    blocks: list,
    markdown: str,
    model_id: str,
    api_key: str,
    provider: str = "deepseek",
    base_url: str | None = None,
    request_overrides: dict | None = None,
    page_num: int = 0,
) -> dict:
    """
    用 LLM 分析页面结构，返回正确的段落列表。

    Args:
        blocks: OCR blocks 列表 [{"label", "text", ...}]
        markdown: 上下文 markdown（含前后页片段）
        model_id: LLM model id
        api_key: API key
        provider: "deepseek" 或 "qwen"
        page_num: 当前页码

    Returns:
        [{"heading_level": int, "text": str}, ...]
    """
    # 仅传标签信息（标签+文本前20字），不传完整文本，避免误导 LLM
    label_lines = []
    for i, b in enumerate(blocks):
        label = b.get("label", "text")
        text = b.get("text", "").strip()
        if len(text) < 2:
            continue
        preview = text[:30] + "..." if len(text) > 30 else text
        label_lines.append(f"[{i}] {label}: \"{preview}\"")

    labels_str = "\n".join(label_lines) if label_lines else "(无标签信息)"

    # 构建用户消息
    msg = f"页码: {page_num}\n\n===OCR标签===\n{labels_str}\n===OCR标签结束===\n\n===连续文本===\n{markdown}\n===连续文本结束==="

    api_result = _call_provider(
        provider,
        _STRUCTURE_SYSTEM,
        msg,
        model_id,
        api_key,
        base_url=base_url,
        request_overrides=request_overrides,
    )

    full = api_result.get("text", "")
    if not full:
        return {"paragraphs": [], "usage": api_result.get("usage", _empty_usage())}

    items = _parse_json_array(full)
    if not items:
        return {"paragraphs": [], "usage": api_result.get("usage", _empty_usage())}

    # 验证和清理
    clean = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if len(text) < 2:
            continue
        hl = int(item.get("heading_level", 0))
        if hl < -1 or hl > 6:
            hl = 0
        clean.append({"heading_level": hl, "text": text})

    return {"paragraphs": clean, "usage": api_result.get("usage", _empty_usage())}


def review_note_page(
    markdown: str,
    footnotes: str,
    page_num: int,
    model_id: str,
    api_key: str,
    provider: str = "deepseek",
    base_url: str | None = None,
    request_overrides: dict | None = None,
    prev_context: str = "",
    next_context: str = "",
    rule_scan: dict | None = None,
) -> dict:
    rule_json = json.dumps(rule_scan or {}, ensure_ascii=False)
    msg = (
        f"页码: {page_num}\n\n"
        f"===规则初判===\n{rule_json}\n===规则初判结束===\n\n"
        f"===当前页文本===\n{markdown or ''}\n===当前页文本结束===\n\n"
        f"===页面脚注字段===\n{footnotes or '本页无脚注'}\n===页面脚注字段结束===\n\n"
        f"===上一页末尾===\n{prev_context or ''}\n===上一页末尾结束===\n\n"
        f"===下一页开头===\n{next_context or ''}\n===下一页开头结束==="
    )
    api_result = _call_provider(
        provider,
        _NOTE_REVIEW_SYSTEM,
        msg,
        model_id,
        api_key,
        base_url=base_url,
        request_overrides=request_overrides,
    )
    payload = parse_json_response(api_result.get("text", ""))
    if not isinstance(payload, dict):
        return {}
    normalized_items = []
    for idx, item in enumerate(payload.get("items") or [], 1):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip()
        text = str(item.get("text", "")).strip()
        if kind not in {"footnote", "endnote"} or not text:
            continue
        number = item.get("number")
        try:
            number = int(number) if number is not None else None
        except (TypeError, ValueError):
            number = None
        normalized_items.append({
            "kind": kind,
            "marker": str(item.get("marker", "")).strip(),
            "number": number,
            "text": text,
            "order": int(item.get("order", idx) or idx),
            "source": "model_review",
            "confidence": float(item.get("confidence", 0.75) or 0.75),
            "section_title": str(item.get("section_title", "")).strip(),
        })
    return {
        "page_kind": str(payload.get("page_kind", "body")).strip() or "body",
        "items": normalized_items,
        "section_hints": [
            str(item).strip()
            for item in (payload.get("section_hints") or [])
            if str(item).strip()
        ],
        "ambiguity_flags": [
            str(item).strip()
            for item in (payload.get("ambiguity_flags") or [])
            if str(item).strip()
        ],
    }


def _prepare_translate_request(
    para_text: str,
    para_pages: str,
    footnotes: str,
    glossary: list,
    heading_level: int = 0,
    para_idx: int | None = None,
    para_total: int | None = None,
    prev_context: str = "",
    next_context: str = "",
    section_path: list[str] | None = None,
    cross_page: str | None = None,
    content_role: str = "body",
) -> tuple[str, str]:
    gloss_str = "\n".join(f"{g[0]}→{g[1]}" for g in glossary)
    sys_prompt = build_prompt(gloss_str, content_role=content_role)
    msg = _build_translate_message(
        para_text=para_text,
        para_pages=para_pages,
        footnotes=footnotes,
        heading_level=heading_level,
        para_idx=para_idx,
        para_total=para_total,
        prev_context=prev_context,
        next_context=next_context,
        section_path=section_path,
        cross_page=cross_page,
        content_role=content_role,
    )
    return sys_prompt, msg


def translate_paragraph(
    para_text: str,
    para_pages: str,
    footnotes: str,
    glossary: list,
    model_id: str,
    api_key: str,
    provider: str = "deepseek",
    base_url: str | None = None,
    request_overrides: dict | None = None,
    heading_level: int = 0,
    para_idx: int | None = None,
    para_total: int | None = None,
    prev_context: str = "",
    next_context: str = "",
    section_path: list[str] | None = None,
    cross_page: str | None = None,
    content_role: str = "body",
) -> dict:
    """
    翻译一个段落。

    Args:
        provider: "deepseek" 或 "qwen"

    Returns:
        包含 pages, original, translation, footnotes, footnotes_translation 的字典
    """
    sys_prompt, msg = _prepare_translate_request(
        para_text=para_text,
        para_pages=para_pages,
        footnotes=footnotes,
        glossary=glossary,
        heading_level=heading_level,
        para_idx=para_idx,
        para_total=para_total,
        prev_context=prev_context,
        next_context=next_context,
        section_path=section_path,
        cross_page=cross_page,
        content_role=content_role,
    )

    result = _call_provider(
        provider,
        sys_prompt,
        msg,
        model_id,
        api_key,
        base_url=base_url,
        request_overrides=request_overrides,
    )

    full = result.get("text", "")
    if not full:
        raise RuntimeError("API返回空内容")

    p = parse_json_response(full)
    if not p:
        p = {
            "pages": para_pages,
            "original": para_text,
            "translation": full,
            "footnotes": footnotes,
            "footnotes_translation": "",
        }
    if not p.get("pages"):
        p["pages"] = para_pages
    if p.get("original"):
        p["original"] = re.sub(r"^>\s*", "", p["original"], flags=re.MULTILINE).strip()
    p["footnotes"] = _normalize_optional_text(p.get("footnotes", "")).strip() or _normalize_optional_text(footnotes).strip()
    p["footnotes_translation"] = _normalize_optional_text(p.get("footnotes_translation", "")).strip()
    p["translation"] = _normalize_translation_text(p.get("translation", ""), para_text, heading_level=heading_level)
    required_glossary = _collect_required_glossary(para_text, glossary)
    missing_defs = _missing_glossary_defs(p["translation"], required_glossary)
    if missing_defs:
        revised = _enforce_glossary_rewrite(
            translation=p["translation"],
            para_text=para_text,
            required=missing_defs,
            model_id=model_id,
            api_key=api_key,
            provider=provider,
            base_url=base_url,
            request_overrides=request_overrides,
        )
        p["translation"] = _normalize_translation_text(revised, para_text, heading_level=heading_level)
    p["_usage"] = result.get("usage", _empty_usage())

    return p


def stream_translate_paragraph(
    para_text: str,
    para_pages: str,
    footnotes: str,
    glossary: list,
    model_id: str,
    api_key: str,
    provider: str = "deepseek",
    stop_checker=None,
    base_url: str | None = None,
    request_overrides: dict | None = None,
    heading_level: int = 0,
    para_idx: int | None = None,
    para_total: int | None = None,
    prev_context: str = "",
    next_context: str = "",
    section_path: list[str] | None = None,
    cross_page: str | None = None,
    content_role: str = "body",
):
    """
    流式翻译一个段落。

    事件类型：
    - {"type": "delta", "text": "..."}
    - {"type": "usage", "usage": {...}}
    - {"type": "done", "text": full_text, "usage": {...}, "result": {...}}
    """
    sys_prompt, msg = _prepare_translate_request(
        para_text=para_text,
        para_pages=para_pages,
        footnotes=footnotes,
        glossary=glossary,
        heading_level=heading_level,
        para_idx=para_idx,
        para_total=para_total,
        prev_context=prev_context,
        next_context=next_context,
        section_path=section_path,
        cross_page=cross_page,
        content_role=content_role,
    )

    stream_iter = _stream_provider(
        provider,
        sys_prompt,
        msg,
        model_id,
        api_key,
        stop_checker=stop_checker,
        base_url=base_url,
        request_overrides=request_overrides,
    )

    final_usage = _empty_usage()
    raw_stream_text = ""
    streamed_preview = ""
    for event in stream_iter:
        if event["type"] == "usage":
            final_usage = event.get("usage", _empty_usage())
            yield event
            continue
        if event["type"] == "delta":
            raw_stream_text += event.get("text", "")
            preview = _normalize_translation_text(
                _extract_translation_preview(raw_stream_text),
                para_text,
                heading_level=heading_level,
            )
            if len(preview) > len(streamed_preview):
                delta_text = preview[len(streamed_preview):]
                streamed_preview = preview
                yield {"type": "delta", "text": delta_text}
            continue
        if event["type"] != "done":
            yield event
            continue

        full = event.get("text", "")
        if not full:
            raise RuntimeError("API返回空内容")

        p = parse_json_response(full)
        if not p:
            p = {
                "pages": para_pages,
                "original": para_text,
                "translation": full,
                "footnotes": footnotes,
                "footnotes_translation": "",
            }
        if not p.get("pages"):
            p["pages"] = para_pages
        if p.get("original"):
            p["original"] = re.sub(r"^>\s*", "", p["original"], flags=re.MULTILINE).strip()
        p["footnotes"] = _normalize_optional_text(p.get("footnotes", "")).strip() or _normalize_optional_text(footnotes).strip()
        p["footnotes_translation"] = _normalize_optional_text(p.get("footnotes_translation", "")).strip()
        p["translation"] = _normalize_translation_text(p.get("translation", ""), para_text, heading_level=heading_level)
        required_glossary = _collect_required_glossary(para_text, glossary)
        missing_defs = _missing_glossary_defs(p["translation"], required_glossary)
        if missing_defs:
            revised = _enforce_glossary_rewrite(
                translation=p["translation"],
                para_text=para_text,
                required=missing_defs,
                model_id=model_id,
                api_key=api_key,
                provider=provider,
                base_url=base_url,
                request_overrides=request_overrides,
            )
            p["translation"] = _normalize_translation_text(revised, para_text, heading_level=heading_level)
        p["_usage"] = final_usage

        yield {
            "type": "done",
            "text": full,
            "usage": final_usage,
            "result": p,
        }
