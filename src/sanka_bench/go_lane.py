"""Python-to-Go campaign boundary and native scaffold promotion."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any

TASKS = tuple(f"python-go-{index:03d}" for index in range(1, 5))
EXTENSION = "sanka/python-to-golang"
DISTRIBUTION = "sanka-extension-python-to-golang"
ARTIFACT = ".sanka/extensions/sanka/python-to-golang/golang"


def release_pins() -> dict[str, Any]:
    pins: dict[str, Any] = json.loads(
        Path(__file__).with_name("python_go_release.json").read_text()
    )
    return pins


def validate_extension_lock(record: dict[str, Any], revision: str | None) -> None:
    """Bind the CLI-managed, hash-verified environment to the selected release."""
    pins = release_pins()
    if revision != pins["marketplace_commit"] or any(
        record.get(key) != value
        for key, value in {
            "id": EXTENSION,
            "version": pins["extension_version"],
            "snapshot_digest": revision,
            "manifest_digest": pins["manifest_digest"],
            "enabled": True,
        }.items()
    ):
        raise ValueError("installed Go extension lock differs from the selected release")


PROMPT = """Migrate the supplied DRF application to native Go/Fiber v3 and SQLite.
Keep source files intact. Preserve responses, JSON types, selected headers, database
state, permissions, rollback and side effects. Read public-tests/scenarios.json.
Expose NewBenchApp(databasePath string) (*fiber.App, error) in the root Go package.
It must open the supplied, already seeded SQLite database, enable foreign keys,
and return the same native Fiber application used by cmd/api/main.go.
The supplied go.mod/go.sum freeze Go 1.26.5, Fiber v3.5.0 and modernc.org/sqlite
v1.57.0 for both arms. Preserve these dependency pins. No replace directives, vendored
framework, Python serving process, proxy or network delegation is allowed.
The evaluator compiles cmd/api and a trusted Go test-client executable, calls
Fiber App.Test, and observes persistent state independently. It supplies no
Python interpreter or external network inside the Go serving sandbox.
Candidate assembly, object files and go:linkname directives are forbidden.
Use DATABASE_URL for the standalone server and PORT for its port.
{grading_scope} One attempt; {max_turns} turns and {wall_seconds} seconds maximum.
"""

ADAPTER = """// SPDX-License-Identifier: Apache-2.0
package backend

import (
    "context"
    "net/url"
    "github.com/gofiber/fiber/v3"
)

