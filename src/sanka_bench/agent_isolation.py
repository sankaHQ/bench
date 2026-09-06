"""OS-enforced file access for an agent and every child it starts.

Only fixture/config/temp directories are writable. System tools and explicitly
selected runtimes are readable; the evaluator and other runs are never mounted
or allowed. Network access remains available to the model provider.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path


def claude_arguments(*, with_skill: bool) -> list[str]:
    tools = "Bash,Read,Write,Edit,Skill"
    settings = {
        "disableAllHooks": True,
        "autoMemoryEnabled": False,
        "disableBundledSkills": True,
        "claudeMdExcludes": ["**"],
        "skillOverrides": {"doctor": "off"},
    }
    arguments = [
        "--setting-sources",
        "project",
        "--settings",
        json.dumps(settings),
        "--tools",
        tools,
        "--allowedTools",
        tools,
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
    ]
    return arguments + ([] if with_skill else ["--disable-slash-commands"])


def command(argv: list[str], *, readable: list[Path], writable: list[Path]) -> list[str]:
    writes = sorted({path.resolve() for path in writable})
    system = [Path(p) for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")]
    if sys.platform == "darwin":
        system += [
            Path("/System"),
            Path("/Library"),
            Path("/dev"),
            Path("/private/var/db/timezone"),
            Path("/private/var/run"),
        ]
    reads = sorted({path.resolve() for path in [*system, *readable, *writes] if path.exists()})
    if Path("/") in reads or Path.home().resolve() in reads:
        raise ValueError("agent read access must not include the filesystem root or home directory")
    if sys.platform == "darwin":
        launcher = "/usr/bin/sandbox-exec"
        if not Path(launcher).is_file():
            raise RuntimeError("agent isolation requires macOS sandbox-exec")

        def paths_filter(paths: list[Path]) -> str:
            return (
                "(require-any " + " ".join(f"(subpath {json.dumps(str(p))})" for p in paths) + ")"
            )

        # Safe openat-based tools open each ancestor directory. Permit those
        # directory handles (and names), without granting access to their files.
        ancestors = sorted({parent for path in reads for parent in path.parents})
        traversal = " ".join(f"(literal {json.dumps(str(p))})" for p in ancestors)
        profile = (
            "(version 1)(allow default)"
            f"(deny file-read* (require-not {paths_filter(reads)}))"
            f"(allow file-read* (require-any {traversal}))"
            "(allow file-read-metadata)"
            f"(deny file-write* (require-not {paths_filter([*writes, Path('/dev/null')])}))"
        )
        return [launcher, "-p", profile, *argv]
    if sys.platform == "linux":
        launcher = shutil.which("bwrap")
        if launcher is None:
            raise RuntimeError("agent isolation requires Linux bubblewrap (bwrap)")
        result = [
            launcher,
            "--die-with-parent",
            "--unshare-user",
            "--unshare-pid",
            "--new-session",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
        ]
        for path in reads:
            result += ["--ro-bind", str(path), str(path)]
        # Preserve system aliases, e.g. /bin -> /usr/bin and /lib -> /usr/lib.
        for path in system:
            if path.is_symlink():
                result += ["--symlink", str(path.resolve()), str(path)]
        for path in writes:
            result += ["--bind", str(path), str(path)]
        return [*result, "--remount-ro", "/", "--", *argv]
    raise RuntimeError("agent isolation requires macOS or Linux bubblewrap")


def run(
    argv: list[str],
    *,
    workspace: Path,
    readable: list[Path],
    writable: list[Path],
    env: dict[str, str],
    timeout: float,
    observe: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    invocation = command(argv, readable=readable, writable=writable)
    with subprocess.Popen(
        invocation,
        cwd=workspace,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        deadline = time.monotonic() + timeout
        try:
            while True:
                if observe:
                    observe()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    stdout, stderr = process.communicate(
                        timeout=min(remaining, 0.25) if observe else remaining
                    )
                    if observe:
                        observe()
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr) from None
        finally:
            # A finished agent must not leave background probes or servers alive.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
