import logging
import os
import sys
import time


_SESSION_LOG_PATH = ""
_SESSION_LOG_READY = False


def _session_log_dir(project_root: str) -> str:
    return os.path.join(project_root, "logs", "sessions")


def _build_session_log_path(log_dir: str) -> str:
    label = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    pid = os.getpid()
    return os.path.join(log_dir, f"app_{label}_{pid}.log")


def _prune_session_logs(log_dir: str, keep_latest: int) -> None:
    if keep_latest <= 0:
        keep_latest = 1
    if not os.path.isdir(log_dir):
        return
    candidates = []
    for filename in os.listdir(log_dir):
        if not filename.startswith("app_") or not filename.endswith(".log"):
            continue
        abs_path = os.path.join(log_dir, filename)
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            continue
        candidates.append((mtime, abs_path))
    candidates.sort(key=lambda item: item[0], reverse=True)
    for _mtime, stale_path in candidates[keep_latest:]:
        try:
            os.remove(stale_path)
        except OSError:
            continue


def _detach_existing_ocr_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        if not getattr(handler, "_ocr_managed_handler", False):
            continue
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def setup_logging():
    """初始化全局日志系统。

    - 输出到 stderr（控制台）
    - 每次启动写入独立日志：logs/sessions/app_YYYYMMDD-HHMMSS_<pid>.log
    - 自动清理，仅保留最近 30 次启动日志
    - 默认级别 INFO，可通过环境变量 LOG_LEVEL 覆盖
    - werkzeug 请求日志设为 WARNING，避免刷屏
    """
    global _SESSION_LOG_PATH, _SESSION_LOG_READY

    if _SESSION_LOG_READY and _SESSION_LOG_PATH:
        os.environ["APP_SESSION_LOG_PATH"] = _SESSION_LOG_PATH
        return _SESSION_LOG_PATH

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(level)
    _detach_existing_ocr_handlers(root)

    # 控制台 handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console._ocr_managed_handler = True
    root.addHandler(console)

    # 会话级文件 handler（每次进程启动独立文件）
    project_root = os.path.dirname(__file__)
    log_dir = _session_log_dir(project_root)
    os.makedirs(log_dir, exist_ok=True)
    try:
        keep_latest = int(os.environ.get("APP_LOG_KEEP_STARTUPS", "30") or 30)
    except Exception:
        keep_latest = 30
    session_log_path = _build_session_log_path(log_dir)
    file_handler = logging.FileHandler(session_log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler._ocr_managed_handler = True
    root.addHandler(file_handler)

    # werkzeug HTTP 访问日志降级，避免刷屏
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    _prune_session_logs(log_dir, keep_latest=keep_latest)
    _SESSION_LOG_PATH = session_log_path
    _SESSION_LOG_READY = True
    os.environ["APP_SESSION_LOG_PATH"] = _SESSION_LOG_PATH
    return _SESSION_LOG_PATH
