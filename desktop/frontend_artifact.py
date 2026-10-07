# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Carry the tested diagnostic frontend between jobs without rebuilding it."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

ARCHIVE = "frontend.zip"
MANIFEST = "frontend-manifest.json"
REQUIRED = {"index.html", "splash.html"}
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name or "\\" in name or ":" in name or path.is_absolute()
        or any(
            part in ("", ".", "..") or part.endswith((" ", "."))
            or part.split(".")[0].upper() in WINDOWS_DEVICES
            or any(ord(char) < 32 or char in '<>"|?*' for char in part)
            for part in name.split("/")
        )
    ):
        raise ValueError(f"Unsafe frontend archive member: {name!r}")
    return path


def identity(source_sha: str, run_id: str, run_attempt: str, sidecar: Path) -> dict:
    return {
        "source_sha": source_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "sidecar_sha256": digest(sidecar),
    }


def pack(dist: Path, artifact: Path, expected: dict) -> None:
    if dist.is_symlink() or not dist.is_dir():
        raise ValueError("Frontend dist must be a real directory")
    files = {}
    for path in sorted(dist.rglob("*")):
        if path.is_symlink():
            raise ValueError("Frontend dist must not contain symlinks")
        if path.is_file():
            name = path.relative_to(dist).as_posix()
            member_path(name)
            files[name] = {"sha256": digest(path), "bytes": path.stat().st_size}
    if not REQUIRED <= files.keys() or any(files[name]["bytes"] == 0 for name in REQUIRED):
        raise ValueError("Frontend index.html and splash.html must exist and be nonempty")
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError("Frontend filenames collide on Windows")
    artifact.mkdir(parents=True, exist_ok=False)
    archive = artifact / ARCHIVE
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as output:
        for name in files:
            output.write(dist / name, name)
    manifest = {"schema": 1, **expected, "archive_sha256": digest(archive), "files": files}
    (artifact / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def restore(dist: Path, artifact: Path, expected: dict) -> None:
    manifest = json.loads((artifact / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Frontend artifact identity does not match this checkout/run/sidecar")
    archive = artifact / ARCHIVE
    if digest(archive) != manifest.get("archive_sha256"):
        raise ValueError("Frontend archive fingerprint mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or not REQUIRED <= files.keys():
        raise ValueError("Frontend manifest is missing required files")
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError("Frontend filenames collide on Windows")
    # Refuse stale output instead of merging it with a supposedly exact build.
    names = {name.casefold() for name in files}
    for name in files:
        relative = member_path(name)
        if any(parent.as_posix().casefold() in names for parent in relative.parents):
            raise ValueError("Frontend file path collides with another file's parent")
    if dist.is_symlink() or (dist.exists() and (not dist.is_dir() or any(dist.iterdir()))):
        raise ValueError("Frontend destination must be absent or empty")
    destination = dist.resolve()
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if len(members) != len(files) or {item.filename for item in members} != files.keys():
            raise ValueError("Frontend archive file set differs from its manifest")
        # Validate every byte and every target before creating any output file.
        for item in members:
            relative = member_path(item.filename)
            if item.is_dir() or stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ValueError("Frontend archive may contain only regular files")
            target = destination.joinpath(*relative.parts).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("Frontend archive target escapes the destination")
            record = files[item.filename]
            if not isinstance(record, dict) or item.file_size != record.get("bytes"):
                raise ValueError("Frontend file size mismatch")
            if item.filename in REQUIRED and item.file_size == 0:
                raise ValueError("Required frontend file is empty")
            with source.open(item) as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != record.get("sha256"):
                raise ValueError("Frontend file fingerprint mismatch")
        dist.mkdir(parents=True, exist_ok=True)
        for item in members:
            target = destination.joinpath(*member_path(item.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(item) as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("pack", "restore"))
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    args = parser.parse_args()
    expected = identity(args.source_sha, args.run_id, args.run_attempt, args.sidecar)
    {"pack": pack, "restore": restore}[args.operation](args.dist, args.artifact, expected)
    print(f"Frontend {args.operation} verified for {args.source_sha}, run {args.run_id}/{args.run_attempt}")


if __name__ == "__main__":
    main()
