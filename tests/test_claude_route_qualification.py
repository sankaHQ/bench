from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "qualify_claude_route", SCRIPTS / "qualify_claude_route.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["qualify_claude_route"] = module
    spec.loader.exec_module(module)
    return module


def _fake_claude(root: Path, *, creates_file: bool) -> Path:
    path = root / ("claude-with-tool" if creates_file else "claude-without-tool")
    write_probe = (
        "Path('qualification.txt').write_text('sanka-bench-claude-route-qualified\\n')"
        if creates_file
        else "pass"
    )
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "if '--version' in sys.argv:\n"
        "    print('2.1.241')\n"
        "    raise SystemExit(0)\n"
        f"Path({str(root / 'qualification-env.json')!r}).write_text(json.dumps({{"
        "'PATH': os.environ.get('PATH'), "
        "'AWS_SECRET_ACCESS_KEY': os.environ.get('AWS_SECRET_ACCESS_KEY'), "
        "'ANTHROPIC_BASE_URL': os.environ.get('ANTHROPIC_BASE_URL'), "
        "'ANTHROPIC_AUTH_TOKEN': os.environ.get('ANTHROPIC_AUTH_TOKEN'), "
        "'CLAUDE_CONFIG_DIR': os.environ.get('CLAUDE_CONFIG_DIR')}))\n"
        f"{write_probe}\n"
        "print(json.dumps({'type': 'assistant', 'message': {'content': []}}))\n"
        "print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, "
        "'num_turns': 1, 'modelUsage': {'gateway-alias': {'inputTokens': 5, "
        "'cacheCreationInputTokens': 1, 'cacheReadInputTokens': 2, 'outputTokens': 3}}}))\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _provider_evidence(root: Path, *, provider: str = "example") -> Path:
    path = root / f"{provider}-evidence.json"
    path.write_text(
        json.dumps(
            {
                "provider": provider,
                "provider_variant": "standard",
                "actual_model_id": "gpt-5.6",
                "usage_accounting": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_qualification_records_tool_stream_model_and_usage(tmp_path: Path) -> None:
    module = _load()

    record = module.qualify(  # type: ignore[attr-defined]
        claude_bin=_fake_claude(tmp_path, creates_file=True),
        requested_model_id="gateway-alias",
        provider="example",
        provider_variant="standard",
        route_kind="gateway",
        billing_mode="api_key",
        gateway_profile="example-anthropic-v1",
        provider_evidence=_provider_evidence(tmp_path),
        output=tmp_path / "qualification.json",
    )

    assert record["actual_model_id"] == "gpt-5.6"
    assert record["checks"] == {
        "tool_use": True,
        "streaming": True,
        "terminal_event": True,
        "usage_accounting": True,
    }
    assert record["evidence"]["provider_sha256"].startswith("sha256:")
    assert record["evidence"]["transcript_sha256"].startswith("sha256:")
    assert (tmp_path / "qualification.jsonl").is_file()


def test_qualification_rejects_missing_tool_output(tmp_path: Path) -> None:
    module = _load()

    with pytest.raises(ValueError, match="tool-use probe"):
        module.qualify(  # type: ignore[attr-defined]
            claude_bin=_fake_claude(tmp_path, creates_file=False),
            requested_model_id="gateway-alias",
            provider="example",
            provider_variant="standard",
            route_kind="gateway",
            billing_mode="api_key",
            gateway_profile="example-anthropic-v1",
            provider_evidence=_provider_evidence(tmp_path),
            output=tmp_path / "qualification.json",
        )


def test_qualification_rejects_mismatched_provider_evidence(tmp_path: Path) -> None:
    module = _load()

    with pytest.raises(ValueError, match="provider identity"):
        module.qualify(  # type: ignore[attr-defined]
            claude_bin=_fake_claude(tmp_path, creates_file=True),
            requested_model_id="gateway-alias",
            provider="example",
            provider_variant="standard",
            route_kind="gateway",
            billing_mode="api_key",
            gateway_profile="example-anthropic-v1",
            provider_evidence=_provider_evidence(tmp_path, provider="different"),
            output=tmp_path / "qualification.json",
        )


def test_native_qualification_uses_isolated_config_without_gateway_or_host_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    monkeypatch.setenv("PATH", f"/global/sanka/bin{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-reach-qualification")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "must-not-reach-native")

    module.qualify(  # type: ignore[attr-defined]
        claude_bin=_fake_claude(tmp_path, creates_file=True),
        requested_model_id="claude-sonnet-5",
        provider="anthropic",
        provider_variant="standard",
        route_kind="anthropic-native",
        billing_mode="subscription",
        gateway_profile=None,
        provider_evidence=_provider_evidence(tmp_path, provider="anthropic"),
        output=tmp_path / "qualification.json",
    )

    environment = json.loads((tmp_path / "qualification-env.json").read_text())
    assert environment["PATH"] == os.defpath
    assert environment["AWS_SECRET_ACCESS_KEY"] is None
    assert environment["ANTHROPIC_BASE_URL"] is None
    assert environment["ANTHROPIC_AUTH_TOKEN"] is None
    assert Path(environment["CLAUDE_CONFIG_DIR"]).name == "claude-config"
