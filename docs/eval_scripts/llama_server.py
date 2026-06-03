#!/usr/bin/env python3
"""Manage a local llama-server process for eval.

Usage as a module:
    from llama_server import LlamaServer
    srv = LlamaServer()
    srv.start()        # blocks until healthy
    # ... run eval ...
    srv.stop()

Usage as a script:
    python llama_server.py start   # start in foreground, Ctrl-C to stop
    python llama_server.py health  # check if already running
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests

DEFAULT_LLAMA_SERVER = Path(
    os.environ.get(
        "LLAMA_SERVER_BIN",
        "/home/yunwei37/workspace/llama.cpp-latest/build/bin/llama-server",
    )
)
DEFAULT_MODEL = Path(
    os.environ.get(
        "LLAMA_MODEL",
        os.path.expanduser(
            "~/.cache/huggingface/hub/models--DevQuasar--Qwen.Qwen3.6-27B-GGUF/"
            "snapshots/b19fa7e8538a1a5f66452eb3b3167e026177be1d/"
            "Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M.gguf"
        ),
    )
)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18080
DEFAULT_GPU_LAYERS = os.environ.get("LLAMA_GPU_LAYERS", "all")
DEFAULT_CTX_SIZE = int(os.environ.get("LLAMA_CTX_SIZE", "32768"))


class LlamaServer:
    def __init__(
        self,
        server_bin: Path = DEFAULT_LLAMA_SERVER,
        model_path: Path = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        gpu_layers: str = DEFAULT_GPU_LAYERS,
        ctx_size: int = DEFAULT_CTX_SIZE,
    ):
        self.server_bin = Path(server_bin)
        self.model_path = Path(model_path)
        self.host = host
        self.port = port
        self.gpu_layers = gpu_layers
        self.ctx_size = ctx_size
        self.base_url = f"http://{host}:{port}"
        self.proc: subprocess.Popen | None = None

    def healthy(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=2)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def start(self, timeout: float = 120) -> None:
        if self.healthy():
            print(f"llama-server already running at {self.base_url}")
            return

        if not self.server_bin.exists():
            raise FileNotFoundError(f"llama-server not found: {self.server_bin}")
        if not self.model_path.exists():
            raise FileNotFoundError(f"model not found: {self.model_path}")

        cmd = [
            str(self.server_bin),
            "-m", str(self.model_path),
            "--host", self.host,
            "--port", str(self.port),
            "-ngl", self.gpu_layers,
            "-c", str(self.ctx_size),
            "--no-webui",
            "--log-disable",
        ]
        print(f"Starting llama-server: {' '.join(cmd[:6])}...")
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                stderr = self.proc.stderr.read() if self.proc.stderr else ""
                raise RuntimeError(
                    f"llama-server exited with code {self.proc.returncode}:\n{stderr[:500]}"
                )
            if self.healthy():
                print(f"llama-server healthy at {self.base_url}")
                return
            time.sleep(1)
        raise TimeoutError(f"llama-server did not become healthy within {timeout}s")

    def stop(self) -> None:
        if not self.proc:
            return
        print("Stopping llama-server...")
        self.proc.send_signal(signal.SIGINT)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        self.proc = None
        print("llama-server stopped.")

    def model_name(self) -> str:
        return self.model_path.stem


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    srv = LlamaServer()

    if action == "health":
        if srv.healthy():
            print(f"OK — llama-server healthy at {srv.base_url}")
        else:
            print(f"NOT RUNNING at {srv.base_url}")
            sys.exit(1)
    elif action == "start":
        srv.start()
        print("Press Ctrl-C to stop.")
        try:
            srv.proc.wait()
        except KeyboardInterrupt:
            srv.stop()
    else:
        print(f"Usage: {sys.argv[0]} [start|health]")
        sys.exit(1)
