"""Minimal environment shared by measured agent subprocesses."""

from __future__ import annotations

import os
from collections.abc import Collection, Mapping

_BASE_NAMES = {
    "CURL_CA_BUNDLE",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "REQUESTS_CA_BUNDLE",
    "SHELL",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USER",
}


def isolated_environment(
    source: Mapping[str, str], extra_names: Collection[str] = ()
) -> dict[str, str]:
    """Keep runtime basics plus named treatment inputs; replace the host PATH."""
    names = _BASE_NAMES | set(extra_names)
    result = {name: source[name] for name in names if source.get(name)}
    result["PATH"] = os.defpath
    return result
