"""Disable Terminal-Bench's tmux wait timeout for local full runs.

This module is loaded by Python's site machinery when its directory is present
on PYTHONPATH. It intentionally leaves non-Terminal-Bench Python processes alone.
"""

from __future__ import annotations

import asyncio
from functools import partial
import time
import re
import os


try:
    from terminal_bench.terminal.tmux_session import TmuxSession
except Exception:
    TmuxSession = None  # type: ignore[assignment]


if TmuxSession is not None:
    _original_send_keys = TmuxSession.send_keys
    _timeout_prefix = re.compile(
        r"(^|[;&|]\s*)timeout(?:\s+-\S+)*\s+\S+\s+"
    )
    _python_timeout_kwarg = re.compile(
        r",\s*timeout\s*=\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    )

    def _strip_shell_timeout_prefix(keys):
        if isinstance(keys, str):
            key_list = [keys]
            was_string = True
        else:
            key_list = list(keys)
            was_string = False

        cleaned = []
        for key in key_list:
            if isinstance(key, str):
                key = _python_timeout_kwarg.sub("", key)
            if isinstance(key, str) and "\n" not in key and "\r" not in key:
                key = _timeout_prefix.sub(r"\1", key)
            cleaned.append(key)

        return cleaned[0] if was_string else cleaned

    def _send_keys_without_shell_timeout(self, keys, *args, **kwargs):
        return _original_send_keys(
            self,
            _strip_shell_timeout_prefix(keys),
            *args,
            **kwargs,
        )

    def _send_blocking_keys_without_timeout(self, keys, max_timeout_sec):
        start_time_sec = time.time()
        self.container.exec_run(self._tmux_send_keys(keys), user=self._user)

        result = self._exec_run(["tmux", "wait", "done"])
        if result.exit_code != 0:
            raise RuntimeError("tmux wait failed without a timeout wrapper")

        elapsed_time_sec = time.time() - start_time_sec
        self._logger.debug(
            f"Blocking command completed in {elapsed_time_sec:.2f}s without timeout."
        )

    TmuxSession.send_keys = _send_keys_without_shell_timeout
    TmuxSession._send_blocking_keys = _send_blocking_keys_without_timeout


try:
    from terminal_bench.llms.lite_llm import LiteLLM
except Exception:
    LiteLLM = None  # type: ignore[assignment]


if LiteLLM is not None:
    _original_litellm_call = LiteLLM.call

    def _call_with_more_output_room(self, *args, **kwargs):
        max_tokens = os.environ.get("T_BENCH_LITELLM_MAX_TOKENS")
        if max_tokens and "max_tokens" not in kwargs:
            kwargs["max_tokens"] = int(max_tokens)
        return _original_litellm_call(self, *args, **kwargs)

    LiteLLM.call = _call_with_more_output_room


try:
    from terminal_bench.harness.harness import Harness
except Exception:
    Harness = None  # type: ignore[assignment]


if Harness is not None:

    async def _run_agent_without_timeout(
        self,
        trial_handler,
        session,
        logging_dir,
        timeout_sec,
        agent,
    ):
        loop = asyncio.get_event_loop()
        task = loop.run_in_executor(
            None,
            partial(
                agent.perform_task,
                instruction=trial_handler.instruction,
                session=session,
                logging_dir=logging_dir,
            ),
        )
        return await task

    Harness._run_agent_with_timeout = _run_agent_without_timeout
