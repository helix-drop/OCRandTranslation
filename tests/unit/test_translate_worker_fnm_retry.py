from __future__ import annotations

import unittest
from unittest.mock import patch

from translation.translate_worker_fnm import _retry_real_mode_failed_units, run_fnm_worker


class _RepoStub:
    def __init__(self, unit: dict):
        self._unit = dict(unit)
        self.update_calls: list[tuple[str, str, dict]] = []

    def list_fnm_translation_units(self, _doc_id: str) -> list[dict]:
        return [dict(self._unit)]

    def update_fnm_translation_unit(self, doc_id: str, unit_id: str, **fields) -> None:
        self.update_calls.append((doc_id, unit_id, dict(fields)))
        self._unit = {**self._unit, **fields}


class RetryRealModeFailedUnitsTest(unittest.TestCase):
    def test_retry_updates_unit_with_doc_id(self) -> None:
        doc_id = "doc-retry-fnm-unit"
        unit_id = "unit-retry-001"
        repo = _RepoStub(
            {
                "unit_id": unit_id,
                "unit_idx": 1,
                "kind": "body",
                "page_start": 36,
                "section_title": "Leçon du 10 janvier 1979",
                "page_segments": [
                    {
                        "page_no": 36,
                        "paragraphs": [
                            {
                                "text": "source",
                                "translation_status": "error",
                                "last_error": "FNM 引用标记未保留",
                                "consumed_by_prev": False,
                                "manual_resolved": False,
                            }
                        ],
                    }
                ],
            }
        )

        deps = {
            "get_active_translate_args": lambda: ("model", {}),
            "get_glossary": lambda _doc_id: [],
            "translate_page_stream": lambda *_args, **_kwargs: {
                "_page_entries": [
                    {
                        "translation": "translated",
                        "_status": "done",
                        "_error": "",
                    }
                ]
            },
            "is_stop_requested": lambda _doc_id: False,
            "load_translate_state": lambda _doc_id: {},
            "save_translate_state": lambda *_args, **_kwargs: None,
        }

        with (
            patch(
                "translation.translate_worker_fnm._unit_stream_context",
                return_value=({"footnotes": ""}, [{"text": "source"}]),
            ),
            patch("translation.translate_worker_fnm._rebuild_fnm_diagnostic_page_entries", return_value=[]),
            patch("translation.translate_worker_fnm._save_real_mode_failure_state", return_value={}),
        ):
            _retry_real_mode_failed_units(doc_id, deps, repo, pages=[])

        self.assertTrue(repo.update_calls)
        updated_doc_id, updated_unit_id, _fields = repo.update_calls[0]
        self.assertEqual(updated_doc_id, doc_id)
        self.assertEqual(updated_unit_id, unit_id)

    def test_retry_continues_to_next_model_when_retry_model_raises(self) -> None:
        doc_id = "doc-retry-fallback"
        unit_id = "unit-retry-fallback-001"
        repo = _RepoStub(
            {
                "unit_id": unit_id,
                "unit_idx": 1,
                "kind": "body",
                "page_start": 48,
                "page_segments": [
                    {
                        "page_no": 48,
                        "paragraphs": [
                            {
                                "text": "source",
                                "translation_status": "error",
                                "last_error": "first model failed",
                                "manual_resolved": False,
                            }
                        ],
                    }
                ],
            }
        )
        calls: list[str] = []

        def _fake_translate_page_stream(*args, **_kwargs):
            calls.append(args[2])
            if args[2] == "slot2":
                raise RuntimeError("slot2 exploded")
            return {
                "_page_entries": [
                    {
                        "translation": "translated by slot3",
                        "_status": "done",
                        "_error": "",
                    }
                ]
            }

        deps = {
            "get_glossary": lambda _doc_id: [],
            "get_translation_retry_model_args": lambda: [
                ("slot2", {"model_id": "slot2-model", "provider": "qwen", "api_key": "key2"}),
                ("slot3", {"model_id": "slot3-model", "provider": "qwen", "api_key": "key3"}),
            ],
            "translate_page_stream": _fake_translate_page_stream,
            "is_stop_requested": lambda _doc_id: False,
            "load_translate_state": lambda _doc_id: {},
            "save_translate_state": lambda *_args, **_kwargs: None,
        }

        with (
            patch(
                "translation.translate_worker_fnm._unit_stream_context",
                return_value=({"footnotes": ""}, [{"text": "source"}]),
            ),
            patch(
                "translation.translate_worker_fnm.apply_body_unit_entry_result",
                return_value={
                    "translated_text": "translated by slot3",
                    "failed_locations": [],
                    "page_segments": [
                        {
                            "page_no": 48,
                            "paragraphs": [
                                {
                                    "text": "source",
                                    "translation": "translated by slot3",
                                    "translation_status": "done",
                                }
                            ],
                        }
                    ],
                },
            ),
            patch("translation.translate_worker_fnm._rebuild_fnm_diagnostic_page_entries", return_value=[]),
            patch("translation.translate_worker_fnm._save_real_mode_failure_state", return_value={}),
        ):
            _retry_real_mode_failed_units(doc_id, deps, repo, pages=[])

        self.assertEqual(calls, ["slot2", "slot3"])
        self.assertEqual(repo._unit["status"], "done")
        self.assertEqual(repo._unit["translated_text"], "translated by slot3")

    def test_run_fnm_worker_real_mode_triggers_post_translate_export_checks(self) -> None:
        called = {"retry": 0, "rebuild": 0, "post_export": 0}

        class _Repo:
            pass

        def _fake_run_translate_worker(**kwargs):
            kwargs["after_target_loop"](
                doc_id="doc-real-fnm",
                worker_plan={},
                context={"execution_mode": "real", "pages": []},
                deps={},
            )
            return {"ok": True}

        with (
            patch("translation.translate_worker_fnm.SQLiteRepository", return_value=_Repo()),
            patch("translation.translate_worker_fnm.run_translate_worker", side_effect=_fake_run_translate_worker),
            patch("translation.translate_worker_fnm._retry_real_mode_failed_units", side_effect=lambda *args, **kwargs: called.__setitem__("retry", called["retry"] + 1)),
            patch("translation.translate_worker_fnm._rebuild_fnm_diagnostic_page_entries", side_effect=lambda *args, **kwargs: called.__setitem__("rebuild", called["rebuild"] + 1)),
            patch("translation.translate_worker_fnm.run_post_translate_export_checks_for_doc", side_effect=lambda *args, **kwargs: called.__setitem__("post_export", called["post_export"] + 1)),
        ):
            result = run_fnm_worker("doc-real-fnm", "Demo", deps={})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(called["retry"], 1)
        self.assertEqual(called["rebuild"], 1)
        self.assertEqual(called["post_export"], 1)


if __name__ == "__main__":
    unittest.main()
