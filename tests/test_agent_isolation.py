from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sanka_bench import agent_isolation


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS zsh and sandbox-exec")
def test_zsh_heredoc_uses_owned_scratch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = agent_isolation.run(
        ["/bin/zsh", "-fc", "cat <<'EOF'\nhello\nEOF"],
        workspace=workspace,
        writable=[workspace],
        readable=[],
        env={"PATH": os.defpath, "TMPDIR": str(workspace), "TMPPREFIX": "/tmp/zsh"},
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "hello\n"


@pytest.mark.skipif(
    sys.platform != "darwin" and shutil.which("bwrap") is None,
    reason="requires macOS sandbox-exec or Linux bubblewrap",
)
def test_agent_can_use_fixture_but_cannot_read_or_modify_host_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "hidden-scenarios.json"
    secret.write_text("private oracle")
    (workspace / "escape").symlink_to(secret)
    (workspace / "source.py").write_text("public source")
    code = """
import os, pathlib, subprocess, sys
workspace, secret = map(pathlib.Path, sys.argv[1:])
for directory in workspace.parents:
    os.close(os.open(directory, os.O_RDONLY | os.O_DIRECTORY))
assert (workspace / 'source.py').read_text() == 'public source'
(workspace / 'target_app.py').write_text('candidate')
for path in (secret, workspace / 'escape'):
    try:
        path.read_text()
    except OSError:
        pass
    else:
        raise AssertionError('host read escaped sandbox')
assert subprocess.run(['/bin/cat', str(secret)], capture_output=True).returncode != 0
assert subprocess.check_output(['/bin/cat', str(workspace / 'source.py')]) == b'public source'
try:
    (workspace / 'hardlink').hardlink_to(secret)
except OSError:
    pass
else:
    try:
        (workspace / 'hardlink').read_text()
    except OSError:
        pass
    else:
        raise AssertionError('hardlink escaped sandbox')
try:
    secret.write_text('tampered')
except OSError:
    pass
else:
    raise AssertionError('host write escaped sandbox')
"""
    result = agent_isolation.run(
        [sys.executable, "-c", code, str(workspace), str(secret)],
        workspace=workspace,
        writable=[workspace],
        readable=[Path(sys.prefix), Path(sys.base_prefix)],
        env={"PATH": os.defpath},
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert (workspace / "target_app.py").read_text() == "candidate"
    assert secret.read_text() == "private oracle"


def test_missing_os_sandbox_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_isolation.sys, "platform", "linux")
    monkeypatch.setattr(agent_isolation.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="bubblewrap"):
        agent_isolation.command(["python"], readable=[], writable=[])


@pytest.mark.skipif(
    not os.environ.get("BENCH_TEST_CLAUDE_BIN"), reason="requires pinned Claude binary"
)
@pytest.mark.parametrize("arm", ["alone", "sanka-cli", "with-sanka"])
def test_real_claude_has_only_the_treatment_skill(tmp_path: Path, arm: str) -> None:
    """No provider call: init inventory is emitted before the refused local connection."""
    binary = Path(os.environ["BENCH_TEST_CLAUDE_BIN"]).resolve()
    host_skill = tmp_path / ".claude/skills/host-only"
    host_skill.mkdir(parents=True)
    host_skill.joinpath("SKILL.md").write_text(
        "---\nname: host-only\ndescription: Must not leak into the benchmark\n---\nHost guidance.\n"
    )
    workspace = tmp_path / "workspace"
    config = tmp_path / "config"
    temporary = tmp_path / "tmp"
    for directory in (workspace, config, temporary):
        directory.mkdir()
    if arm == "with-sanka":
        skill = workspace / ".claude/skills/sanka-cli"
        skill.mkdir(parents=True)
        skill.joinpath("SKILL.md").write_text(
            "---\nname: sanka-cli\ndescription: Migration CLI\n---\nUse the supplied Sanka CLI.\n"
        )
    environment = {
        "PATH": os.defpath,
        "HOME": str(Path.home()),
        "CLAUDE_CONFIG_DIR": str(config),
        "CLAUDE_CODE_TMPDIR": str(temporary),
        "TMPDIR": str(temporary),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "ANTHROPIC_API_KEY": "offline-probe",
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:1",
    }
    try:
        result = agent_isolation.run(
            [
                str(binary),
                "-p",
                "Reply ready",
                "--model",
                "offline-probe",
                "--output-format",
                "stream-json",
                "--verbose",
                "--max-turns",
                "1",
                *agent_isolation.claude_arguments(with_skill=arm == "with-sanka"),
            ],
            workspace=workspace,
            readable=[binary],
            writable=[workspace, config, temporary],
            env=environment,
            timeout=5,
        )
        stdout = result.stdout
    except subprocess.TimeoutExpired as exc:
        stdout = str(exc.output or "")
    events = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
    init = next(event for event in events if event.get("subtype") == "init")
    assert init["skills"] == (["sanka-cli"] if arm == "with-sanka" else [])
    assert set(init["tools"]) == {"Bash", "Read", "Write", "Edit"} | (
        {"Skill"} if arm == "with-sanka" else set()
    )
    assert init["mcp_servers"] == []
    assert init["plugins"] == []
