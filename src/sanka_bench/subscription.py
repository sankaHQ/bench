"""Codex-managed authentication; only the native runner executes benchmark tools.

One account lease spans the child lifetime. Different provider API runs may run
alongside it, but independent subscription workers fail closed on contention.
"""

from __future__ import annotations

import fcntl
import json
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack, suppress
from pathlib import Path
from typing import Any

from sanka_bench.environment import isolated_environment
from sanka_bench.native_agent import Runner, tools

# Codex's model defaults require apply_patch, which this harness does not expose.
BASE_INSTRUCTIONS = (
    "You are completing a coding task through harness-provided tools. "
    "Use bench_exec to read, create, and edit files in the benchmark workspace "
    "using shell commands or Python. Only the advertised bench_* tools are available; "
    "do not assume host tools or an apply_patch executable exist. "
    "Follow the task and tool contracts, then report what you implemented and verified."
)


class Subscription:
    def __init__(self, deadline: float, executable: str | None = None) -> None:
        self.executable = executable
        self.deadline = deadline
        self.stack = ExitStack()
        self.events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.sequence = 0
        self.thread_id: str | None = None
        self.cursor = 0
        self.confirmed_settings: tuple[str, str] | None = None
        self.total: dict[str, int] = {}

    def __enter__(self) -> Subscription:
        try:
            home = Path.home() / ".sanka-bench" / "codex"
            if home.is_symlink() or home.parent.is_symlink() or not home.is_dir():
                raise ValueError("run sanka-bench login before subscription generation")
            fd = os.open(home / "session.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            lock = self.stack.enter_context(os.fdopen(fd, "r+"))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(
                    "subscription session busy; only one GPT worker is supported"
                ) from exc
            cwd = self.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="sanka-subscription-")
            )
            env = isolated_environment(os.environ, ("CODEX_CA_CERTIFICATE",))
            env.update(HOME=cwd, CODEX_HOME=str(home), PATH=os.environ.get("PATH", os.defpath))
            executable = self.executable or shutil.which("codex")
            if not executable:
                raise ValueError("Codex CLI is required for subscription generation")
            command = [executable]
            for option in (
                'forced_login_method="chatgpt"',
                'cli_auth_credentials_store="file"',
                'model_provider="openai"',
                'web_search="disabled"',
                "project_doc_max_bytes=0",
                "features.apps=false",
                "features.plugins=false",
                "features.remote_plugin=false",
                "features.skill_search=false",
                "features.shell_tool=false",
                "features.unified_exec=false",
                "features.shell_snapshot=false",
            ):
                command += ["-c", option]
            command += ["app-server"]
            self.process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
                pass_fds=(lock.fileno(),),
            )
            self.stack.callback(self._stop)
            threading.Thread(target=self._reader, daemon=True).start()
            self.rpc(
                "initialize",
                {
                    "clientInfo": {"name": "sanka-bench", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.send({"method": "initialized"})
            account = self.rpc("account/read", {"refreshToken": False})
            if (account.get("account") or {}).get("type") != "chatgpt":
                raise ValueError("subscription requires a ChatGPT login; API fallback is disabled")
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args: Any) -> None:
        self.stack.close()

    def _stop(self) -> None:
        if self.process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()

    def _reader(self) -> None:
        assert self.process.stdout
        try:
            for line in self.process.stdout:
                self.events.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self.events.put(None)

    def send(self, event: dict[str, Any]) -> None:
        assert self.process.stdin
        self.process.stdin.write(json.dumps(event) + "\n")
        self.process.stdin.flush()

    def next(self) -> dict[str, Any]:
        try:
            event = self.events.get(timeout=max(0, self.deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError("subscription response deadline exceeded") from None
        if event is None:
            raise RuntimeError("subscription managed process exited")
        return event

    def rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        while True:
            event = self.next()
            if event.get("id") == request_id and "method" not in event:
                if "error" in event:
                    raise RuntimeError(f"subscription {method} rejected")
                return dict(event["result"])
            self.check(event)

    @staticmethod
    def check(event: dict[str, Any]) -> None:
        method = event.get("method", "")
        if method.startswith("mcpServer/") or ("id" in event and "method" in event):
            raise RuntimeError("unexpected subscription tool or MCP server; isolation failed")
        if method == "error":
            raise RuntimeError("subscription provider error; preserve attempt")

    def __call__(self, runner: Runner) -> dict[str, Any]:
        if self.thread_id is None:
            started = self.rpc(
                "thread/start",
                {
                    "model": runner.model,
                    "modelProvider": "openai",
                    "allowProviderModelFallback": False,
                    "environments": [],
                    "ephemeral": True,
                    "approvalPolicy": "never",
                    "baseInstructions": BASE_INSTRUCTIONS,
                    "dynamicTools": [
                        {
                            "type": "function",
                            "name": "bench_" + spec["name"],
                            "description": (
                                "Runs in the harness-owned benchmark workspace. "
                                "bench_exec can write files there even though the Codex host "
                                "filesystem is read-only. " + spec["description"]
                            ),
                            "inputSchema": spec["parameters"],
                        }
                        for spec in tools(runner.sanka is not None)
                    ],
                },
            )
            if started.get("model") != runner.model or started.get("runtimeWorkspaceRoots"):
                raise ValueError("subscription model or execution environment mismatch")
            self.thread_id = started["thread"]["id"]
            runner.event("subscription_thread", model=started["model"], environment_access=False)
        messages = [
            item["content"] for item in runner.history[self.cursor :] if item.get("role") == "user"
        ]
        self.cursor = len(runner.history)
        self.sequence += 1
        self.send(
            {
                "id": self.sequence,
                "method": "turn/start",
                "params": {
                    "threadId": self.thread_id,
                    "effort": runner.effort,
                    "input": [{"type": "text", "text": "\n\n".join(messages)}],
                },
            }
        )
        before = dict(self.total)
        responses = 0
        verified_stop: str | None = None
        while True:
            event = self.next()
            method, params = event.get("method"), event.get("params", {})
            runner.event("subscription_event", event=event)
            if method == "thread/settings/updated":
                settings = params["threadSettings"]
                if settings["model"] != runner.model or settings["effort"] != runner.effort:
                    raise ValueError("subscription changed model or reasoning effort")
                self.confirmed_settings = (settings["model"], settings["effort"])
            elif method == "item/tool/call":
                if verified_stop is not None:
                    raise RuntimeError("subscription emitted another tool after verified stop")
                if params["threadId"] != self.thread_id:
                    raise ValueError("subscription tool call crossed thread boundary")
                call = {
                    "call_id": params["callId"],
                    "name": params["tool"].removeprefix("bench_"),
                    "arguments": json.dumps(params["arguments"]),
                }
                if call["name"] not in {spec["name"] for spec in tools(runner.sanka is not None)}:
                    raise ValueError("unexpected subscription tool")
                result = runner.dispatch(call)
                runner.event("tool_result", **call, result=result)
                if call["name"] == "verify" and runner.verified:
                    verified_stop = params.get("turnId")
                    if not isinstance(verified_stop, str) or not verified_stop:
                        raise ValueError("verified subscription tool omitted turn identity")
                    # Cancel while the provider is waiting for this tool result, before
                    # acknowledging it can trigger another inference request.
                    self.sequence += 1
                    self.send(
                        {
                            "id": self.sequence,
                            "method": "turn/interrupt",
                            "params": {"threadId": self.thread_id, "turnId": verified_stop},
                        }
                    )
                    runner.usage_complete = False  # Preserve unreported final usage as unknown.
                    runner.event("subscription_verified_stop", turn_id=verified_stop)
                    continue
                self.send(
                    {
                        "id": event["id"],
                        "result": {
                            "contentItems": [{"type": "inputText", "text": result}],
                            "success": True,
                        },
                    }
                )
            elif method == "thread/tokenUsage/updated":
                total = params["tokenUsage"]["total"]
                if total != self.total:
                    responses += 1
                    self.total = total
            elif method == "turn/completed":
                stopped = (
                    verified_stop is not None
                    and params.get("threadId") == self.thread_id
                    and params["turn"].get("id") == verified_stop
                    and params["turn"]["status"] == "interrupted"
                )
                if (
                    (verified_stop is not None and not stopped)
                    or (verified_stop is None and params["turn"]["status"] != "completed")
                    or self.confirmed_settings != (runner.model, runner.effort)
                    or not responses
                ):
                    runner.usage_complete = False
                    raise RuntimeError("subscription turn failed or omitted evidence")
                break
            elif "error" in event:
                raise RuntimeError("subscription request rejected")
            else:
                self.check(event)
        runner.turns += responses - 1
        runner.requests += responses - 1
        delta = {k: v - before.get(k, 0) for k, v in self.total.items()}
        if any(type(v) is not int or v < 0 for v in delta.values()):
            raise ValueError("invalid subscription token usage")
        return {
            "model": runner.model,
            "status": "completed",
            "output": [],
            "usage": {
                "input_tokens": delta["inputTokens"],
                "output_tokens": delta["outputTokens"],
                "input_tokens_details": {"cached_tokens": delta["cachedInputTokens"]},
                "output_tokens_details": {"reasoning_tokens": delta["reasoningOutputTokens"]},
            },
        }
