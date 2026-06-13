"""Subprocess wrapper around scripts/convert.py.

Streams stdout, parses progress markers, calls back into the queue.
The subprocess is launched with CWD = repo root so its relative paths
behave identically to a manual CLI invocation, and run through the
sandbox module so it can only write to its own job dirs.

We use synchronous `subprocess.Popen` bridged to asyncio via a reader
thread rather than `asyncio.create_subprocess_exec`. Reason: on Windows
under uvicorn `--reload`, the worker process runs on `SelectorEventLoop`,
which has no subprocess support and raises a bare `NotImplementedError`.
The thread bridge works on every event loop.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import REPO_ROOT, get_settings
from . import sandbox

STAGE_RE = re.compile(r"^===\s*(\d+)/(\d+)\s+")
PAGE_RE = re.compile(r"^page\s+(\d+):")
LOG_TAIL_LINES = 200

_EOF = object()  # sentinel pushed onto the queue when the reader thread exits


async def run_convert(
    *,
    source: Path,
    work_dir: Path,
    upload_dir: Path,
    mode: str,
    on_stage: Callable[[int, int], Awaitable[None]],
    on_page: Callable[[int], Awaitable[None]],
    on_line: Callable[[str], Awaitable[None]],
) -> tuple[int, str]:
    """Run convert.py. Returns (exit_code, full_tail_log)."""
    s = get_settings()
    cmd = [
        s.python_bin,
        str(s.convert_script),
        "--source", str(source),
        "--work-dir", str(work_dir),
        # EasyOCR + Tesseract are optional cross-verifiers; skipping
        # them keeps the prod install (and the sandbox) lean. Set
        # DECKWEAVER_CROSS_VERIFY=true if you've installed them and
        # want belt-and-suspenders OCR confidence.
    ]
    if not s.cross_verify:
        cmd.append("--skip-cross-verify")
    if mode != "full":
        cmd += ["--mode", mode]

    wrapped, cleanup = sandbox.wrap_command(
        cmd, upload_dir=upload_dir, output_dir=work_dir,
    )
    env = sandbox.safe_env()
    preexec = sandbox.make_preexec(
        memory_mb=s.subprocess_memory_mb,
        cpu_seconds=s.subprocess_cpu_seconds,
        output_mb=s.subprocess_output_mb,
    )

    loop = asyncio.get_running_loop()
    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            wrapped,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            # preexec_fn is None on Windows (see sandbox.make_preexec),
            # which is the only value Popen accepts there.
            preexec_fn=preexec,
        )

        queue: asyncio.Queue[Any] = asyncio.Queue()

        def _reader() -> None:
            assert proc is not None and proc.stdout is not None
            try:
                for raw in iter(proc.stdout.readline, b""):
                    text = raw.decode("utf-8", errors="replace").rstrip()
                    loop.call_soon_threadsafe(queue.put_nowait, text)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _EOF)

        threading.Thread(target=_reader, daemon=True).start()

        tail: deque[str] = deque(maxlen=LOG_TAIL_LINES)
        try:
            while True:
                item = await queue.get()
                if item is _EOF:
                    break
                line = item  # type: str
                tail.append(line)
                await on_line(line)
                m = STAGE_RE.match(line)
                if m:
                    await on_stage(int(m.group(1)), int(m.group(2)))
                    continue
                m = PAGE_RE.match(line)
                if m:
                    await on_page(int(m.group(1)))

            code = await loop.run_in_executor(None, proc.wait)
            return code, "\n".join(tail)
        except asyncio.CancelledError:
            # Best-effort: terminate then kill if it doesn't exit.
            try:
                proc.terminate()
                await loop.run_in_executor(None, lambda: proc.wait(timeout=5))
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception:
                pass
            raise
    finally:
        for p in cleanup:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
