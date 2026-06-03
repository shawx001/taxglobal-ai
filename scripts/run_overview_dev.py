from __future__ import annotations

import argparse
import contextlib
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173


def _wait_for_port(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for 127.0.0.1:{port}")


def _start_process(args: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        args,
        cwd=ROOT,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TaxGlobal overview frontend + backend dev servers.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    args = parser.parse_args()

    processes = [
        _start_process(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(BACKEND_PORT),
            ]
        ),
        _start_process(
            [
                sys.executable,
                "-m",
                "http.server",
                str(FRONTEND_PORT),
                "--bind",
                "127.0.0.1",
                "--directory",
                str(FRONTEND_DIR),
            ]
        ),
    ]

    try:
        _wait_for_port(BACKEND_PORT)
        _wait_for_port(FRONTEND_PORT)
        url = f"http://127.0.0.1:{FRONTEND_PORT}/index.html"
        print(f"TaxGlobal overview dev page: {url}")
        if not args.no_open:
            webbrowser.open(url)
        while all(proc.poll() is None for proc in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping dev servers...")
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
