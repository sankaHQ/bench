"""Manifest and result-schema loading."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


class SchemaError(ValueError):
    """Raised when a benchmark document violates its versioned schema."""


def schema_path(name: str) -> Path:
    resource = files("sanka_bench").joinpath("schema", f"{name}.schema.json")
    return Path(str(resource))


def load_document(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SchemaError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SchemaError(f"{path} must contain an object")
    return payload


def load_schema(name: str) -> dict[str, Any]:
    path = schema_path(name)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SchemaError(f"schema {name} must contain an object")
    Draft202012Validator.check_schema(payload)
    return payload


def validate_payload(payload: dict[str, Any], schema_name: str, *, label: str) -> None:
    validator = Draft202012Validator(load_schema(schema_name))
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    if not errors:
        return
    rendered = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        rendered.append(f"{location}: {error.message}")
    raise SchemaError(f"{label} is invalid: " + "; ".join(rendered))


def load_and_validate(path: Path, schema_name: str) -> dict[str, Any]:
    payload = load_document(path)
    validate_payload(payload, schema_name, label=str(path))
    return payload
