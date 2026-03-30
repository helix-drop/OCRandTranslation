#!/usr/bin/env python3
"""Managed launcher: closing the dedicated browser window stops the app."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_URL = "http://localhost:8080"


def build_browser_command(system: str, browser_path: str, profile_dir: str, url: str) -> list[str]:
    command = [
        browser_path,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        f"--app={url}",
    ]
    if system == "Darwin":
        command.append("--disable-features=DialMediaRouteProvider")
    return command


def browser_candidates(system: str) -> list[str]:
    if system == "Darwin":
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            str(Path.home() / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ]

    if system == "Windows":
        prefixes = [
            os.environ.get("ProgramFiles", ""),
            os.environ.get("ProgramFiles(x86)", ""),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        rels = [
            r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
        ]
        return [
            os.path.join(prefix, rel)
            for prefix in prefixes if prefix
            for rel in rels
        ]

    return []


def find_supported_browser(system: str) -> str | None:
    for candidate in browser_candidates(system):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def wait_for_server(url: str, timeout_s: float = 20.0, interval_s: float = 0.25) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=0.5) as resp:
                if 200 <= int(resp.status) < 500:
                    return True
        except Exception:
            pass
        time.sleep(interval_s)
    return False


def terminate_process(proc: subprocess.Popen | None, grace_s: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace_s)
        return
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the app and bind it to a dedicated browser window.")
    parser.add_argument("--server-python", required=True, help="Python executable used to launch app.py")
    parser.add_argument("--url", default=DEFAULT_URL, help="App URL, default http://localhost:8080")
    parser.add_argument("--cwd", default=str(ROOT), help="Repository root")
    parser.add_argument("--browser-path", default="", help="Optional explicit Chrome/Edge executable path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    system = platform.system()
    cwd = Path(args.cwd).resolve()
    profile_dir = tempfile.mkdtemp(prefix="ocr-reader-managed-profile-")
    server_proc: subprocess.Popen | None = None
    browser_proc: subprocess.Popen | None = None

    def cleanup(_signum=None, _frame=None):
        terminate_process(browser_proc, grace_s=2.0)
        terminate_process(server_proc, grace_s=5.0)
        shutil.rmtree(profile_dir, ignore_errors=True)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        server_proc = subprocess.Popen(
            [args.server_python, "app.py"],
            cwd=str(cwd),
        )
        if not wait_for_server(args.url):
            print(f"Managed launch failed: app did not become ready at {args.url} in time.", file=sys.stderr)
            return 1

        browser_path = args.browser_path or find_supported_browser(system)
        if not browser_path:
            print(
                "Managed launch could not find Chrome or Edge. Use the standard launcher instead.",
                file=sys.stderr,
            )
            return 1

        browser_proc = subprocess.Popen(
            build_browser_command(system, browser_path, profile_dir, args.url),
            cwd=str(cwd),
        )

        while True:
            if browser_proc.poll() is not None:
                return 0
            if server_proc.poll() is not None:
                print("The app process exited early, so the managed launch is stopping.", file=sys.stderr)
                return int(server_proc.returncode or 1)
            time.sleep(0.5)
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
