"""Verify the locally signed Android artifact at the checked-out release commit."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from zipfile import BadZipFile, ZipFile

APK = Path("packaging/kodikdown-android.apk")
SOURCE_ASSET = "assets/kodikdown-source-trees.txt"
CERTIFICATE = "dee5b1f9e6159afd9f854bddfb71929006b723fe45f3a98d0a887791d6b8a265"


def source_trees(repository: Path) -> str:
    hashes = subprocess.check_output(
        ["git", "rev-parse", "HEAD:android", "HEAD:src/kodikdown/gui/brands"],
        cwd=repository,
        text=True,
    )
    return " ".join(hashes.split())


def verify_source(apk: Path, expected: str) -> None:
    marker_bytes = f"{expected}\n".encode("ascii")
    with ZipFile(apk) as archive:
        if archive.namelist().count(SOURCE_ASSET) != 1:
            raise ValueError(
                "Missing or duplicate APK source hashes. Run android/build.sh --release."
            )
        with archive.open(SOURCE_ASSET) as marker:
            if marker.read(len(marker_bytes) + 1) != marker_bytes:
                raise ValueError("The APK was built from a different Android or brand source tree.")


def verify(repository: Path, tools: Path, tag: str) -> None:
    apk = repository / APK
    verify_source(apk, source_trees(repository))
    manifest = subprocess.check_output([tools / "aapt", "dump", "badging", apk], text=True)
    if not manifest.startswith("package: name='com.shawniks.kodikdown' "):
        raise ValueError("The APK must use the production application ID.")
    version = re.search(r"versionName='([^']+)'", manifest.partition("\n")[0])
    if version is None or f"v{version[1]}" != tag:
        raise ValueError(f"The APK version does not match release tag {tag}.")
    if "application-debuggable" in manifest:
        raise ValueError("The APK is debuggable.")
    signature = subprocess.check_output(
        [tools / "apksigner", "verify", "--print-certs", apk], text=True
    )
    certificates = re.findall(
        r"^Signer #\d+ certificate SHA-256 digest: ([a-fA-F0-9]+)$", signature, re.M
    )
    if [certificate.lower() for certificate in certificates] != [CERTIFICATE]:
        raise ValueError("The APK must use the production signing certificate.")


if __name__ == "__main__":
    try:
        verify(
            Path.cwd(),
            Path(os.environ["ANDROID_HOME"]) / "build-tools" / "35.0.0",
            os.environ["GITHUB_REF_NAME"],
        )
    except (BadZipFile, OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
