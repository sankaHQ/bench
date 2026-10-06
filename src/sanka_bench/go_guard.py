"""Compile Go candidates; observe Fiber requests inside an empty Linux sandbox."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

FIBER = "github.com/gofiber/fiber/v3"
PROBE = """package main
import (
    "bytes"
    "crypto/sha256"
    "encoding/json"
    "fmt"
    "io"
    "net/http/httptest"
    "os"
    "strings"
    "time"
    backend "MODULE"
    "github.com/gofiber/fiber/v3"
)
type request struct {
    Method string `json:"method"`
    Path string `json:"path"`
    Body json.RawMessage `json:"body"`
    Headers map[string]string `json:"headers"`
    Capture []string `json:"capture_headers"`
}
func benchWitness(data []byte)
func main() {
    var input request
    if err := json.NewDecoder(os.Stdin).Decode(&input); err != nil { panic(err) }
    app, err := backend.NewBenchApp("/database/case.sqlite3")
    if err != nil { panic(err) }
    if app == nil { panic("NewBenchApp returned nil") }
    body := input.Body
    if string(body) == "null" { body = nil }
    req := httptest.NewRequest(input.Method, "http://testserver"+input.Path, bytes.NewReader(body))
    req.Header.Set("Content-Type", "application/json")
    for key, value := range input.Headers { req.Header.Set(key, value) }
    response, err := app.Test(req, fiber.TestConfig{Timeout: 10*time.Second, FailOnTimeout: true})
    if err != nil { panic(err) }
    defer response.Body.Close()
    raw, err := io.ReadAll(io.LimitReader(response.Body, 8*1024*1024+1))
    if err != nil || len(raw) > 8*1024*1024 { panic("invalid or oversized response") }
    var value any
    if len(raw) > 0 {
        decoder := json.NewDecoder(bytes.NewReader(raw)); decoder.UseNumber()
        if decoder.Decode(&value) != nil { value = string(raw) }
    }
    result := map[string]any{"status": response.StatusCode, "body": value}
    if len(input.Capture) > 0 {
        headers := map[string]string{}
        for _, key := range input.Capture {
            headers[strings.ToLower(key)] = response.Header.Get(key)
        }
        result["headers"] = headers
    }
    encoded, err := json.Marshal(result)
    if err != nil { panic(err) }
    fmt.Println("SANKA_BENCH_RESPONSE="+string(encoded))
    benchWitness([]byte(fmt.Sprintf("SANKA_BENCH_ATTEST=%x\\n", sha256.Sum256(encoded))))
}
"""

# A dedicated syscall lets the external tracer distinguish the trusted probe's
# post-dispatch witness from candidate stdout on the campaign's pinned platform.
WITNESS = {
    "amd64": """#include "textflag.h"
TEXT ·benchWitness(SB),NOSPLIT,$0-24
    MOVQ $1, AX
    MOVQ $1, DI
    MOVQ data_base+0(FP), SI
    MOVQ data_len+8(FP), DX
    SYSCALL
    RET
""",
    "arm64": """#include "textflag.h"
TEXT ·benchWitness(SB),NOSPLIT,$0-24
    MOVD $64, R8
    MOVD $1, R0
    MOVD data_base+0(FP), R1
    MOVD data_len+8(FP), R2
    SVC
    RET
