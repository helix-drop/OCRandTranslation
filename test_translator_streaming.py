#!/usr/bin/env python3
"""流式翻译器单元测试。"""

import unittest
from unittest.mock import patch

import translator


class _FakeUsage:
    def __init__(self, prompt_tokens=0, completion_tokens=0, total_tokens=None):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens if total_tokens is not None else prompt_tokens + completion_tokens


class _FakeDelta:
    def __init__(self, content=""):
        self.content = content


class _FakeChoice:
    def __init__(self, content=""):
        self.delta = _FakeDelta(content)


class _FakeMessage:
    def __init__(self, content=""):
        self.content = content


class _FakeNonStreamChoice:
    def __init__(self, content=""):
        self.message = _FakeMessage(content)


class _FakeChunk:
    def __init__(self, content="", usage=None):
        self.choices = [] if content is None else [_FakeChoice(content)]
        self.usage = usage


class _FakeStreamResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        self.closed = True


class _FakeOpenAIClient:
    def __init__(self, response):
        self._response = response
        self.chat = self
        self.completions = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeNonStreamResponse:
    def __init__(self, content, usage=None):
        self.choices = [_FakeNonStreamChoice(content)]
        self.usage = usage or _FakeUsage()


class TranslatorStreamingTest(unittest.TestCase):
    def test_stream_translate_paragraph_yields_delta_usage_and_done(self):
        json_text = (
            '{"pages":"1","original":"orig","translation":"译文",'
            '"footnotes":"","footnotes_translation":""}'
        )
        chunks = [
            _FakeChunk(json_text[:20]),
            _FakeChunk(json_text[20:55]),
            _FakeChunk(json_text[55:], usage=_FakeUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18)),
        ]
        fake_response = _FakeStreamResponse(chunks)

        with patch.object(translator, "OpenAI", return_value=_FakeOpenAIClient(fake_response)):
            events = list(translator.stream_translate_paragraph(
                para_text="orig",
                para_pages="1",
                footnotes="",
                glossary=[],
                model_id="fake-model",
                api_key="fake-key",
                provider="qwen",
            ))

        self.assertEqual([event["type"] for event in events], ["delta", "usage", "done"])
        self.assertEqual(events[-1]["result"]["translation"], "译文")
        self.assertEqual(events[-1]["usage"]["total_tokens"], 18)
        self.assertEqual("".join(event.get("text", "") for event in events if event["type"] == "delta"), "译文")
        self.assertFalse(any('{"pages"' in event.get("text", "") for event in events if event["type"] == "delta"))

    def test_stream_translate_paragraph_hides_raw_json_during_streaming(self):
        json_text = (
            '{"pages":"4","original":"orig","translation":"第一句\\n第二句",'
            '"footnotes":"","footnotes_translation":""}'
        )
        chunks = [
            _FakeChunk(json_text[:18]),
            _FakeChunk(json_text[18:42]),
            _FakeChunk(json_text[42:68]),
            _FakeChunk(json_text[68:], usage=_FakeUsage(prompt_tokens=9, completion_tokens=5, total_tokens=14)),
        ]
        fake_response = _FakeStreamResponse(chunks)

        with patch.object(translator, "OpenAI", return_value=_FakeOpenAIClient(fake_response)):
            events = list(translator.stream_translate_paragraph(
                para_text="orig",
                para_pages="4",
                footnotes="",
                glossary=[],
                model_id="fake-model",
                api_key="fake-key",
                provider="qwen",
            ))

        delta_text = "".join(event.get("text", "") for event in events if event["type"] == "delta")
        self.assertEqual(delta_text, "第一句\n第二句")
        self.assertEqual(events[-1]["result"]["translation"], "第一句\n第二句")
        self.assertFalse('translation":' in delta_text)

    def test_stream_translate_paragraph_respects_stop_checker(self):
        holder = {}
        chunks = [
            _FakeChunk('{"pages":"1",'),
            _FakeChunk('"original":"orig"}'),
        ]

        def _fake_openai(*args, **kwargs):
            response = _FakeStreamResponse(chunks)
            holder["response"] = response
            return _FakeOpenAIClient(response)

        checks = iter([False, True, True])

        with patch.object(translator, "OpenAI", side_effect=_fake_openai):
            with self.assertRaises(translator.TranslateStreamAborted):
                list(translator.stream_translate_paragraph(
                    para_text="orig",
                    para_pages="1",
                    footnotes="",
                    glossary=[],
                    model_id="fake-model",
                    api_key="fake-key",
                    provider="qwen",
                    stop_checker=lambda: next(checks, True),
                ))

        self.assertTrue(holder["response"].closed)

    def test_stream_translate_paragraph_keeps_heading_translation_from_swallowing_body(self):
        json_text = (
            '{"pages":"11","original":"Funding","translation":"资助\\n\\n本研究获得资助。",'
            '"footnotes":"","footnotes_translation":""}'
        )
        chunks = [
            _FakeChunk(json_text[:30]),
            _FakeChunk(json_text[30:68]),
            _FakeChunk(json_text[68:], usage=_FakeUsage(prompt_tokens=6, completion_tokens=4, total_tokens=10)),
        ]
        fake_response = _FakeStreamResponse(chunks)

        with patch.object(translator, "OpenAI", return_value=_FakeOpenAIClient(fake_response)):
            events = list(translator.stream_translate_paragraph(
                para_text="Funding",
                para_pages="11",
                footnotes="",
                glossary=[],
                model_id="fake-model",
                api_key="fake-key",
                provider="qwen",
                heading_level=2,
                next_context="This research received funding from the Ministry of Science and Technology, Taiwan.",
            ))

        delta_text = "".join(event.get("text", "") for event in events if event["type"] == "delta")
        self.assertEqual(delta_text, "资助")
        self.assertEqual(events[-1]["result"]["translation"], "资助")

    def test_translate_paragraph_accepts_non_stream_content_list(self):
        response = _FakeNonStreamResponse(
            [
                {"type": "output_text", "text": '{"pages":"1","original":"orig","translation":"译文","footnotes":"","footnotes_translation":""}'},
            ],
            usage=_FakeUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )
        client = _FakeOpenAIClient(response)

        with patch.object(translator, "OpenAI", return_value=client):
            result = translator.translate_paragraph(
                para_text="orig",
                para_pages="1",
                footnotes="",
                glossary=[],
                model_id="qwen3.5-plus",
                api_key="fake-key",
                provider="qwen",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                request_overrides={"extra_body": {"enable_thinking": False}},
            )

        self.assertEqual(result["translation"], "译文")
        self.assertEqual(result["_usage"]["total_tokens"], 8)

    def test_stream_qwen_request_includes_disable_thinking_extra_body(self):
        json_text = (
            '{"pages":"1","original":"orig","translation":"译文",'
            '"footnotes":"","footnotes_translation":""}'
        )
        response = _FakeStreamResponse([
            _FakeChunk(json_text, usage=_FakeUsage(prompt_tokens=2, completion_tokens=1, total_tokens=3)),
        ])
        client = _FakeOpenAIClient(response)

        with patch.object(translator, "OpenAI", return_value=client):
            events = list(translator.stream_translate_paragraph(
                para_text="orig",
                para_pages="1",
                footnotes="",
                glossary=[],
                model_id="qwen3.5-plus",
                api_key="fake-key",
                provider="qwen",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                request_overrides={"extra_body": {"enable_thinking": False}},
            ))

        self.assertEqual(events[-1]["result"]["translation"], "译文")
        self.assertEqual(client.calls[0]["extra_body"], {"enable_thinking": False})


if __name__ == "__main__":
    unittest.main()
