"""Unmodified Claude Code transport; Sanka alone executes the advertised MCP tools."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from sanka_bench.environment import isolated_environment
from sanka_bench.native_agent import BudgetReached, Runner, tools
from sanka_bench.subscription import Subscription


class ClaudeSubscription(Subscription):
    """Reuse the owned subprocess lifecycle, queue and deadline of the Codex transport."""

    def __enter__(self) -> ClaudeSubscription:
        try:
            self.home = Path.home() / ".sanka-bench" / "claude"
            if self.home.is_symlink() or self.home.parent.is_symlink() or not self.home.is_dir():
                raise ValueError("run sanka-bench login --provider claude first")
            fd = os.open(self.home / "session.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            self.lock = self.stack.enter_context(os.fdopen(fd, "r+"))
            # ponytail: one account lease; independent workers must wait outside this transport.
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.cwd = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="sanka-claude-"))
            self.started = False
            return self
        except BaseException:
            self.stack.close()
            raise

    def start(self, runner: Runner) -> None:
        executable = self.executable or shutil.which("claude")
        if not executable:
            raise ValueError("Claude Code CLI is required")
        env = isolated_environment(os.environ)
        env.update(
            CLAUDE_CONFIG_DIR=str(self.home),
            PATH=os.environ.get("PATH", os.defpath),
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            DISABLE_AUTOUPDATER="1",
            CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION="false",
        )
        status = subprocess.run(
            [executable, "auth", "status"],
            env=env,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            timeout=min(30, runner.remaining()),
            check=True,
        )
        auth = json.loads(status.stdout)
        if auth.get("authMethod") != "claude.ai" or not auth.get("loggedIn"):
            raise ValueError("Claude subscription login required; API fallback disabled")
        names = ["mcp__bench__" + s["name"] for s in tools(runner.sanka is not None)]
        command = [
            executable,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--model",
            runner.model,
            "--effort",
            runner.effort,
            "--tools",
            "",
            "--allowedTools",
            ",".join(names),
            "--permission-mode",
            "dontAsk",
            "--strict-mcp-config",
            "--mcp-config",
            json.dumps({"mcpServers": {"bench": {"type": "sdk", "name": "bench"}}}),
            "--setting-sources",
            "",
            "--settings",
            json.dumps({"disableAllHooks": True}),
            "--disable-slash-commands",
            "--no-chrome",
            "--no-session-persistence",
            "--prompt-suggestions",
            "false",
            "--system-prompt",
            "Complete the task using only the advertised mcp__bench tools. "
            "They execute in the harness-owned workspace. Follow the supplied task contract.",
        ]
        self.process = subprocess.Popen(
            command,
            cwd=self.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
            pass_fds=(self.lock.fileno(),),
        )
        self.stack.callback(self._stop)
        threading.Thread(target=self._reader, daemon=True).start()
        self.send(
            {
                "type": "control_request",
                "request_id": "init",
                "request": {
                    "subtype": "initialize",
                    "hooks": {},
                    "skills": [],
                },
            }
        )
        self.started = True

    def mcp(self, runner: Runner, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("subtype") != "mcp_message" or request.get("server_name") != "bench":
            raise ValueError("unexpected Claude control request; isolation failed")
        message = request["message"]
        method = message.get("method")
        result: dict[str, Any]
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "bench", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": s["name"],
                        "description": s["description"],
                        "inputSchema": s["parameters"],
                    }
                    for s in tools(runner.sanka is not None)
                ]
            }
        elif method == "tools/call":
            params = message["params"]
            if params["name"] not in {s["name"] for s in tools(runner.sanka is not None)}:
                raise ValueError("unexpected Claude tool")
            if runner.verified:
                raise ValueError("tool received after verified completion")
            call = {"name": params["name"], "arguments": json.dumps(params.get("arguments", {}))}
            output = runner.dispatch(call)
            runner.event("tool_result", **call, result=output)
            result = {"content": [{"type": "text", "text": output}]}
        elif method in {"notifications/initialized", "ping"}:
            result = {}
        else:
            raise ValueError("unexpected Claude MCP method")
        return {"mcp_response": {"jsonrpc": "2.0", "id": message.get("id"), "result": result}}

    def __call__(self, runner: Runner) -> dict[str, Any]:
        if not self.started:
            self.start(runner)
        messages = [h["content"] for h in runner.history[self.cursor :] if h.get("role") == "user"]
        self.cursor = len(runner.history)
        self.send({"type": "user", "message": {"role": "user", "content": "\n\n".join(messages)}})
        responses: dict[str, dict[str, Any]] = {}

        def observe(message: dict[str, Any]) -> None:
            if message.get("model") != runner.model:
                raise ValueError("Claude model fallback detected")
            if message["id"] not in responses:
                # Count on arrival so quota, timeout and tool-budget exits retain evidence.
                runner.requests += bool(responses)
                runner.turns += 1
                responses[message["id"]] = dict(message["usage"])

        initialized = False
        current_id = None
        final_usage = None
        while True:
            event = self.next()
            runner.event("claude_subscription_event", event=event)
            kind = event.get("type")
            if (
                kind == "rate_limit_event"
                and event.get("rate_limit_info", {}).get("status") == "rejected"
            ):
                raise RuntimeError("Claude subscription limit reached; pause admission")
            if kind == "system" and event.get("subtype") == "api_retry":
                raise RuntimeError("Claude provider retry requested; pause admission")
            if kind == "control_request":
                data = self.mcp(runner, event["request"])
                if runner.verified:
                    # No extra inference after verification. Usage may lack its final delta.
                    runner.usage_complete = False
                    self._stop()
                    break
                if runner.tool_calls >= runner.max_turns:
                    # The last permitted tool already ran. Do not buy another
                    # model response merely to discover the exhausted tool budget.
                    runner.usage_complete = False
                    raise BudgetReached("tool_calls")
                self.send(
                    {
                        "type": "control_response",
                        "response": {
                            "subtype": "success",
                            "request_id": event["request_id"],
                            "response": data,
                        },
                    }
                )
            elif kind == "control_response":
                if event["response"].get("subtype") == "error":
                    raise RuntimeError("Claude initialization rejected")
            elif kind == "system" and event.get("subtype") == "init":
                allowed = {"mcp__bench__" + s["name"] for s in tools(runner.sanka is not None)}
                if (
                    event.get("model") != runner.model
                    or set(event.get("tools", [])) != allowed
                    or event.get("apiKeySource") != "none"
                    or event.get("plugins")
                    or event.get("skills")
                    or event.get("mcp_servers") != [{"name": "bench", "status": "connected"}]
                ):
                    raise ValueError("Claude model/tool isolation mismatch")
                initialized = True
            elif kind == "assistant":
                message = event["message"]
                observe(message)
                if runner.turns > runner.max_turns:
                    runner.usage_complete = False
                    raise BudgetReached("model_turns")
            elif kind == "stream_event":
                data = event["event"]
                if data["type"] == "message_start":
                    message = data["message"]
                    observe(message)
                    current_id = message["id"]
                elif data["type"] == "message_delta":
                    if current_id is None:
                        raise ValueError("Claude usage delta without message")
                    responses[current_id].update(data["usage"])
                    runner.event(
                        "claude_usage",
                        message_id=current_id,
                        model=runner.model,
                        usage=responses[current_id],
                    )
            elif kind == "result":
                if event.get("is_error"):
                    raise RuntimeError(
                        "Claude request failed: "
                        + str(event.get("result", event.get("errors", "")))[:600]
                    )
                if set(event.get("modelUsage", {})) != {runner.model}:
                    raise ValueError(
                        "Claude used auxiliary models; preserve qualification evidence"
                    )
                final_usage = event.get("usage")
                if event.get("subtype") != "success":
                    raise RuntimeError("Claude turn did not complete")
                break
        if not initialized and self.thread_id is None:
            raise ValueError("Claude omitted model/tool initialization evidence")
        self.thread_id = "initialized"
        if not responses:
            raise ValueError("Claude omitted response usage")
        usage = {
            k: sum(u[k] for u in responses.values())
            for k in (
                "input_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
                "output_tokens",
            )
        }
        if final_usage is not None and any(final_usage.get(k) != v for k, v in usage.items()):
            raise ValueError("Claude final usage does not reconcile with streamed usage")
        if any(type(v) is not int or v < 0 for v in usage.values()):
            raise ValueError("invalid Claude usage")
        runner.turns -= 1  # Runner.request adds the successfully returned response.
        return {
            "model": runner.model,
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": ""}}],
            "usage": {
                "prompt_tokens": usage["input_tokens"]
                + usage["cache_read_input_tokens"]
                + usage["cache_creation_input_tokens"],
                "completion_tokens": usage["output_tokens"],
                "prompt_tokens_details": {"cached_tokens": usage["cache_read_input_tokens"]},
            },
        }