""",
}


def witness_pc(instructions: str, architecture: str) -> int:
    patterns = {"amd64": (r"0f05\s+SYSCALL", 2), "arm64": (r"d4000001\s+SVC", 4)}
    if architecture not in patterns:
        raise ValueError("unsupported native witness syscall architecture")
    opcode, size = patterns[architecture]
    addresses = re.findall(r"\b0x([0-9a-f]+)\s+" + opcode + r"\b", instructions)
    if len(addresses) != 1:
        raise ValueError("trusted dispatch witness syscall is missing or ambiguous")
    return int(addresses[0], 16) + size


def _bounded(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> str:
    """Kill the entire task-owned process group on timeout, including Go children."""
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=timeout)
        finally:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        output.seek(0)
        text = output.read(8 * 1024 * 1024 + 1).decode(errors="replace")
        if code or len(text) > 8 * 1024 * 1024:
            raise ValueError(f"Go build failed ({code}): {text[-4000:]}")
        return text


def prepare(workspace: Path, output: Path) -> Path:
    if sys.platform != "linux" or not shutil.which("bwrap") or not shutil.which("strace"):
        raise ValueError("Go evaluation requires Linux, bubblewrap and strace; no unsafe fallback")
    for path in workspace.rglob("*"):
        if path.is_symlink():
            raise ValueError("Go candidate must not contain symlinks")
        if path.is_file() and (
            path.suffix in {".s", ".S", ".syso"}
            or (path.suffix == ".go" and b"go:linkname" in path.read_bytes())
        ):
            raise ValueError("candidate assembly, object files and go:linkname are forbidden")
    if not (workspace / "go.sum").is_file():
        raise ValueError("Go candidate requires a frozen go.sum")
    go = shutil.which("go")
    if not go:
        raise ValueError("Go compiler is missing from the evaluator image")
    env = {
        "PATH": os.defpath + ":/usr/local/go/bin",
        "HOME": str(output),
        "GOCACHE": str(output / "cache"),
        "GOMODCACHE": "/opt/go-mod-cache",
        "CGO_ENABLED": "0",
        "GOWORK": "off",
        "GOTOOLCHAIN": "local",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "GOFLAGS": "-mod=readonly",
    }
    output.mkdir(parents=True, exist_ok=True)
    modules = _bounded([go, "list", "-m", "-json", "all"], cwd=workspace, env=env, timeout=120)
    decoder, remaining, records = json.JSONDecoder(), modules.strip(), []
    while remaining:
        record, end = decoder.raw_decode(remaining)
        records.append(record)
        remaining = remaining[end:].lstrip()
    if any(record.get("Replace") for record in records):
        raise ValueError("Go module replacements are forbidden")
    module = next((record["Path"] for record in records if record.get("Main")), "")
    if not re.fullmatch(r"[A-Za-z0-9._~/-]+", module):
        raise ValueError("invalid Go module path")
    fiber = next((record for record in records if record.get("Path") == FIBER), None)
    if not fiber or not fiber.get("Sum"):
        raise ValueError("candidate must use checksum-locked upstream Fiber v3")
    expected = os.environ.get("SANKA_BENCH_FIBER_VERSION")
    if not expected or fiber.get("Version") != expected:
        raise ValueError("candidate Fiber version does not match the pinned evaluator")
    sqlite = next((r for r in records if r.get("Path") == "modernc.org/sqlite"), None)
    if not sqlite or sqlite.get("Version") != os.environ.get("SANKA_BENCH_SQLITE_VERSION"):
        raise ValueError("candidate SQLite driver does not match the pinned evaluator")
    version = _bounded([go, "version"], cwd=workspace, env=env, timeout=10)
    expected_go = os.environ.get("SANKA_BENCH_GO_VERSION")
    if not expected_go or f" go{expected_go} " not in version:
        raise ValueError("Go compiler does not match the pinned evaluator")
    platform = os.environ.get("SANKA_BENCH_GO_PLATFORM", "linux/amd64")
    if platform not in {"linux/amd64", "linux/arm64"} or not version.strip().endswith(platform):
        raise ValueError("Go native-dispatch witness does not match the pinned Linux platform")
    architecture = platform.split("/")[1]
    _bounded([go, "mod", "verify"], cwd=workspace, env=env, timeout=120)
    _bounded([go, "build", "-trimpath", "./..."], cwd=workspace, env=env, timeout=120)
    _bounded(
        [go, "build", "-trimpath", "-o", str(output / "api"), "./cmd/api"],
        cwd=workspace,
        env=env,
        timeout=120,
    )
    probe_dir = workspace / "cmd/sanka-bench-probe"
    if probe_dir.exists():
        raise ValueError("candidate uses the evaluator-reserved probe directory")
    probe_dir.mkdir(parents=True)
    try:
        (probe_dir / "main.go").write_text(PROBE.replace("MODULE", module))
        (probe_dir / f"witness_{architecture}.s").write_text(WITNESS[architecture])
        binary = output / "probe"
        _bounded(
            [
                go,
                "build",
                "-buildmode=exe",
                "-trimpath",
                "-o",
                str(binary),
                "./cmd/sanka-bench-probe",
            ],
            cwd=workspace,
            env=env,
            timeout=120,
        )
        instructions = _bounded(
            [go, "tool", "objdump", "-s", "^main.benchWitness.abi0$", str(binary)],
            cwd=workspace,
            env=env,
            timeout=30,
        )
        binary.with_suffix(".witness.json").write_text(
            json.dumps(
                {
                    "pc": witness_pc(instructions, architecture),
                }
            )
        )
    finally:
        shutil.rmtree(probe_dir)
    return binary


def trace_violations(trace: str) -> tuple[list[str], list[str]]:
    processes, sockets = [], []
    started = False
    for line in trace.splitlines():
        if not started:
            if 'execve("/target",' in line and line.endswith("= 0"):
                started = True
            continue
        if re.search(r"\b(execve|execveat|fork|vfork)\(", line) or (
            re.search(r"\bclone3?\(", line) and "CLONE_THREAD" not in line
        ):
            processes.append("process creation or execution attempted")
        if re.search(r"\bconnect\(", line):
            sockets.append("outbound connection attempted")
    if not started:
        processes.append("target execution was not observed")
    return sorted(set(processes)), sorted(set(sockets))


def dispatch_witness(trace: str, response: str, symbol: dict[str, int]) -> bool:
    marker = "SANKA_BENCH_ATTEST=" + hashlib.sha256(response.encode()).hexdigest()
    matches = 0
    pending: dict[str, tuple[str, str]] = {}
    for line in trace.splitlines():
        event = re.fullmatch(r"(\d+)\s+\[([0-9a-f]+)\]\s+(.*)", line)
        if event:
            thread, pc, call = event.groups()
            if call.startswith("write(") and call.endswith(" <unfinished ...>"):
                pending[thread] = (pc, call.removesuffix(" <unfinished ...>"))
                continue
            if call.startswith("<... write resumed>"):
                start = pending.pop(thread, None)
                if start is None or start[0] != pc:
                    continue
                line = f"[{pc}] {start[1]}{call.removeprefix('<... write resumed>')}"
        address = re.search(r"\[([0-9a-f]+)\]", line)
        if (
            address
            and int(address[1], 16) == symbol["pc"]
            and f'write(1, "{marker}\\n", {len(marker) + 1}) = {len(marker) + 1}' in line
        ):
            matches += 1
    return matches == 1


def request(
    binary: Path, workspace: Path, database: Path, scenario: dict[str, Any]
) -> dict[str, Any]:
    if not str(scenario.get("path", "")).startswith("/"):
        raise ValueError("scenario requires a local HTTP path")
    with tempfile.TemporaryDirectory(prefix="go-serving-") as temp:
        root = Path(temp)
        trace = root / "trace"
        # Only the per-scenario database directory and candidate workspace are visible.
        argv = [
            "strace",
            "-f",
            "-qq",
            "-i",
            "-s",
            "256",
            "-o",
            str(trace),
            "-e",
            "trace=process,connect,write",
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            "--ro-bind",
            str(binary),
            "/target",
            "--bind",
            str(workspace),
            "/workspace",
            "--bind",
            str(database.parent),
            "/database",
            "--tmpfs",
            "/tmp",
            "--chdir",
            "/workspace",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "DATABASE_URL",
            "file:/database/case.sqlite3",
            "/target",
        ]
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=output,
                start_new_session=True,
                env={"PATH": os.defpath},
            )
            try:
                process.communicate(json.dumps(scenario).encode(), timeout=30)
            finally:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            output.seek(0)
            raw = output.read(8 * 1024 * 1024 + 1)
        if process.returncode or len(raw) > 8 * 1024 * 1024:
            raise ValueError(f"Go serving failed: {raw[-2000:].decode(errors='replace')}")
        lines = [
            line for line in raw.decode().splitlines() if line.startswith("SANKA_BENCH_RESPONSE=")
        ]
        if len(lines) != 1:
            raise ValueError("Go probe must return exactly one response")
        encoded = lines[0].split("=", 1)[1]
        response = json.loads(encoded)
        trace_text = trace.read_text()
        processes, sockets = trace_violations(trace_text)
        witnessed = dispatch_witness(
            trace_text, encoded, json.loads(binary.with_suffix(".witness.json").read_text())
        )
        return {
            "response": response,
            "native": {
                "app_is_fiber": witnessed,
                "fiber_dispatch_observed": witnessed,
                "endpoint_in_workspace": True,
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "forbidden_imports": [],
                "process_events": processes,
                "socket_events": sockets,
            },
        }
