"""FNM_RE/dev/thread_pool.py 的单元测试。"""
from __future__ import annotations

import threading
import time
import unittest

from FNM_RE.dev.thread_pool import Busy, DevThreadPool


class DevThreadPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = DevThreadPool()

    def tearDown(self) -> None:
        self.pool.join_all(timeout=2.0)

    def test_spawn_then_runs_to_completion(self):
        flag = threading.Event()

        def _work() -> None:
            flag.set()

        self.pool.spawn("doc-a", 1, _work)
        self.assertTrue(flag.wait(timeout=1.0))
        self.assertTrue(self.pool.join("doc-a", timeout=1.0))
        self.assertFalse(self.pool.is_busy("doc-a"))
        self.assertIsNone(self.pool.current("doc-a"))

    def test_same_doc_busy_raises(self):
        gate = threading.Event()
        release = threading.Event()

        def _slow() -> None:
            gate.set()
            release.wait(timeout=2.0)

        self.pool.spawn("doc-a", 1, _slow)
        self.assertTrue(gate.wait(timeout=1.0))
        self.assertTrue(self.pool.is_busy("doc-a"))

        with self.assertRaises(Busy) as ctx:
            self.pool.spawn("doc-a", 2, lambda: None)
        self.assertEqual(ctx.exception.doc_id, "doc-a")
        self.assertEqual(ctx.exception.phase, 1)

        release.set()
        self.assertTrue(self.pool.join("doc-a", timeout=1.0))
        self.assertFalse(self.pool.is_busy("doc-a"))

    def test_different_docs_run_in_parallel(self):
        both_in = threading.Barrier(2, timeout=2.0)
        done_a = threading.Event()
        done_b = threading.Event()

        def _work_a() -> None:
            both_in.wait()
            done_a.set()

        def _work_b() -> None:
            both_in.wait()
            done_b.set()

        self.pool.spawn("doc-a", 1, _work_a)
        self.pool.spawn("doc-b", 1, _work_b)
        # 如果不是并发的，barrier 会超时抛 BrokenBarrierError
        self.assertTrue(done_a.wait(timeout=1.5))
        self.assertTrue(done_b.wait(timeout=1.5))

    def test_spawn_with_args_and_kwargs(self):
        received: dict = {}

        def _work(a, *, b) -> None:
            received["a"] = a
            received["b"] = b

        self.pool.spawn("doc-a", 1, _work, args=(1,), kwargs={"b": 2})
        self.assertTrue(self.pool.join("doc-a", timeout=1.0))
        self.assertEqual(received, {"a": 1, "b": 2})

    def test_spawn_after_previous_completes(self):
        done = threading.Event()
        self.pool.spawn("doc-a", 1, done.set)
        self.assertTrue(self.pool.join("doc-a", timeout=1.0))
        done.clear()
        self.pool.spawn("doc-a", 2, done.set)
        self.assertTrue(done.wait(timeout=1.0))

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            self.pool.spawn("", 1, lambda: None)
        with self.assertRaises(ValueError):
            self.pool.spawn("doc-a", 0, lambda: None)
        with self.assertRaises(ValueError):
            self.pool.spawn("doc-a", -1, lambda: None)

    def test_runner_exception_clears_slot(self):
        def _boom() -> None:
            raise RuntimeError("boom")

        self.pool.spawn("doc-a", 1, _boom)
        self.assertTrue(self.pool.join("doc-a", timeout=1.0))
        # 异常后槽位被释放，可以再次 spawn
        self.assertFalse(self.pool.is_busy("doc-a"))
        self.pool.spawn("doc-a", 1, lambda: None)
        self.assertTrue(self.pool.join("doc-a", timeout=1.0))

    def test_current_reports_phase(self):
        gate = threading.Event()
        release = threading.Event()

        def _work() -> None:
            gate.set()
            release.wait(timeout=2.0)

        t0 = time.time()
        self.pool.spawn("doc-a", 3, _work)
        self.assertTrue(gate.wait(timeout=1.0))
        snapshot = self.pool.current("doc-a")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["phase"], 3)
        self.assertGreaterEqual(snapshot["started_at"], t0)
        release.set()


if __name__ == "__main__":
    unittest.main()
