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

    def create(self, **kwargs):
        return self._response


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

        self.assertEqual([event["type"] for event in events], ["delta", "delta", "delta", "usage", "done"])
        self.assertEqual(events[-1]["result"]["translation"], "译文")
        self.assertEqual(events[-1]["usage"]["total_tokens"], 18)

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


if __name__ == "__main__":
    unittest.main()
