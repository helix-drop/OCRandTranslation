#!/usr/bin/env python3
"""流式翻译器单元测试。"""

import unittest
from unittest.mock import patch

import translation.translator as translator


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


class _FakeErrorResponse:
    def __init__(self, status_code=400, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload


class _FakeProviderError(Exception):
    def __init__(self, response):
        super().__init__("provider error")
        self.response = response


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
    def test_build_prompt_includes_footnote_invariants(self):
        prompt = translator.build_prompt("")
        self.assertIn("脚注/尾注编号与出现顺序必须守恒", prompt)
        self.assertIn("必须保留脚注标记形态", prompt)
        self.assertIn("看不清的脚注宁可原样保留在footnotes", prompt)

    def test_build_translate_message_includes_export_contract(self):
        msg = translator._build_translate_message(
            para_text="Body text [^1]",
            para_pages="10",
            footnotes="1. Note",
            heading_level=0,
        )
        self.assertIn("导出契约：original=正文原文", msg)
        self.assertIn("脚注约束：编号与顺序必须守恒", msg)

    def test_build_translate_message_marks_endnote_role(self):
        msg = translator._build_translate_message(
            para_text="1. Endnote entry text",
            para_pages="172",
            footnotes="",
            heading_level=0,
            content_role="endnote",
        )
        self.assertIn("内容角色：尾注条目", msg)
        self.assertIn("这是尾注条目", msg)
        self.assertIn("不得正文化", msg)

    def test_classify_provider_exception_maps_http_400_to_non_retryable_error(self):
        exc = _FakeProviderError(
            _FakeErrorResponse(
                status_code=400,
                payload={"error": {"message": "invalid_request: bad extra_body"}},
                text='{"error":{"message":"invalid_request: bad extra_body"}}',
            )
        )

        mapped = translator._classify_provider_exception(exc)

        self.assertIsInstance(mapped, translator.NonRetryableProviderError)
        self.assertEqual(mapped.status_code, 400)
        self.assertIn("invalid_request", str(mapped))

    def test_structure_system_contains_notes_preservation_rules(self):
        system = translator._STRUCTURE_SYSTEM
        self.assertIn("脚注/尾注保真", system)
        self.assertIn("NOTES/Notes/注释/尾注", system)
        self.assertIn("不得把脚注/尾注条目并入普通正文段落", system)

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

    def test_prepare_translate_request_only_includes_matched_glossary_terms(self):
        sys_prompt, _msg = translator._prepare_translate_request(
            para_text="Alpha is discussed here.",
            para_pages="1",
            footnotes="",
            glossary=[["Alpha", "阿尔法"], ["Beta", "贝塔"]],
        )

        self.assertIn("Alpha→阿尔法", sys_prompt)
        self.assertNotIn("Beta→贝塔", sys_prompt)

    def test_prepare_translate_request_matches_glossary_terms_in_footnotes(self):
        sys_prompt, _msg = translator._prepare_translate_request(
            para_text="Body paragraph without explicit term.",
            para_pages="9",
            footnotes="1. Beta appears only in footnote.",
            glossary=[["Alpha", "阿尔法"], ["Beta", "贝塔"]],
        )

        self.assertIn("Beta→贝塔", sys_prompt)
        self.assertNotIn("Alpha→阿尔法", sys_prompt)

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

    def test_mt_request_uses_user_only_and_translation_options(self):
        response = _FakeNonStreamResponse("机器翻译结果", usage=_FakeUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8))
        client = _FakeOpenAIClient(response)

        with patch.object(translator, "OpenAI", return_value=client):
            result = translator.translate_paragraph(
                para_text="原文里提到了生物传感器。",
                para_pages="1",
                footnotes="",
                glossary=[["生物传感器", "biological sensor"]],
                model_id="qwen-mt-plus",
                api_key="fake-key",
                provider="qwen_mt",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                request_overrides={"extra_body": {"translation_options": {"source_lang": "auto", "target_lang": "Chinese"}}},
            )

        self.assertEqual(result["translation"], "机器翻译结果")
        self.assertEqual(len(client.calls[0]["messages"]), 1)
        self.assertEqual(client.calls[0]["messages"][0]["role"], "user")
        self.assertEqual(
            client.calls[0]["extra_body"]["translation_options"]["target_lang"],
            "Chinese",
        )
        self.assertEqual(
            client.calls[0]["extra_body"]["translation_options"]["terms"],
            [{"source": "生物传感器", "target": "biological sensor"}],
        )

    def test_mt_request_only_sends_matched_glossary_terms_from_body_and_footnotes(self):
        response = _FakeNonStreamResponse("机器翻译结果", usage=_FakeUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8))
        client = _FakeOpenAIClient(response)

        with patch.object(translator, "OpenAI", return_value=client):
            translator.translate_paragraph(
                para_text="The main body does not name the term.",
                para_pages="7",
                footnotes="1. Biosensor calibration note.",
                glossary=[["Biosensor", "生物传感器"], ["Metaphysics", "形而上学"]],
                model_id="qwen-mt-plus",
                api_key="fake-key",
                provider="qwen_mt",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                request_overrides={"extra_body": {"translation_options": {"source_lang": "auto", "target_lang": "Chinese"}}},
            )

        self.assertEqual(
            client.calls[0]["extra_body"]["translation_options"]["terms"],
            [{"source": "Biosensor", "target": "生物传感器"}],
        )

    def test_mt_incremental_stream_emits_true_deltas(self):
        response = _FakeStreamResponse([
            _FakeChunk("我"),
            _FakeChunk("没有"),
            _FakeChunk("笑", usage=_FakeUsage(prompt_tokens=2, completion_tokens=2, total_tokens=4)),
        ])
        client = _FakeOpenAIClient(response)

        with patch.object(translator, "OpenAI", return_value=client):
            events = list(
                translator.stream_translate_paragraph(
                    para_text="orig",
                    para_pages="1",
                    footnotes="",
                    glossary=[],
                    model_id="qwen-mt-flash",
                    api_key="fake-key",
                    provider="qwen_mt",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    request_overrides={"extra_body": {"translation_options": {"source_lang": "auto", "target_lang": "Chinese"}}},
                )
            )

        deltas = [event["text"] for event in events if event["type"] == "delta"]
        self.assertEqual(deltas, ["我", "没有", "笑"])
        self.assertEqual(events[-1]["result"]["translation"], "我没有笑")

    def test_mt_cumulative_stream_trims_repeated_prefix(self):
        response = _FakeStreamResponse([
            _FakeChunk("我"),
            _FakeChunk("我没有"),
            _FakeChunk("我没有笑", usage=_FakeUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5)),
        ])
        client = _FakeOpenAIClient(response)

        with patch.object(translator, "OpenAI", return_value=client):
            events = list(
                translator.stream_translate_paragraph(
                    para_text="orig",
                    para_pages="1",
                    footnotes="",
                    glossary=[],
                    model_id="qwen-mt-plus",
                    api_key="fake-key",
                    provider="qwen_mt",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    request_overrides={"extra_body": {"translation_options": {"source_lang": "auto", "target_lang": "Chinese"}}},
                )
            )

        deltas = [event["text"] for event in events if event["type"] == "delta"]
        self.assertEqual(deltas, ["我", "没有", "笑"])
        self.assertEqual(events[-1]["result"]["translation"], "我没有笑")

    def test_mt_fnm_body_freezes_and_restores_ref_markers(self):
        class _EchoMtClient(_FakeOpenAIClient):
            def create(self, **kwargs):
                self.calls.append(kwargs)
                body = kwargs["messages"][0]["content"]
                return _FakeNonStreamResponse(
                    body.replace("Body one ", "正文译文 "),
                    usage=_FakeUsage(prompt_tokens=4, completion_tokens=4, total_tokens=8),
                )

        client = _EchoMtClient(None)

        with patch.object(translator, "OpenAI", return_value=client):
            result = translator.translate_paragraph(
                para_text="Body one {{FN_REF:fn-01-0001}}",
                para_pages="1",
                footnotes="",
                glossary=[],
                model_id="qwen-mt-plus",
                api_key="fake-key",
                provider="qwen_mt",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                request_overrides={"extra_body": {"translation_options": {"source_lang": "auto", "target_lang": "Chinese"}}},
                is_fnm=True,
            )

        self.assertNotIn("{{FN_REF:fn-01-0001}}", client.calls[0]["messages"][0]["content"])
        self.assertEqual(result["translation"], "正文译文 {{FN_REF:fn-01-0001}}")


if __name__ == "__main__":
    unittest.main()
