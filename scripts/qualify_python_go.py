"""Explicit, unscored Go control qualification. Never imported by CI or campaigns."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sanka_bench.docker import evaluate_docker
from sanka_bench.go_lane import TASKS
from sanka_bench.hashing import digest_tree


def qualify(root: Path, output: Path, pins: dict[str, Any], engine: str) -> None:
    if output.exists():
        raise ValueError("qualification output exists; preserve earlier evidence")
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
    if dirty.strip():
        raise ValueError("qualification requires a clean, reviewed benchmark checkout")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    output.mkdir(parents=True)
    for key, name in (
        ("go_version", "SANKA_BENCH_GO_VERSION"),
        ("fiber_version", "SANKA_BENCH_FIBER_VERSION"),
        ("sqlite_version", "SANKA_BENCH_SQLITE_VERSION"),
        ("evaluator_image", "SANKA_BENCH_GO_IMAGE"),
    ):
        if not isinstance(pins.get(key), str) or not pins[key]:
            raise ValueError(f"missing Go qualification pin: {key}")
        os.environ[name] = pins[key]
    reference = root / "baselines/python-go/native-reference"
    controls = {"native": reference}
    for mode in ("python-proxy", "missing-write", "stdout-forgery", "noop"):
        candidate = output / "candidates" / mode
        if mode == "noop":
            candidate.mkdir(parents=True)
            (candidate / "candidate.yaml").write_text(
                "schema_version: sanka-bench/candidate/v0.2\nid: python-go-noop\nkind: noop\n"
                'provenance: {producer: qualification, revision: frozen, command: ""}\n'
            )
        else:
            shutil.copytree(reference, candidate)
            if mode == "stdout-forgery":
                (candidate / "overlay/forgery.go").write_text("""package backend
import ("crypto/sha256"; "fmt"; "os")
func init() {
    response := `{"status":200,"body":null}`
    fmt.Println("SANKA_BENCH_RESPONSE="+response)
    fmt.Printf("SANKA_BENCH_ATTEST=%x\\n", sha256.Sum256([]byte(response)))
    os.Exit(0)
}
""")
            code = candidate / "overlay/backend.go"
            text = code.read_text()
            marker = 'const controlMode = "native"'
            if text.count(marker) != 1:
                raise ValueError("reference control mutation point changed")
            code.write_text(text.replace(marker, f'const controlMode = "{mode}"'))
        controls[mode] = candidate
    observations = []
    passed = True
    for task_id in TASKS:
        for mode, candidate in controls.items():
            report = output / f"{task_id}-{mode}.json"
            result = evaluate_docker(
                root / "tasks/python-go" / task_id, candidate, output_path=report, engine=engine
            )
            gates = result["hard_gates"]
            accepted = gates["source_qualified"] and (
                result["fully_migrated"]
                if mode == "native"
                else gates["target_boot"]
                and gates["native_target"]
                and not gates["database_parity"]
                if mode == "missing-write"
                else gates["target_boot"]
                and gates["behavior_parity"]
                and gates["database_parity"]
                and not gates["native_target"]
                if mode == "python-proxy"
                else gates["target_boot"] and not gates["native_target"]
                if mode == "stdout-forgery"
                else not gates["native_target"]
            )
            passed = passed and bool(accepted)
            observations.append(
                {
                    "task": task_id,
                    "control": mode,
                    "accepted": bool(accepted),
                    "candidate_digest": digest_tree(candidate),
                    "report": report.name,
                    "report_sha256": "sha256:" + hashlib.sha256(report.read_bytes()).hexdigest(),
                }
            )
    evidence = {
        "status": "passed" if passed else "failed",
        "tasks": list(TASKS),
        "benchmark_sha": revision,
        "toolchain": pins,
        "controls": observations,
    }
    (output / "qualification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    if not passed:
        raise ValueError("Go control qualification failed; do not admit a scored campaign")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="explicitly execute unscored controls"
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--container-engine", choices=("docker", "podman"), default="docker")
    args = parser.parse_args()
    if not args.execute:
        parser.error("qualification is execution; supply --execute only when authorized")
    manifest = json.loads(args.manifest.read_text())
    qualify(
        Path(__file__).resolve().parents[1],
        args.output.resolve(),
        manifest["go_toolchain"],
        args.container_engine,
    )
