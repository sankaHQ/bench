"""Small direct-API runner. Own the lifecycle; ask the model only for remaining work.

No evaluator imports, hidden scenarios, model SDK, session service or agent CLI.
The caller supplies sandboxed execution and the existing scaffold promotion rule.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

VERSION = "sanka-native/1"
ROUTES = {
    "openai": ("https://api.openai.com/v1/responses", "OPENAI_API_KEY"),
    "fireworks": ("https://api.fireworks.ai/inference/v1/chat/completions", "FIREWORKS_API_KEY"),
}
MAX_OUTPUT_TOKENS = 8192
MAX_CONTEXT_BYTES = 120_000
MAX_TOOL_OUTPUT = 6000
MAX_REPAIRS = 3


def version() -> str:
    return VERSION + "+" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def post(url: str, key: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    # Never forward credentials to a redirect or an ambient proxy.
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("provider response is not an object")
    return data


def tools(with_sanka: bool) -> list[dict[str, Any]]:
    result = [
        {
            "type": "function",
            "name": "exec",
            "strict": True,
            "description": "Inspect, edit or test project files with a shell command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        }
    ]
    result.append(
        {
            "type": "function",
            "name": "read",
            "strict": True,
            "description": (
                "Read a bounded line range from a workspace file or saved tool output. "
                "Reuse saved output "
                "instead of rerunning commands. Does not invalidate verification."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start": {"type": "integer"},
                    "lines": {"type": "integer"},
                },
                "required": ["path", "start", "lines"],
                "additionalProperties": False,
            },
        }
    )
    if with_sanka:
        result.append(
            {
                "type": "function",
                "name": "verify",
                "strict": True,
                "description": (
                    "Verify public scenarios and register completion with the harness. "
                    "Use this tool after repairs; shell verification does not register completion. "
                    "Pass a workspace Python seed script (.py) when scenarios need initial rows. "
                    "Django is configured when the script runs; JSON fixtures are not scripts. "
                    "Does not regenerate the candidate."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"seed": {"type": ["string", "null"]}},
                    "required": ["seed"],
                    "additionalProperties": False,
                },
            }
        )
    return result


def compact(text: str, command: str) -> dict[str, Any]:
    """Decode the CLI's versioned key=JSON wire format, never infer success from prose."""
    lines = text.strip().splitlines()
    if not lines or not lines[0].startswith(f"sanka-compact/v1 {command} "):
        raise ValueError(f"{command} requires a CLI supporting --compact-dsl")
    header = lines[0].split()
    if len(header) != 4:
        raise ValueError("invalid compact header")
    data: dict[str, Any] = {"outcome": header[2], "migration_state": header[3]}
    for line in lines[1:]:
        key, sep, value = line.partition("=")
        if not sep or key in data:
            raise ValueError("invalid or duplicate compact field")
        data[key] = json.loads(value)
    error = data.get("error")
    if (
        command == "verify"
        and isinstance(error, dict)
        and error.get("code") == ("SANKA_EXTENSION_REPLAY_MISMATCH")
    ):
        details = error.get("details")
        if (
            not isinstance(details, dict)
            or details.get("schema") != "sanka-verify-replay/v1"
            or details.get("ok") is not False
        ):
            raise ValueError("invalid replay mismatch details")
        # Failed CLI replays wrap the same verification report in error.details.
        for key in ("ok", "summary", "failures", "warnings", "coverage_issues"):
            if key in details:
                data[key] = details[key]
    return data


class BudgetReached(Exception):
    pass


