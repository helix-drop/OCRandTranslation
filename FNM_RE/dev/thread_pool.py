"""FNM 开发模式后台线程池。

目标：
  - 同一个 `doc_id` 串行（已有任务在跑 → 抛 `Busy`）。
  - 不同 `doc_id` 之间并发。
  - 线程是 daemon，进程退出不阻塞。

用法::

    pool = DevThreadPool()
    pool.spawn(doc_id, phase, target, args=(...), kwargs={...})

    if pool.is_busy(doc_id):
        ...

    info = pool.current(doc_id)  # {'phase': 1, 'started_at': ...} or None
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional


class Busy(Exception):
    """目标 doc 已有 in-flight 任务。"""

    def __init__(self, doc_id: str, phase: Optional[int] = None) -> None:
        msg = f"doc {doc_id!r} is busy"
        if phase is not None:
            msg += f" (phase {phase})"
        super().__init__(msg)
        self.doc_id = doc_id
        self.phase = phase


@dataclass
class _Slot:
    thread: threading.Thread
    phase: int
    started_at: float


class DevThreadPool:
    """非常简单的 per-doc 线程注册表。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, _Slot] = {}

    # ---------- 查询 ----------

    def is_busy(self, doc_id: str) -> bool:
        with self._lock:
            slot = self._slots.get(str(doc_id))
            if slot is None:
                return False
            if not slot.thread.is_alive():
                # 线程已结束但还没回收，顺手清理
                self._slots.pop(str(doc_id), None)
                return False
            return True

    def current(self, doc_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            slot = self._slots.get(str(doc_id))
            if slot is None or not slot.thread.is_alive():
                return None
            return {"phase": slot.phase, "started_at": slot.started_at}

    def active_docs(self) -> list[str]:
        with self._lock:
            return [doc for doc, slot in self._slots.items() if slot.thread.is_alive()]

    # ---------- 调度 ----------

    def spawn(
        self,
        doc_id: str,
        phase: int,
        target: Callable[..., Any],
        *,
        args: Iterable[Any] = (),
        kwargs: Optional[Mapping[str, Any]] = None,
        name: Optional[str] = None,
    ) -> threading.Thread:
        doc_key = str(doc_id)
        if not doc_key:
            raise ValueError("doc_id 不能为空")
        if not isinstance(phase, int) or phase <= 0:
            raise ValueError(f"phase 必须是正整数，收到 {phase!r}")

        call_args = tuple(args or ())
        call_kwargs = dict(kwargs or {})

        with self._lock:
            existing = self._slots.get(doc_key)
            if existing is not None and existing.thread.is_alive():
                raise Busy(doc_key, existing.phase)
            # 清理旧 slot（死线程）
            self._slots.pop(doc_key, None)

            def _runner() -> None:
                try:
                    target(*call_args, **call_kwargs)
                finally:
                    with self._lock:
                        slot = self._slots.get(doc_key)
                        if slot is not None and slot.thread is threading.current_thread():
                            self._slots.pop(doc_key, None)

            thread_name = name or f"fnm-dev-{doc_key}-p{phase}"
            thread = threading.Thread(target=_runner, name=thread_name, daemon=True)
            self._slots[doc_key] = _Slot(thread=thread, phase=phase, started_at=time.time())
            thread.start()
            return thread

    # ---------- 测试友好 ----------

    def join(self, doc_id: str, timeout: Optional[float] = None) -> bool:
        """等待指定 doc 的线程结束。返回是否已结束。"""
        with self._lock:
            slot = self._slots.get(str(doc_id))
            thread = slot.thread if slot is not None else None
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def join_all(self, timeout: Optional[float] = None) -> None:
        with self._lock:
            threads = [slot.thread for slot in self._slots.values()]
        for thread in threads:
            thread.join(timeout)


# 模块级默认池：web 层复用这一个实例
_default_pool = DevThreadPool()


def get_default_pool() -> DevThreadPool:
    return _default_pool
