"""翻译模块：支持 Anthropic Claude 和 Qwen (DashScope) API。"""
import json
import re

import anthropic
from openai import OpenAI

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class TranslateStreamAborted(RuntimeError):
    """流式翻译被外部停止。"""


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


def build_prompt(gloss_str: str) -> str:
    lines = [
        "你是一位专业的学术文献翻译专家，擅长将外文学术论文翻译为中文。",
        "",
        "任务：校正原文，翻译为中文。",
        "",
        "校正规则：",
        "- 修复OCR造成的断词、多余空格、错字",
        "- 保留原文分段（用\\n\\n分隔段落）",
        "- 专有名词、人名、术语在中文翻译中首次出现时标注原文",
        "- 引用格式(如作者, 年份)保留原样",
        "",
        "重要（关于脚注）：",
        "- 正文(===正文===之间的内容)和脚注(===页面脚注===之间的内容)是严格分开的",
        "- \"original\"字段只包含正文，不要把正文内容移入脚注",
        "- \"footnotes\"字段只包含页面底部的脚注(如有)，不要把正文内容放入此字段",
        "- 输入中明确标记了\"本页无脚注\"时，footnotes和footnotes_translation必须为空字符串",
        "- 绝对禁止编造、推测或从其他来源引入脚注内容",
        "- 如果你看不到任何脚注内容，就返回空字符串，不要尝试\"补充\"",
        "",
        "仅输出一个JSON对象，不要```json标记或JSON之外的文字：",
        "{",
        '  "pages": "页码",',
        '  "original": "校正后的正文原文",',
        '  "footnotes": "校正后的脚注原文，无则空字符串",',
        '  "translation": "正文的中文翻译(段落与原文对应)",',
        '  "footnotes_translation": "脚注的中文翻译，无则空字符串"',
        "}",
    ]
    if gloss_str.strip():
        lines.extend(["", "术语词典：", gloss_str])
    return "\n".join(lines)


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


def _call_anthropic(sys_prompt: str, user_msg: str, model_id: str, api_key: str) -> dict:
    """调用 Anthropic Claude API。"""
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model_id,
        max_tokens=4096,
        system=sys_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    full = ""
    for block in response.content:
        if block.type == "text":
            full += block.text
    usage = _build_usage(
        prompt_tokens=getattr(response.usage, "input_tokens", 0),
        completion_tokens=getattr(response.usage, "output_tokens", 0),
    )
    return {"text": full, "usage": usage}


def _call_qwen(sys_prompt: str, user_msg: str, model_id: str, api_key: str) -> dict:
    """调用 Qwen (DashScope) API，使用 OpenAI 兼容接口。"""
    client = OpenAI(
        api_key=api_key,
        base_url=DASHSCOPE_BASE_URL,
    )
    response = client.chat.completions.create(
        model=model_id,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ],
    )
    usage = _build_usage(
        prompt_tokens=getattr(response.usage, "prompt_tokens", 0),
        completion_tokens=getattr(response.usage, "completion_tokens", 0),
        total_tokens=getattr(response.usage, "total_tokens", None),
    )
    if response.choices and response.choices[0].message.content:
        return {"text": response.choices[0].message.content, "usage": usage}
    return {"text": "", "usage": usage}


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


def _stream_anthropic(sys_prompt: str, user_msg: str, model_id: str, api_key: str, stop_checker=None):
    """Anthropic 流式文本输出。"""
    client = anthropic.Anthropic(api_key=api_key)
    full_parts = []
    stream = None
    try:
        stream = client.messages.stream(
            model=model_id,
            max_tokens=4096,
            system=sys_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        with stream as response:
            for text in response.text_stream:
                _check_stream_stop(stop_checker)
                if not text:
                    continue
                full_parts.append(text)
                yield {"type": "delta", "text": text}
            final_message = response.get_final_message()
        usage = _build_usage(
            prompt_tokens=getattr(getattr(final_message, "usage", None), "input_tokens", 0),
            completion_tokens=getattr(getattr(final_message, "usage", None), "output_tokens", 0),
        )
        full_text = "".join(full_parts)
        yield {"type": "usage", "usage": usage}
        yield {"type": "done", "text": full_text, "usage": usage}
    except TranslateStreamAborted:
        _close_stream_response(stream)
        raise


def _stream_qwen(sys_prompt: str, user_msg: str, model_id: str, api_key: str, stop_checker=None):
    """Qwen/OpenAI 兼容接口流式文本输出。"""
    client = OpenAI(
        api_key=api_key,
        base_url=DASHSCOPE_BASE_URL,
    )
    response = client.chat.completions.create(
        model=model_id,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ],
        stream=True,
        stream_options={"include_usage": True},
    )
    full_parts = []
    usage = _empty_usage()
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
    except TranslateStreamAborted:
        _close_stream_response(response)
        raise
    finally:
        _close_stream_response(response)


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