class Runner:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        effort: str,
        key: str,
        prompt: str,
        workspace: Path,
        artifacts: Path,
        execute: Callable[..., subprocess.CompletedProcess[str]],
        promote: Callable[[], dict[str, str]],
        sanka: Path | None,
        target: str,
        max_turns: int,
        wall_seconds: int,
        price_in: float | None = None,
        price_out: float | None = None,
        price_cached: float | None = None,
        max_cost: float | None = None,
        expected_model: str | None = None,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
        max_context_bytes: int = MAX_CONTEXT_BYTES,
        exchange: Callable[[Runner], dict[str, Any]] | None = None,
    ) -> None:
        for name, value in (
            ("max_output_tokens", max_output_tokens),
            ("max_context_bytes", max_context_bytes),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.exchange = exchange
        self.max_output_tokens = max_output_tokens
        self.max_context_bytes = max_context_bytes
        self.provider, self.model, self.effort, self.key = provider, model, effort, key
        self.expected_model = expected_model or model
        self.workspace, self.artifacts = workspace, artifacts
        self.execute, self.promote, self.sanka, self.target = execute, promote, sanka, target
        self.max_turns, self.price_in, self.price_out, self.max_cost = (
            max_turns,
            price_in,
            price_out,
            max_cost,
        )
        if price_cached is not None and (
            type(price_cached) not in {int, float}
            or not math.isfinite(price_cached)
            or price_in is None
            or not 0 <= price_cached <= price_in
        ):
            raise ValueError("price_cached must be finite and between zero and price_in")
        self.price_cached = price_cached
        self.started = time.monotonic()
        self.deadline = self.started + wall_seconds
        self.events: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        self.usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "reasoning_output_tokens": 0,
        }
        self.usage_complete = True
        self.missing_details: set[str] = set()
        self.requests = self.retries = self.turns = self.tool_calls = self.commands = 0
        self.repairs = 0
        self.stages: dict[str, Any] = {}
        self.generated: dict[str, str] = {}
        self.verified = False
        self.seed: str | None = None
        self.verification_summary: str | None = None
        self.artifacts.mkdir(parents=True, exist_ok=True)
        (self.artifacts / "tools").mkdir(exist_ok=True)

    def event(self, kind: str, **data: Any) -> None:
        item = {"type": kind, "elapsed_seconds": time.monotonic() - self.started, **data}
        self.events.append(item)
        with (self.artifacts / "events.jsonl").open("a") as output:
            output.write(json.dumps(item) + "\n")

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BudgetReached("wall_clock")
        return remaining

    def command(
        self, argv: list[str], *, phase: str = "model_tool"
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        self.remaining()
        self.commands += 1
        started = time.monotonic()
        timed_out = False
        self.event("command_start", number=self.commands, argv=argv, phase=phase)
        try:
            outcome = self.execute(argv, timeout=min(120, self.remaining()))
        except OSError as exc:
            self.event(
                "command_end",
                number=self.commands,
                phase=phase,
                duration_seconds=time.monotonic() - started,
                failure_category="infrastructure_failure",
                error_type=type(exc).__name__,
            )
            raise
        except subprocess.TimeoutExpired as exc:
            timed_out = True

            def text(value: Any) -> str:
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""

            outcome = subprocess.CompletedProcess(argv, 124, text(exc.stdout), text(exc.stderr))
        raw = outcome.stdout + ("\nstderr:\n" + outcome.stderr if outcome.stderr else "")
        path = self.artifacts / "tools" / f"{self.commands:04d}.txt"
        path.write_text(raw)
        self.event(
            "command_end",
            number=self.commands,
            exit_code=outcome.returncode,
            phase=phase,
            timed_out=timed_out,
            failure_category="command_timeout" if timed_out else None,
            duration_seconds=time.monotonic() - started,
            output_path=str(path),
            output_bytes=len(raw.encode()),
        )
        body = raw
        if timed_out:
            self.remaining()  # Preserve overall wall-budget exhaustion before parsing output.
        if len(raw) > MAX_TOOL_OUTPUT:
            body = raw[: MAX_TOOL_OUTPUT // 2] + "\n[truncated]\n" + raw[-MAX_TOOL_OUTPUT // 2 :]
        return outcome, f"exit={outcome.returncode} output={path}\n{body}"

    def lifecycle(self, stage: str, arguments: list[str]) -> tuple[dict[str, Any], str]:
        outcome, summary = self.command(
            [
                str(self.sanka),
                stage,
                *arguments,
                "--extension-env",
                "PYTHONPATH",
                "--extension-env",
                "PATH",
                "--extension-env",
                "HOME",
                "--extension-env",
                "TMPDIR",
                "--compact-dsl",
            ],
            phase=stage,
        )
        try:
            data = compact(outcome.stdout, stage)
        except ValueError:
            self.stages[stage] = {
                "ok": False,
                "exit_code": outcome.returncode,
                "failure_category": "infrastructure_failure",
            }
            self.event(
                "lifecycle", stage=stage, ok=False, failure_category="infrastructure_failure"
            )
            raise RuntimeError("invalid lifecycle protocol; inspect saved command output") from None
        ok = outcome.returncode == 0 and data["outcome"] == "success"
        failure_category = None if ok else "infrastructure_failure"
        if stage == "verify":
            # Coverage is separate from parity: matching all-404 responses is not proof.
            if data.get("error", {}).get("code") == "SANKA_EXTENSION_REPLAY_INVALID" and (
                (
                    data["error"].get("message", "").startswith("candidate entrypoint not found: ")
                    and not (self.workspace / "target_app.py").exists()
                )
                or (
                    data["error"].get("message", "").startswith("candidate[")
                    and "] process failed: " in data["error"]["message"]
                    and str(self.workspace / "target_app.py") in data["error"]["message"]
                )
            ):
                failure_category = "candidate_failure"
            elif data.get("ok") is False:
                counts = data.get("summary", {})
                source_only = counts.get("source_expectation_mismatches", 0) > 0 and not any(
                    counts.get(key, 0)
                    for key in (
                        "status_mismatches",
                        "body_mismatches",
                        "header_mismatches",
                        "database_mismatches",
                        "non_native",
                    )
                )
                failure_category = "coverage_incomplete" if source_only else "candidate_failure"
            elif data.get("warnings") or data.get("coverage_issues"):
                failure_category = "coverage_incomplete"
            elif data.get("ok") is not True:
                failure_category = "infrastructure_failure"
            if self.events[-1].get("timed_out"):
                failure_category = "infrastructure_failure"
            ok = ok and data.get("ok") is True and failure_category is None
            if not ok:
                advice = {
                    "coverage_incomplete": "Supply the missing seed/auth scenario prerequisite; "
                    "do not repair target code just to silence coverage warnings.",
                    "candidate_failure": "Repair the reported candidate mismatches.",
                    "infrastructure_failure": "Inspect the saved command output for execution "
                    "or protocol failure before changing the candidate.",
                }[failure_category or "infrastructure_failure"]
                summary += (
                    f"\nHarness verification not accepted ({failure_category}): {advice} "
                    "Call the verify tool with the seed path if needed. "
                    "A CLI success alone does not satisfy this gate."
                )
        self.stages[stage] = {
            "ok": ok,
            "exit_code": outcome.returncode,
            "data": data,
            "failure_category": failure_category,
        }
        self.event("lifecycle", stage=stage, ok=ok, result=data, failure_category=failure_category)
        if stage == "verify" and failure_category == "infrastructure_failure":
            raise RuntimeError("verification infrastructure failed; inspect saved command output")
        return data, summary

    def bootstrap(self) -> str:
        summaries = []
        for stage, arguments in (
            ("scan", ["."]),
            (
                "plan",
                [
                    ".",
                    "--to",
                    self.target,
                    "--strategy",
                    "native",
                    "--generation",
                    "minimal",
                    "--package-manager",
                    "pip",
                    "--output",
                    f".sanka/output/{self.target}",
                ],
            ),
        ):
            _, summary = self.lifecycle(stage, arguments)
            summaries.append(summary)
            if not self.stages[stage]["ok"]:
                return "\n".join(summaries)
        plan_hash = self.stages["plan"]["data"].get("plan_hash")
        if not isinstance(plan_hash, str) or not plan_hash.startswith("sha256:"):
            raise ValueError("plan did not return a reviewed core plan hash")
        _, summary = self.lifecycle(
            "apply",
            [
                "--root",
                ".",
                "--plan-hash",
                plan_hash,
                *(
                    ["--bench-candidate", ".sanka/agent-candidate"]
                    if self.target == "fastapi"
                    else []
                ),
            ],
        )
        summaries.append(summary)
        if (
            not self.stages["apply"]["ok"]
            and self.stages["apply"]["data"].get("error", {}).get("code")
            == "SANKA_EXTENSION_READINESS"
        ):
            summaries.append(
                "Readiness blocked generation. Implement the missing target, then verify."
            )
            return "\n".join(summaries)
        if self.stages["apply"]["ok"]:
            # Test the generated tree before promoting it: promotion changes the source hash.
            _, summary = self.lifecycle("test", [".", "--to", self.target])
            summaries.append(summary)
            self.generated = self.promote()
        summaries.append(self.verify(None))
        return "\n".join(summaries)

    def verify(self, seed: str | None) -> str:
        if seed is not None:
            path = (self.workspace / seed).resolve()
            if not path.is_relative_to(self.workspace.resolve()) or not path.is_file():
                raise ValueError("seed must be an existing workspace file")
            if path.suffix != ".py":
                raise ValueError("seed must be a Python .py script, not a JSON fixture")
        if seed == self.seed and self.verification_summary is not None:
            return self.verification_summary
        self.seed = seed
        self.verified = False
        _, summary = self.lifecycle(
            "verify",
            [
                ".",
                "--to",
                self.target,
                "--scenarios",
                "public-tests/scenarios.json",
                "--candidate",
                ".",
                "--entrypoint",
                "target_app.py",
                "--db-env",
                "BENCH_DB_PATH",
                "--edge-probes",
                *(["--seed", seed] if seed else []),
            ],
        )
        self.verified = self.stages["verify"]["ok"]
        self.verification_summary = summary
        return summary

    def payload(self) -> dict[str, Any]:
        specs = tools(self.sanka is not None)
        if self.provider == "openai":
            return {
                "model": self.model,
                "input": self.history,
                "tools": specs,
                "store": False,
                "include": ["reasoning.encrypted_content"],
                "reasoning": {"effort": self.effort},
                "parallel_tool_calls": False,
                "max_output_tokens": self.max_output_tokens,
            }
        return {
            "model": self.model,
            "messages": self.history,
            "tools": [
                {"type": "function", "function": {k: v for k, v in spec.items() if k != "type"}}
                for spec in specs
            ],
            "reasoning_effort": self.effort,
            "max_tokens": self.max_output_tokens,
        }

    def cost(self) -> float | None:
        if not self.usage_complete or self.price_in is None or self.price_out is None:
            return None
        # price_in must cover uncached input including any cache-write premium.
        # Discount only cache reads actually reported; future requests reserve full input.
        cached = self.usage["cache_read_input_tokens"]
        discount = 0 if self.price_cached is None else cached * (self.price_in - self.price_cached)
        return (
            self.usage["input_tokens"] * self.price_in
            + self.usage["output_tokens"] * self.price_out
            - discount
        ) / 1_000_000

    def request(self) -> dict[str, Any]:
        payload = self.payload()
        size = len(json.dumps(payload).encode())
        if size > self.max_context_bytes:
            raise BudgetReached("context_bytes")
        if self.max_cost is not None:
            assert self.price_in is not None and self.price_out is not None
            reserve = (
                (size + 1024) * self.price_in + self.max_output_tokens * self.price_out
            ) / 1e6
            if (self.cost() or 0) + reserve > self.max_cost:
                raise BudgetReached("cost_reservation")
        for attempt in range(3):
            timeout = self.remaining()
            self.requests += 1
            self.event(
                "request",
                number=self.requests,
                model=self.model,
                provider=self.provider,
                reasoning_effort=self.effort,
                context_bytes=size,
                max_output_tokens=self.max_output_tokens,
            )
            request_started = time.monotonic()
            request_status = "failed"
            request_duration: float | None = None
            try:
                result = (
                    self.exchange(self)
                    if self.exchange
                    else post(ROUTES[self.provider][0], self.key, payload, timeout)
                )
                self.turns += 1
                request_status = "received"
                return result
            except urllib.error.HTTPError as exc:
                # Retry explicit rate rejection only, never ambiguous timeout/5xx generation.
                request_duration = time.monotonic() - request_started
                request_status = "rate_limited" if exc.code == 429 else "provider_error"
                self.event(
                    "provider_error", status=exc.code, failure_category="infrastructure_failure"
                )
                if exc.code >= 500:
                    self.usage_complete = False
                if exc.code != 429 or attempt == 2:
                    raise RuntimeError(f"provider HTTP {exc.code}") from None
                delay = max(2.0**attempt, float(exc.headers.get("Retry-After", 0)))
                if delay > 30 or delay >= self.remaining():
                    raise RuntimeError("rate limit exceeds bounded retry window") from None
                self.retries += 1
                self.event("provider_retry", status=429, delay=delay)
                time.sleep(delay)
            except RuntimeError:
                if self.exchange:
                    self.usage_complete = False
                raise
            except TimeoutError:
                request_status = "provider_timeout"
                self.usage_complete = False  # The in-flight response may still be billed.
                self.remaining()  # Classify our own deadline as a budget stop, preserving output.
                raise
            except (OSError, ValueError):
                self.usage_complete = False  # ambiguous response: never claim zero billed tokens
                raise
            except KeyboardInterrupt:
                self.usage_complete = False
                raise
            finally:
                if self.exchange and request_status != "received":
                    self.usage_complete = False
                self.event(
                    "request_end",
                    number=self.requests,
                    status=request_status,
                    duration_seconds=(
                        time.monotonic() - request_started
                        if request_duration is None
                        else request_duration
                    ),
                )
        raise AssertionError("unreachable")

    def receive(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        self.event("response", response=response)
        usage = response.get("usage")
        if not isinstance(usage, dict):
            self.usage_complete = False
            raise ValueError("provider omitted token usage")
        is_openai = self.provider == "openai"
        for name, field in (
            ("input_tokens", "input_tokens" if is_openai else "prompt_tokens"),
            ("output_tokens", "output_tokens" if is_openai else "completion_tokens"),
        ):
            value = usage.get(field)
            if type(value) is not int or value < 0:
                self.usage_complete = False
                raise ValueError("provider omitted valid token usage")
            self.usage[name] += value
        cached = usage.get("input_tokens_details" if is_openai else "prompt_tokens_details") or {}
        reasoning = (
            usage.get("output_tokens_details" if is_openai else "completion_tokens_details") or {}
        )
        if not isinstance(cached, dict) or not isinstance(reasoning, dict):
            raise ValueError("invalid token details")
        for name, value in (
            ("cache_read_input_tokens", cached.get("cached_tokens")),
            ("reasoning_output_tokens", reasoning.get("reasoning_tokens")),
        ):
            if value is None:
                self.missing_details.add(name)
                continue
            total = (
                usage["input_tokens" if is_openai else "prompt_tokens"]
                if name == "cache_read_input_tokens"
                else usage["output_tokens" if is_openai else "completion_tokens"]
            )
            if type(value) is not int or not 0 <= value <= total:
                self.usage_complete = False
                raise ValueError("invalid token detail")
            self.usage[name] += value
        if response.get("model") != self.expected_model:
            raise ValueError("provider returned a different model; qualify the exact route first")
        if is_openai:
            # Keep complete reasoning items and call IDs, including encrypted content.
            output = response.get("output", [])
            if response.get("status") == "incomplete":
                raise BudgetReached("incomplete_response")
            if (
                response.get("status") != "completed"
                or not isinstance(output, list)
                or not all(isinstance(item, dict) for item in output)
            ):
                raise ValueError("invalid or failed provider response")
            self.history.extend(output)
            return [item for item in output if item.get("type") == "function_call"]
        choice = response["choices"][0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("invalid chat response")
        if choice.get("finish_reason") not in {"stop", "tool_calls"}:
            raise BudgetReached("incomplete_response")
        message = choice["message"]
        self.history.append(message)  # includes reasoning_content for interleaved thinking
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list) or not all(
            isinstance(item, dict) and isinstance(item.get("function"), dict) for item in calls
        ):
            raise ValueError("invalid chat tool calls")
        return [{"call_id": item["id"], **item["function"]} for item in calls]

    def dispatch(self, call: dict[str, Any]) -> str:
        if self.tool_calls >= self.max_turns:
            raise BudgetReached("tool_calls")
        self.tool_calls += 1
        try:
            arguments = json.loads(call["arguments"])
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
            if call["name"] == "read" and set(arguments) == {"path", "start", "lines"}:
                path, start, count = arguments["path"], arguments["start"], arguments["lines"]
                if not isinstance(path, str) or type(start) is not int or type(count) is not int:
                    raise ValueError("read requires a path and integer line range")
                if start < 1 or not 1 <= count <= 200:
                    raise ValueError("start must be positive and lines between 1 and 200")
                file = (self.workspace / path).resolve()
                if not file.is_file() or not any(
                    file.is_relative_to(root.resolve())
                    for root in (self.workspace, self.artifacts / "tools")
                ):
                    raise ValueError("read requires an existing workspace file")
                # Bound each line as well as the response; a minified file may be one huge line.
                result = ""
                with file.open(errors="replace") as stream:
                    for number in range(1, start + count):
                        self.remaining()
                        line = stream.readline(MAX_TOOL_OUTPUT + 1)
                        if not line:
                            break
                        if len(line) > MAX_TOOL_OUTPUT:
                            raise ValueError(
                                "line exceeds output bound; extract a focused field with exec"
                            )
                        if number >= start:
                            excerpt = f"{number}: {line}"
                            if len(result) + len(excerpt) > MAX_TOOL_OUTPUT:
                                return result + f"\n[continue at line {number}]"
                            result += excerpt
                return result
            if call["name"] == "exec" and set(arguments) == {"command"}:
                command = arguments["command"]
                if not isinstance(command, str) or not command.strip() or "\0" in command:
                    raise ValueError("command must be a nonempty string without NUL")
                self.verified = False  # Never reuse verification after an arbitrary command.
                self.verification_summary = None
                return self.command(["/bin/sh", "-c", command])[1]
            if call["name"] == "verify" and self.sanka and set(arguments) == {"seed"}:
                seed = arguments["seed"]
                if seed is not None and not isinstance(seed, str):
                    raise ValueError("seed must be a path or null")
                return self.verify(seed)
            raise ValueError("unknown tool or arguments")
        except (ValueError, KeyError) as exc:
            return f"tool error: {exc}"

    def verification_failure_key(self) -> str:
        # Output/report paths change on every replay; they are not repair progress.
        data = self.stages.get("verify", {}).get("data", {})
        return json.dumps(
            {
                key: data.get(key)
                for key in ("ok", "summary", "failures", "warnings", "coverage_issues")
            },
            sort_keys=True,
        )

    def run(self) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        last_failed_summary: str | None = None
        reason = "completed_unverified"
        error = False
        self.event(
            "start",
            version=version(),
            provider=self.provider,
            model=self.model,
            effort=self.effort,
            tools=tools(self.sanka is not None),
        )
        try:
            if self.sanka:
                summary = self.bootstrap()
                self.history.append(
                    {
                        "role": "user",
                        "content": (
                            "Sanka results follow. Reuse generated files; repair only gaps. "
                            "Do not repeat scan/plan/apply. The scaffold test result is retained. "
                            "Call the verify tool after repairs, not exec with a shell verify "
                            "command. Public replay is not a benchmark score. "
                            "If scenarios need initial rows, create a "
                            "seed from source/public information and pass its path to verify.\n"
                            + summary
                        ),
                    }
                )
            if self.verified:
                reason = "verified"
            else:
                for _ in range(self.max_turns):
                    self.remaining()
                    calls = self.receive(self.request())
                    if not calls:
                        if self.sanka and not self.verified:
                            summary = self.dispatch(
                                {"name": "verify", "arguments": json.dumps({"seed": self.seed})}
                            )
                            if not self.verified:
                                self.repairs += 1
                                failure_key = self.verification_failure_key()
                                if (
                                    failure_key == last_failed_summary
                                    or self.repairs >= MAX_REPAIRS
                                ):
                                    reason = "verification_failed"
                                    break
                                last_failed_summary = failure_key
                                self.history.append({"role": "user", "content": summary})
                                continue
                        reason = "verified" if self.verified else "completed_unverified"
                        break
                    repeated_verification = False
                    seen: set[str] = set()
                    for call in calls:
                        call_id = call.get("call_id")
                        if not isinstance(call_id, str) or not call_id or call_id in seen:
                            raise ValueError("invalid or duplicate tool call ID")
                        seen.add(call_id)
                        result = self.dispatch(call)
                        self.event("tool_result", call_id=call_id, name=call["name"], result=result)
                        self.history.append(
                            {"type": "function_call_output", "call_id": call_id, "output": result}
                            if self.provider == "openai"
                            else {"role": "tool", "tool_call_id": call_id, "content": result}
                        )
                        if call["name"] == "verify" and not self.verified:
                            failure_key = self.verification_failure_key()
                            repeated_verification = failure_key == last_failed_summary
                            last_failed_summary = failure_key
                    if (
                        repeated_verification
                        and self.verification_summary is not None
                        and not self.verified
                    ):
                        reason = "verification_failed"
                        break
                    if self.verified:
                        reason = "verified"
                        break  # No paid final-summary turn after verified completion.
                else:
                    reason = "model_turns"
        except BudgetReached as exc:
            reason = str(exc)
        except KeyboardInterrupt:
            reason, error = "interrupted", True
            raise
        except (OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
            # No response body / URL / auth headers in exceptions or user-facing logs.
            reason, error = f"provider_or_runner_error:{type(exc).__name__}", True
            self.event(
                "error",
                category=type(exc).__name__,
                message=str(exc).replace(self.key, "[redacted]")[:1000]
                if self.key
                else str(exc)[:1000],
            )
        finally:
            phase_seconds: dict[str, float] = {}
            for event in self.events:
                if event["type"] in {"command_end", "request_end"}:
                    phase = event.get("phase", "provider")
                    phase_seconds[phase] = phase_seconds.get(phase, 0.0) + event["duration_seconds"]
            stats: dict[str, Any] = {
                "type": "result",
                "subtype": "native-error" if error else "native-" + reason,
                "is_error": error,
                "result": reason,
                "usage_complete": self.usage_complete,
                "missing_usage_details": sorted(self.missing_details),
                "failure_category": "infrastructure_failure"
                if error
                else (
                    self.stages.get("verify", {}).get("failure_category")
                    if reason == "verification_failed"
                    else None
                ),
                "num_turns": self.turns,
                "duration_ms": (time.monotonic() - self.started) * 1000,
                "phase_seconds": phase_seconds,
                **{
                    k: v if self.usage_complete and k not in self.missing_details else None
                    for k, v in self.usage.items()
                },
                "total_tokens": self.usage["input_tokens"] + self.usage["output_tokens"]
                if self.usage_complete
                else None,
                "cost_usd": self.cost(),
                "cost_basis": "subscription-no-marginal-cost"
                if self.exchange
                else "provided-rates-cache-aware-upper-estimate"
                if self.price_cached is not None
                else "provided-rates-uncached-upper-estimate"
                if self.price_in is not None
                else "unpriced-provider-usage",
                "work": {
                    "observed_model_responses": self.turns,
                    "tool_calls": self.tool_calls,
                    "provider_api_requests": self.requests,
                    "provider_retries": self.retries,
                    "commands": self.commands,
                    "repair_rounds": self.repairs,
                },
                "stages": self.stages,
                "generated_files": self.generated,
                "verified": self.verified,
                "limits": {
                    "max_output_tokens": self.max_output_tokens,
                    "max_context_bytes": self.max_context_bytes,
                },
            }
            checkpoint = self.artifacts / "state.tmp"
            checkpoint.write_text(json.dumps({"stats": stats, "history": self.history}))
            checkpoint.replace(self.artifacts / "state.json")
            self.event("result", **{k: v for k, v in stats.items() if k != "type"})
        transcript = "\n".join(json.dumps(event) for event in self.events) + "\n"
        return subprocess.CompletedProcess([VERSION], int(error), transcript, ""), stats


if __name__ == "__main__":
    import sys

    if sys.argv[1:] != ["--version"]:
        raise SystemExit("Use scripts/run_agent_candidate.py --agent sanka-native")
    print(version())
