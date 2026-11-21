from __future__ import annotations

import os
import runpy
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

verifier = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "packaging/verify_android_release.py")
)


def test_release_rejects_apk_built_from_another_tree(tmp_path: Path) -> None:
    apk = tmp_path / "release.apk"
    expected = "a" * 40 + " " + "b" * 40
    with ZipFile(apk, "w") as archive:
        archive.writestr(verifier["SOURCE_ASSET"], expected + "\n")
    verifier["verify_source"](apk, expected)
    with pytest.raises(ValueError, match="different Android or brand source tree"):
        verifier["verify_source"](apk, "c" * 40 + " " + "b" * 40)


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required for release checks")
@pytest.mark.parametrize("changed", ["android/build.sh", "src/kodikdown/gui/brands/icon.png"])
def test_release_verifies_source_trees_after_head_changes(tmp_path: Path, changed: str) -> None:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-c", "user.name=Release test", "-c", "user.email=test@example.test", *args],
            cwd=tmp_path,
            env=env,
            text=True,
        ).strip()

    git("init", "--quiet", "--template=")
    for name in ("android/build.sh", "src/kodikdown/gui/brands/icon.png"):
        source = tmp_path / name
        source.parent.mkdir(parents=True)
        source.write_text("source", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "Prepare source")
    source_commit = git("rev-parse", "HEAD")
    expected = verifier["source_trees"](tmp_path)

    apk = tmp_path / verifier["APK"]
    apk.parent.mkdir()
    with ZipFile(apk, "w") as archive:
        archive.writestr(verifier["SOURCE_ASSET"], expected + "\n")
    (tmp_path / "README.md").write_text("Updated release notes", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "Add APK and update docs")
    assert git("rev-parse", "HEAD") != source_commit
    verifier["verify_source"](apk, verifier["source_trees"](tmp_path))

    (tmp_path / changed).write_text("different source", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "Change Android build inputs")
    with pytest.raises(ValueError, match="different Android or brand source tree"):
        verifier["verify_source"](apk, verifier["source_trees"](tmp_path))
