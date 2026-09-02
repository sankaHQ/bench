"""Network-disabled Docker runner for the benchmark evaluator."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from sanka_bench.hashing import digest_tree
from sanka_bench.process import run_command


class DockerEvaluationError(RuntimeError):
    """Raised when the isolated evaluator image cannot build or run."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def evaluate_docker(
    task_dir: Path,
    candidate_dir: Path,
    *,
    output_path: Path | None,
) -> dict[str, Any]:
    root = repository_root()
    task_relative = _relative_to_root(task_dir, root)
    candidate_relative = _relative_to_root(candidate_dir, root)
    image_tag = _ensure_evaluator_image(root)

    # Docker Desktop shares /Users by default, but not macOS's resolved
    # /var/folders temporary path. Keep the bind source inside the repository
    # so the same isolated runner works on macOS and Linux hosts.
    with tempfile.TemporaryDirectory(prefix=".sanka-bench-output-", dir=root) as temp:
        output_root = Path(temp)
        container_output = output_root / "result.json"
        run = run_command(
            [
                "docker",
                "run",
                "--rm",
                "--init",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--pids-limit",
                "128",
                "--memory",
                "1g",
                "--cpus",
                "2",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=512m",
                "--mount",
                f"type=bind,source={output_root},target=/output",
                image_tag,
                "evaluate",
                "--runner",
                "local",
                "--task",
                f"/bench/{task_relative.as_posix()}",
                "--candidate",
                f"/bench/{candidate_relative.as_posix()}",
                "--output",
                "/output/result.json",
            ],
            cwd=root,
            timeout=900,
        )
        if not run.passed:
            detail = run.stderr.strip() or run.stdout.strip()
            raise DockerEvaluationError(f"isolated evaluation failed: {detail}")
        payload = json.loads(container_output.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise DockerEvaluationError("isolated evaluator returned a non-object result")
        result = cast(dict[str, Any], payload)
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return result


def _ensure_evaluator_image(root: Path) -> str:
    image_tag = f"sanka-bench:{digest_tree(root).removeprefix('sha256:')[:16]}"
    inspect = run_command(
        ["docker", "image", "inspect", image_tag],
        cwd=root,
        timeout=30,
    )
    if inspect.passed:
        return image_tag

    build = run_command(
        ["docker", "build", "--pull=false", "--tag", image_tag, "."],
        cwd=root,
        timeout=900,
    )
    if not build.passed:
        detail = build.stderr.strip() or build.stdout.strip()
        raise DockerEvaluationError(f"evaluator image build failed: {detail}")
    return image_tag


def _relative_to_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise DockerEvaluationError(f"Docker inputs must live under {root}: {resolved}")
    return resolved.relative_to(root)
