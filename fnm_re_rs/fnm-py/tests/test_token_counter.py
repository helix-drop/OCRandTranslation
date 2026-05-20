"""M2.B5: token_counter — dump_traces / write_summary_traces."""

import json
import tempfile
from pathlib import Path

import fnm_re_rs


def test_dump_traces_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        written = fnm_re_rs.dump_traces_json(tmpdir, "test-doc")
        assert written == 0


def test_write_summary_traces_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = {"by_stage": {}, "total": {}}
        result = json.loads(
            fnm_re_rs.write_summary_traces_json(tmpdir, json.dumps(summary))
        )
        assert result["written"] == 0


def test_write_summary_traces_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        summary = {
            "by_stage": {
                "repair_cluster": {
                    "request_count": 5,
                    "prompt_tokens": 1000,
                    "completion_tokens": 200,
                    "total_tokens": 1200,
                }
            },
            "total": {
                "request_count": 5,
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "total_tokens": 1200,
            },
        }
        result = json.loads(
            fnm_re_rs.write_summary_traces_json(tmpdir, json.dumps(summary))
        )
        assert result["written"] == 1
        trace_dir = Path(tmpdir) / "llm_traces"
        summary_file = trace_dir / "repair_cluster.summary.json"
        assert summary_file.exists()
        data = json.loads(summary_file.read_text())
        assert data["stage"] == "repair_cluster"
        assert data["usage"]["request_count"] == 5
