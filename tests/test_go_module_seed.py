import hashlib
import zipfile

import pytest

from sanka_bench import go_lane


def test_seed_copies_verified_module_data_into_each_private_cache(tmp_path):
    archive = tmp_path / "seed.zip"
    name = "cache/download/example.org/module/@v/v1.0.0.mod"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, "module example.org/module\n")
    digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    first, second = tmp_path / "first", tmp_path / "second"
    go_lane.seed_module_cache(archive, digest, first)
    go_lane.seed_module_cache(archive, digest, second)
    (first / name).write_text("agent mutation")
    assert (second / name).read_text() == "module example.org/module\n"
    with pytest.raises(ValueError, match="digest"):
        go_lane.seed_module_cache(archive, "sha256:" + "0" * 64, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("name", ["../escape", "/escape", "cache/download/../../escape"])
def test_seed_rejects_escaping_archive_without_writing(tmp_path, name):
    archive = tmp_path / "seed.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, "untrusted")
    digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="path"):
        go_lane.seed_module_cache(archive, digest, tmp_path / "cache")
    assert not (tmp_path / "cache").exists()
