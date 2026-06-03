#!/usr/bin/env python3
"""Evaluate OctoBench trajectories with upstream mini-vela and local llama.cpp.

This script intentionally keeps mini-vela's official files unchanged:

1. collect raw trajectories from a benchmark run directory
2. run upstream convert/convert_cc_traj_to_msg.py
3. start local llama.cpp judge server with fixed n_ctx=128000 on GPU
4. call upstream evaluate.py's whole-case evaluate_single for every case
5. stop the judge server that this script started
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
MINI_VELA = ROOT / "mini-vela"
DEFAULT_DATASET = MINI_VELA / "data" / "octobench_full.jsonl"
DEFAULT_VENV = Path("/tmp/octobench-litellm-venv")
EVAL_SCRIPTS = ROOT.parents[1] / "eval_scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from llama_server import LlamaServer  # noqa: E402


JUDGE_PARALLEL = 1


class _MaxTokensProxyServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], upstream_base_url: str, judge_max_tokens: int):
        super().__init__(server_address, _MaxTokensProxyHandler)
        self.upstream_base_url = upstream_base_url.rstrip("/")
        self.judge_max_tokens = judge_max_tokens


class _MaxTokensProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _forward(self, body: bytes | None = None) -> None:
        target = self.server.upstream_base_url + self.path
        data = body
        if self.command == "POST" and self.path == "/v1/chat/completions" and body:
            payload = json.loads(body.decode("utf-8"))
            payload["max_tokens"] = max(int(payload.get("max_tokens") or 0), self.server.judge_max_tokens)
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        auth = self.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth
        request = Request(target, data=data, headers=headers, method=self.command)
        try:
            with urlopen(request, timeout=1800) as response:
                response_body = response.read()
                self.send_response(response.status)
                content_type = response.headers.get("Content-Type")
                if content_type:
                    self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)
        except HTTPError as exc:
            response_body = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

    def do_GET(self) -> None:
        self._forward()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        self._forward(body)


class MaxTokensProxy:
    def __init__(self, upstream_base_url: str, judge_max_tokens: int, host: str = "127.0.0.1"):
        self.server = _MaxTokensProxyServer((host, 0), upstream_base_url, judge_max_tokens)
        self.thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"max_tokens proxy listening at {self.base_url}, judge_max_tokens={self.server.judge_max_tokens}")

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_dataset_by_id(dataset: Path) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    with dataset.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            case = json.loads(line)
            cases[case["instance_id"]] = case
    return cases


def first_session_id(path: Path) -> str:
    with path.open(encoding="utf-8", errors="surrogatepass") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                return json.loads(line).get("session_id") or path.stem
            except json.JSONDecodeError:
                return path.stem
    return path.stem


def normalize_session_id(session_id: str, strip_prefix: str) -> str:
    if strip_prefix and session_id.startswith(strip_prefix):
        return session_id[len(strip_prefix):]
    return session_id


def collect_trajectory_files(run_dir: Path) -> list[Path]:
    patterns = [
        "*/mini-vela-results/trajectories/*.jsonl",
        "mini-vela-results/trajectories/*.jsonl",
        "trajectories/*.jsonl",
        "*.jsonl",
    ]
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in run_dir.glob(pattern):
            resolved = path.resolve()
            if resolved not in seen and path.is_file():
                seen.add(resolved)
                found.append(path)
    return sorted(found)


def prepare_eval_inputs(
    run_dir: Path,
    dataset: Path,
    eval_dir: Path,
    strip_session_prefix: str,
) -> tuple[Path, Path, list[dict[str, Any]]]:
    cases = load_dataset_by_id(dataset)
    raw_dir = eval_dir / "raw-trajectories"
    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    selected: list[dict[str, Any]] = []
    copied: list[dict[str, Any]] = []
    for src in collect_trajectory_files(run_dir):
        original_session_id = first_session_id(src)
        instance_id = normalize_session_id(original_session_id, strip_session_prefix)
        if instance_id not in cases:
            continue
        dst = raw_dir / f"{instance_id}.jsonl"
        with src.open(encoding="utf-8", errors="surrogatepass") as in_f, dst.open(
            "w", encoding="utf-8", errors="surrogatepass"
        ) as out_f:
            for line in in_f:
                if not line.strip():
                    continue
                record = json.loads(line)
                record["session_id"] = instance_id
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
        selected.append(cases[instance_id])
        copied.append(
            {
                "source": str(src),
                "original_session_id": original_session_id,
                "instance_id": instance_id,
                "output": str(dst),
            }
        )

    dataset_out = eval_dir / "dataset_for_eval.jsonl"
    with dataset_out.open("w", encoding="utf-8") as f:
        for case in selected:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    write_json(
        eval_dir / "prepare_manifest.json",
        {
            "run_dir": str(run_dir),
            "source_dataset": str(dataset),
            "raw_trajectory_count": len(copied),
            "case_count": len(selected),
            "strip_session_prefix": strip_session_prefix,
            "trajectories": copied,
        },
    )
    return raw_dir, dataset_out, selected


def run_command(cmd: list[str], cwd: Path, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> subprocess.CompletedProcess:
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")
    write_json(
        stdout_path.with_suffix(".command.json"),
        {
            "cmd": cmd,
            "cwd": str(cwd),
            "returncode": proc.returncode,
            "elapsed_s": time.time() - started,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        },
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command failed with {proc.returncode}: {' '.join(cmd)}")
    return proc


def summarize_scores(scores_path: Path, summary_path: Path) -> None:
    if not scores_path.exists():
        return
    data = json.loads(scores_path.read_text(encoding="utf-8"))
    lines = [
        "# OctoBench Score Summary",
        "",
        f"- total: {data.get('summary', {}).get('total', 0)}",
        f"- success_count: {data.get('summary', {}).get('success_count', 0)}",
        f"- avg_reward: {data.get('summary', {}).get('avg_reward', 0)}",
        f"- pass_count: {data.get('summary', {}).get('pass_count', 0)}",
        "",
        "| instance_id | reward | binary_reward | checks | success | fail |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in data.get("results", []):
        detailed = result.get("detailed_results") or {}
        lines.append(
            "| {instance_id} | {reward} | {binary_reward} | {checks} | {succ} | {fail} |".format(
                instance_id=result.get("instance_id"),
                reward=result.get("reward", 0),
                binary_reward=result.get("binary_reward", 0),
                checks=detailed.get("total_checks", 0),
                succ=detailed.get("total_success", 0),
                fail=detailed.get("total_fail", 0),
            )
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_upstream_evaluate_module():
    spec = importlib.util.spec_from_file_location("octobench_upstream_evaluate", MINI_VELA / "evaluate.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load upstream evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summarize_output(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "results": results,
        "summary": {
            "total": len(results),
            "success_count": sum(1 for r in results if r.get("success")),
            "avg_reward": round(sum(r.get("reward", 0) for r in results) / len(results), 3) if results else 0,
            "pass_count": sum(1 for r in results if r.get("binary_reward") == 1),
        },
    }


def write_scores_atomic(path: Path, results: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(summarize_output(results), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_parallel_evaluate(
    converted: Path,
    selected: list[dict[str, Any]],
    scores: Path,
    model: str,
    base_url: str,
    parallel: int = JUDGE_PARALLEL,
) -> None:
    upstream_evaluate = load_upstream_evaluate_module()
    llm_config = {
        "api_key": "llama.cpp",
        "base_url": base_url,
        "model": model,
    }
    ordered_ids = [case["instance_id"] for case in selected]
    results_by_id: dict[str, dict[str, Any]] = {}
    partial_path = scores.with_suffix(".partial.jsonl")
    if partial_path.exists():
        partial_path.unlink()
    write_scores_atomic(scores, [])

    def evaluate_case(case_data: dict[str, Any]) -> dict[str, Any]:
        instance_id = case_data["instance_id"]
        eval_result = upstream_evaluate.evaluate_single(
            str(converted),
            case_data,
            llm_config,
            session_id=instance_id,
        )
        return {"instance_id": instance_id, **eval_result}

    print(f"[EVAL-PARALLEL] judge_parallel={parallel}, cases={len(selected)}", flush=True)

    with ThreadPoolExecutor(max_workers=parallel) as executor, partial_path.open("a", encoding="utf-8") as partial:
        futures = {executor.submit(evaluate_case, case): case["instance_id"] for case in selected}
        for done_count, future in enumerate(as_completed(futures), start=1):
            instance_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "instance_id": instance_id,
                    "success": False,
                    "error": str(exc),
                    "reward": 0.0,
                    "binary_reward": 0,
                }
            results_by_id[instance_id] = result
            partial.write(json.dumps(result, ensure_ascii=False) + "\n")
            partial.flush()

            ordered_results = [results_by_id[case_id] for case_id in ordered_ids if case_id in results_by_id]
            write_scores_atomic(scores, ordered_results)
            status = "success" if result.get("success") else "failed"
            print(
                f"[EVAL-PARALLEL] {done_count}/{len(selected)} {instance_id}: "
                f"{status}, reward={result.get('reward', 0)}",
                flush=True,
            )

    ordered_results = [results_by_id[case_id] for case_id in ordered_ids if case_id in results_by_id]
    write_scores_atomic(scores, ordered_results)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True, help="Benchmark run directory containing raw trajectories")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, help="Evaluation output directory")
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    parser.add_argument("--strip-session-prefix", default="", help="Normalize ActPlane trajectory session IDs if needed")
    parser.add_argument("--model", default="Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M.gguf")
    parser.add_argument(
        "--judge-max-tokens",
        type=int,
        default=16384,
        help="Forwarding proxy raises upstream evaluate.py max_tokens to this value without editing evaluate.py.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.venv.exists():
        raise SystemExit(f"venv not found: {args.venv}")
    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")

    run_dir = args.run_dir.resolve()
    out_dir = (args.out_dir or (run_dir / f"official-eval-llama-{utc_stamp()}")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_dir, dataset_for_eval, selected = prepare_eval_inputs(
        run_dir=run_dir,
        dataset=args.dataset.resolve(),
        eval_dir=out_dir,
        strip_session_prefix=args.strip_session_prefix,
    )
    if not selected:
        raise SystemExit(f"no evaluable trajectories found under {run_dir}")

    env = os.environ.copy()
    env["PATH"] = f"{args.venv / 'bin'}:{env.get('PATH', '')}"
    converted = out_dir / "converted_trajectories.jsonl"
    run_command(
        [
            str(args.venv / "bin" / "python"),
            "convert/convert_cc_traj_to_msg.py",
            "--input_path",
            str(raw_dir),
            "--output_path",
            str(converted),
        ],
        cwd=MINI_VELA,
        env=env,
        stdout_path=out_dir / "convert.stdout.txt",
        stderr_path=out_dir / "convert.stderr.txt",
    )

    scores = out_dir / "scores_llama_judge.json"
    server = LlamaServer(
        judge_json=True,
        parallel=JUDGE_PARALLEL,
        restart_existing=True,
        log_path=out_dir / "llama-judge-server.log",
    )
    token_proxy = None
    try:
        server.start(timeout=360)
        token_proxy = MaxTokensProxy(server.base_url, args.judge_max_tokens)
        token_proxy.start()
        write_json(
            out_dir / "evaluate.parallel.command.json",
            {
                "mode": "wrapper_whole_case_evaluate_single",
                "upstream_evaluate_py": str(MINI_VELA / "evaluate.py"),
                "trajectories": str(converted),
                "data": str(dataset_for_eval),
                "output": str(scores),
                "model": args.model,
                "base_url": f"{token_proxy.base_url}/v1",
                "judge_parallel": JUDGE_PARALLEL,
                "server_parallel": JUDGE_PARALLEL,
                "judge_max_tokens": args.judge_max_tokens,
                "official_unit": "whole_case_full_checklist",
            },
        )
        run_parallel_evaluate(
            converted=converted,
            selected=selected,
            scores=scores,
            model=args.model,
            base_url=f"{token_proxy.base_url}/v1",
            parallel=JUDGE_PARALLEL,
        )
    finally:
        if token_proxy:
            token_proxy.stop()
        server.stop()

    summarize_scores(scores, out_dir / "scores_summary.md")
    print(json.dumps({"eval_dir": str(out_dir), "case_count": len(selected), "scores": str(scores)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