输出：仅JSON数组，不加任何标记：
[
  {"heading_level": 1, "text": "论文完整标题"},
  {"heading_level": 0, "text": "第一个完整正文段落的全部文字..."},
  {"heading_level": 2, "text": "章节标题"},
  {"heading_level": 0, "text": "该章节第一个完整段落的全部文字..."},
  {"heading_level": -1, "text": "Corresponding author: ..."}
]"""


def structure_page(
    blocks: list,
    markdown: str,
    model_id: str,
    api_key: str,
    provider: str = "anthropic",
    page_num: int = 0,
) -> dict:
    """
    用 LLM 分析页面结构，返回正确的段落列表。

    Args:
        blocks: OCR blocks 列表 [{"label", "text", ...}]
        markdown: 上下文 markdown（含前后页片段）
        model_id: LLM model id
        api_key: API key
        provider: "anthropic" 或 "qwen"
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

    if provider == "qwen":
        api_result = _call_qwen(_STRUCTURE_SYSTEM, msg, model_id, api_key)
    else:
        api_result = _call_anthropic(_STRUCTURE_SYSTEM, msg, model_id, api_key)

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


def translate_paragraph(
    para_text: str,
    para_pages: str,
    footnotes: str,
    glossary: list,
    model_id: str,
    api_key: str,
    provider: str = "anthropic",
) -> dict:
    """
    翻译一个段落。

    Args:
        provider: "anthropic" 或 "qwen"

    Returns:
        包含 pages, original, translation, footnotes, footnotes_translation 的字典
    """
    gloss_str = "\n".join(f"{g[0]}→{g[1]}" for g in glossary)
    sys_prompt = build_prompt(gloss_str)

    msg = f"页码：{para_pages}\n\n===正文===\n{para_text}\n===正文结束==="
    if footnotes:
        msg += f"\n\n===页面脚注===\n{footnotes}\n===页面脚注结束==="
    else:
        msg += "\n\n===页面脚注===\n本页无脚注\n===页面脚注结束==="

    if provider == "qwen":
        result = _call_qwen(sys_prompt, msg, model_id, api_key)
    else:
        result = _call_anthropic(sys_prompt, msg, model_id, api_key)

    full = result.get("text", "")
    if not full:
        raise RuntimeError("API返回空内容")

    p = parse_json_response(full)
    if not p:
        p = {
            "pages": para_pages,
            "original": para_text,
            "translation": full,
            "footnotes": "",
            "footnotes_translation": "",
        }
    if not p.get("pages"):
        p["pages"] = para_pages
    if p.get("original"):
        p["original"] = re.sub(r"^>\s*", "", p["original"], flags=re.MULTILINE).strip()
    p["_usage"] = result.get("usage", _empty_usage())

    return p


def stream_translate_paragraph(
    para_text: str,
    para_pages: str,
    footnotes: str,
    glossary: list,
    model_id: str,
    api_key: str,
    provider: str = "anthropic",
    stop_checker=None,
):
    """
    流式翻译一个段落。

    事件类型：
    - {"type": "delta", "text": "..."}
    - {"type": "usage", "usage": {...}}
    - {"type": "done", "text": full_text, "usage": {...}, "result": {...}}
    """
    gloss_str = "\n".join(f"{g[0]}→{g[1]}" for g in glossary)
    sys_prompt = build_prompt(gloss_str)

    msg = f"页码：{para_pages}\n\n===正文===\n{para_text}\n===正文结束==="
    if footnotes:
        msg += f"\n\n===页面脚注===\n{footnotes}\n===页面脚注结束==="
    else:
        msg += "\n\n===页面脚注===\n本页无脚注\n===页面脚注结束==="

    if provider == "qwen":
        stream_iter = _stream_qwen(sys_prompt, msg, model_id, api_key, stop_checker=stop_checker)
    else:
        stream_iter = _stream_anthropic(sys_prompt, msg, model_id, api_key, stop_checker=stop_checker)

    final_usage = _empty_usage()
    for event in stream_iter:
        if event["type"] == "usage":
            final_usage = event.get("usage", _empty_usage())
            yield event
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
                "footnotes": "",
                "footnotes_translation": "",
            }
        if not p.get("pages"):
            p["pages"] = para_pages
        if p.get("original"):
            p["original"] = re.sub(r"^>\s*", "", p["original"], flags=re.MULTILINE).strip()
        p["_usage"] = final_usage

        yield {
            "type": "done",
            "text": full,
            "usage": final_usage,
            "result": p,
        }