// NewBenchApp adapts the generated SQLite app to the public benchmark contract.
func NewBenchApp(databasePath string) (*fiber.App, error) {
    uri := (&url.URL{Scheme: "file", Path: databasePath}).String()
    pool, err := OpenSQLite(context.Background(), uri)
    if err != nil { return nil, err }
    return NewApp(pool), nil
}
"""


def promote(workspace: Path) -> dict[str, str]:
    generated = workspace / ARTIFACT
    if not (generated / "go.mod").is_file():
        return {}
    copied = {}
    for path in sorted(generated.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Go artifact must not contain symlinks or escaping paths")
        if not path.is_file():
            continue
        relative = path.relative_to(generated)
        if path.suffix not in {".go", ".sql"} and relative.name not in {"go.mod", "go.sum"}:
            continue
        target = workspace / relative
        if target.is_symlink() or not target.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Go promotion destination escapes workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    adapter = workspace / "bench_adapter.go"
    if not adapter.exists():
        adapter.write_text(ADAPTER)
        copied[adapter.name] = hashlib.sha256(adapter.read_bytes()).hexdigest()
    return copied


def validate_campaign(manifest: dict[str, Any], *, execution: bool) -> None:
    tasks = manifest.get("suite", {}).get("tasks", [])
    if tasks != list(TASKS):
        raise ValueError("Python-to-Go campaign requires exactly the four ordered Go task IDs")
    config = manifest.get("execution", {})
    if config.get("configurations") != ["alone", "sanka-cli"] or config.get("samples", 1) != 1:
        raise ValueError("Python-to-Go requires alone/sanka-cli and one pass@1 sample")
    if not execution:
        return
    if (
        config.get("sanka_workflow") != "native-lifecycle-v1"
        or not manifest.get("models")
        or any(model.get("harness") != "sanka-native" for model in manifest["models"])
    ):
        raise ValueError("Go qualification admission requires native models and lifecycle")
    record = manifest.get("go_qualification", {})
    path = record.get("path")
    if not path or not Path(path).is_absolute():
        raise ValueError("Python-to-Go qualification evidence is required before execution")
    payload = Path(path).read_bytes()
    if "sha256:" + hashlib.sha256(payload).hexdigest() != record.get("sha256"):
        raise ValueError("Go qualification digest mismatch")
    evidence = json.loads(payload)
    if (
        evidence.get("status") != "passed"
        or evidence.get("tasks") != list(TASKS)
        or evidence.get("benchmark_sha") != manifest.get("benchmark_sha")
        or evidence.get("toolchain") != manifest.get("go_toolchain")
    ):
        raise ValueError("Go qualification does not match this benchmark/toolchain")
    expected = {
        (task, control)
        for task in TASKS
        for control in ("native", "python-proxy", "missing-write", "stdout-forgery", "noop")
    }
    controls = evidence.get("controls", [])
    if (
        len(controls) != len(expected)
        or {(item.get("task"), item.get("control")) for item in controls} != expected
        or any(item.get("accepted") is not True for item in controls)
    ):
        raise ValueError("Go qualification lacks the complete accepted control matrix")
    for item in controls:
        report = (Path(path).parent / item["report"]).resolve()
        if not report.is_relative_to(Path(path).parent.resolve()):
            raise ValueError("Go qualification report escapes its evidence directory")
        if "sha256:" + hashlib.sha256(report.read_bytes()).hexdigest() != item["report_sha256"]:
            raise ValueError("Go qualification report changed")
    pins = manifest.get("go_toolchain", {})
    for key, value in {
        "go_version": "1.26.5",
        "fiber_version": "v3.5.0",
        "sqlite_version": "v1.57.0",
    }.items():
        if pins.get(key) != value:
            raise ValueError(f"{key} must match the public dependency lock: {value}")
    for name in ("go_version", "fiber_version", "sqlite_version", "evaluator_image"):
        if not isinstance(pins.get(name), str) or not pins[name].strip():
            raise ValueError(f"Go toolchain requires {name}")
    if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", pins["evaluator_image"]):
        raise ValueError("Go evaluator image must be pinned by digest")
    compiler = Path(str(pins.get("go_bin") or ""))
    if not compiler.is_absolute() or not compiler.is_file():
        raise ValueError("Go generation compiler requires an absolute binary path")
    if "sha256:" + hashlib.sha256(compiler.read_bytes()).hexdigest() != pins.get("go_bin_sha256"):
        raise ValueError("Go generation compiler digest mismatch")
    toolchain = manifest.get("toolchain", {})
    release = release_pins()
    for key in ("sanka_cli", "extension_version", "marketplace_commit"):
        if toolchain.get(key) != release[key]:
            raise ValueError(f"Go campaign {key} differs from the selected release")
    if not re.fullmatch(r"[0-9a-f]{40}", str(toolchain.get("marketplace_commit", ""))):
        raise ValueError("Go campaign requires an immutable marketplace commit")
    wheels = toolchain.get("wheel_hashes", {})
    if not wheels:
        raise ValueError("Go campaign requires CLI, extension and SDK wheel hashes")
    expected_wheels = {
        item["filename"]: item["sha256"]
        for item in release["artifacts"]
        if item["filename"].endswith(".whl")
    }
    if (
        len(wheels) != len(expected_wheels)
        or {Path(path).name: digest for path, digest in wheels.items()} != expected_wheels
    ):
        raise ValueError("Go wheel pins must match the complete selected release")
    identities = set()
    for filename, expected_hash in wheels.items():
        wheel = Path(filename)
        if not wheel.is_absolute() or wheel.suffix != ".whl":
            raise ValueError("wheel pins must name absolute local .whl paths")
        if "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest() != expected_hash:
            raise ValueError(f"wheel changed: {wheel.name}")
        with zipfile.ZipFile(wheel) as archive:
            metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("wheel requires one distribution metadata record")
            name = str(BytesParser().parsebytes(archive.read(metadata[0]))["Name"])
            identity = re.sub(r"[-_.]+", "-", name).lower()
            if identity in identities:
                raise ValueError("duplicate wheel distribution")
            identities.add(identity)


def verify_installed_wheels(sanka_bin: Path, wheels: dict[str, str]) -> None:
    """Check CLI payload; the CLI seals extension payloads in its separate cache."""
    cli = next(
        item for item in release_pins()["artifacts"] if item["filename"].startswith("sanka_cli-")
    )
    if [digest for path, digest in wheels.items() if Path(path).name == cli["filename"]] != [
        cli["sha256"]
    ]:
        raise ValueError("installed CLI check requires its selected release wheel")
    script = """
import hashlib, importlib.metadata as metadata, json, pathlib, sys, zipfile
from email.parser import BytesParser
for filename, expected in json.loads(sys.argv[1]).items():
    wheel = pathlib.Path(filename)
    assert "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest() == expected, "wheel changed"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        info = next(name for name in names if name.endswith(".dist-info/METADATA"))
        package = BytesParser().parsebytes(archive.read(info))["Name"]
        if package != "sanka-cli":
            continue
        installed = metadata.distribution(package)
        roots, expected_files = set(), set()
        for name in names:
            if name.endswith("/") or name.endswith(".dist-info/RECORD"):
                continue
            assert ".data/" not in name, "wheel data layouts are not supported"
            relative = pathlib.PurePosixPath(name)
            assert not relative.is_absolute() and ".." not in relative.parts, "unsafe wheel path"
            actual = pathlib.Path(installed.locate_file(name))
            assert not actual.is_symlink() and actual.read_bytes() == archive.read(name), name
            expected_files.add(actual.resolve())
            if not relative.parts[0].endswith(".dist-info"):
                roots.add(pathlib.Path(installed.locate_file(relative.parts[0])))
        for root in roots:
            for actual in root.rglob("*") if root.is_dir() else [root]:
                if actual.is_file() and "__pycache__" not in actual.parts:
                    assert actual.resolve() in expected_files, "extra runtime file: " + str(actual)
"""
    checked = subprocess.run(
        [str(sanka_bin.parent / "python"), "-I", "-c", script, json.dumps(wheels)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if checked.returncode:
        raise ValueError(
            "installed Sanka runtime differs from pinned wheels: " + checked.stderr[-2000:]
        )
