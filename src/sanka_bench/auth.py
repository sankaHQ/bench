"""Authentication delegated to official provider CLIs, outside benchmark artifacts."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from sanka_bench.environment import isolated_environment


def run_auth(action: str, provider: str = "chatgpt") -> int:
    if provider not in {"chatgpt", "claude"}:
        raise ValueError(f"unsupported login provider: {provider}")
    if provider == "chatgpt":
        binary = "codex"
        commands = {
            "login": ["login", "--device-auth"],
            "status": ["login", "status"],
            "logout": ["logout"],
        }
        options = ["-c", 'forced_login_method="chatgpt"', "-c", 'cli_auth_credentials_store="file"']
        install_url = "https://learn.chatgpt.com/docs/cli"
    else:
        binary = "claude"
        commands = {
            "login": ["auth", "login", "--claudeai"],
            "status": ["auth", "status", "--text"],
            "logout": ["auth", "logout"],
        }
        options = []
        install_url = "https://code.claude.com/docs/en/setup"
    command = commands[action]
    executable = shutil.which(binary)
    if executable is None:
        raise ValueError(f"{binary.title()} CLI is required; install it from {install_url}")

    home = Path.home() / ".sanka-bench" / binary
    for directory in (home.parent, home):
        if directory.is_symlink():
            raise ValueError(f"refusing symlinked credential directory: {directory}")
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    env = isolated_environment(os.environ, ("CODEX_CA_CERTIFICATE",))
    # The npm Codex launcher needs the user's Node executable on PATH.
    env["PATH"] = os.environ.get("PATH", os.defpath)
    env["CODEX_HOME" if provider == "chatgpt" else "CLAUDE_CONFIG_DIR"] = str(home)
    print(f"Sanka Bench subscription credentials: {home}", flush=True)
    if action == "login":
        print(
            f"Complete the {provider} login in the official CLI below. "
            "Benchmark generation requires a separately qualified managed transport.",
            flush=True,
        )
    try:
        # ponytail: one account-wide lock; parallel inference needs one managed auth owner.
        import fcntl

        fd = os.open(home / "session.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise ValueError("subscription session lock must be a regular file")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError(
                    "Sanka Bench subscription session is busy; retry after the active "
                    "login, status, or logout command finishes"
                ) from exc
            return subprocess.run(
                [
                    executable,
                    *options,
                    *command,
                ],
                cwd=home,
                env=env,
                check=False,
                # Keep ownership if the parent dies while Codex still writes credentials.
                pass_fds=(lock.fileno(),),
            ).returncode
    except KeyboardInterrupt:
        return 130
