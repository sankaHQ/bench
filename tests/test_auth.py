from pathlib import Path
from types import SimpleNamespace

import pytest

from sanka_bench import auth
from sanka_bench.cli import main


@pytest.mark.parametrize(
    ("argv", "suffix"),
    [
        (["login"], ["login", "--device-auth"]),
        (["login", "--device-auth"], ["login", "--device-auth"]),
        (["login", "status"], ["login", "status"]),
        (["logout"], ["logout"]),
    ],
)
def test_auth_uses_private_home_and_never_inherits_api_billing(tmp_path, monkeypatch, argv, suffix):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.shutil, "which", lambda _: "/bin/codex")
    monkeypatch.setenv("CODEX_HOME", "/personal/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-forward")
    monkeypatch.setenv("CODEX_API_KEY", "do-not-forward")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "do-not-forward")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[-len(suffix) :] == suffix
        assert 'forced_login_method="chatgpt"' in command
        assert 'cli_auth_credentials_store="file"' in command
        home = tmp_path / ".sanka-bench" / "codex"
        assert kwargs["cwd"] == home
        assert kwargs["env"]["CODEX_HOME"] == str(home)
        assert "do-not-forward" not in kwargs["env"].values()
        assert home.stat().st_mode & 0o777 == 0o700
        assert home.parent.stat().st_mode & 0o777 == 0o700
        assert not kwargs["check"]
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(auth.subprocess, "run", run)
    assert main(argv) == 7
    assert len(calls) == 1


def test_missing_codex_is_actionable_and_creates_no_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.shutil, "which", lambda _: None)
    assert main(["login"]) == 2
    assert "Codex CLI is required" in capsys.readouterr().out
    assert not (tmp_path / ".sanka-bench").exists()


@pytest.mark.parametrize("child", [False, True])
def test_refuses_symlinked_credential_storage(tmp_path, monkeypatch, child):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.shutil, "which", lambda _: "/bin/codex")
    target = tmp_path / "other-account"
    target.mkdir()
    base = tmp_path / ".sanka-bench"
    if child:
        base.mkdir()
        base = base / "codex"
    base.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(auth.subprocess, "run", lambda *_a, **_k: pytest.fail("must not launch"))
    assert main(["login"]) == 2
    assert not list(target.iterdir())


def test_device_login_can_be_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.shutil, "which", lambda _: "/bin/codex")

    def cancel(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(auth.subprocess, "run", cancel)
    assert main(["login"]) == 130
