"""Device authentication owned by Codex, isolated from benchmark artifacts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from sanka_bench.environment import isolated_environment


def run_auth(action: str) -> int:
    commands = {
        "login": ["login", "--device-auth"],
        "status": ["login", "status"],
        "logout": ["logout"],
    }
    command = commands[action]
    executable = shutil.which("codex")
    if executable is None:
        raise ValueError(
            "Codex CLI is required; install it from https://learn.chatgpt.com/docs/cli"
        )

    home = Path.home() / ".sanka-bench" / "codex"
    for directory in (home.parent, home):
        if directory.is_symlink():
            raise ValueError(f"refusing symlinked credential directory: {directory}")
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    env = isolated_environment(os.environ, ("CODEX_CA_CERTIFICATE",))
    # The npm Codex launcher needs the user's Node executable on PATH.
    env["PATH"] = os.environ.get("PATH", os.defpath)
    env["CODEX_HOME"] = str(home)
    print(f"Sanka Bench subscription credentials: {home}", flush=True)
    if action == "login":
        print(
            "Complete the device login below. This stores a subscription session; "
            "the current benchmark generation adapters still require API keys.",
            flush=True,
        )
    try:
        return subprocess.run(
            [
                executable,
                "-c",
                'forced_login_method="chatgpt"',
                "-c",
                'cli_auth_credentials_store="file"',
                *command,
            ],
            cwd=home,
            env=env,
            check=False,
        ).returncode
    except KeyboardInterrupt:
        return 130
