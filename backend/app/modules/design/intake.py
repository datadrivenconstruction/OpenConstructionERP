"""Verify a ``.ddcrev`` package (contract §2–§5) and unpack it into a work directory.

Nothing here touches the database or the storage: the router stores and registers only
what passed every check. All refusals are :class:`PackageRejected` with the HTTP status
the contract assigns (413 size, 422 content).
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .contract_models import (
    ALL_COLUMNS,
    BBOX_COLUMNS,
    INT_COLUMNS,
    KEY_COLUMNS,
    QTY_COLUMNS,
    REQUIRED_COLUMNS,
    TEXT_COLUMNS,
    Diff,
    ElementRow,
    Manifest,
)

MANIFEST = "manifest.json"
# Fixed paths per role (contract §2 table); a sheet lives under sheets/, a thumbnail anywhere.
FIXED_PATHS = {
    "source": "model.ddc",
    "geometry": "geometry.glb",
    "elements": "elements.parquet",
    "diff": "diff.json",
    "brief": "brief.json",
    "issues": "issues.bcfzip",
    "ifc": "model.ifc",
}
SHEET_PATH = re.compile(r"^sheets/[A-Za-z0-9._-]+\.pdf$")
_CHUNK = 1024 * 1024
_MAX_ERRORS = 20


class PackageRejected(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def _reject(detail: Any, status_code: int = 422) -> PackageRejected:
    return PackageRejected(status_code, detail)


def _errors(exc: ValidationError, where: str) -> list[dict[str, Any]]:
    return [
        {"loc": [where, *e["loc"]], "msg": e["msg"]}
        for e in exc.errors(include_url=False, include_input=False)[:_MAX_ERRORS]
    ]


@dataclass
class VerifiedPackage:
    manifest: Manifest
    manifest_json: dict[str, Any]
    files: dict[str, Path]  # manifest path -> unpacked file
    roles: dict[str, str]  # role -> path for single-file roles
    element_count: int
    max_rows: int
    diff: Diff | None
    glb_node_keys: list[str]

    def rows(self) -> Iterator[dict[str, Any]]:
        return iter_rows(self.files[self.roles["elements"]], self.max_rows)


def _member_infos(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    from app.core.partner_pack._safe_extract import UnsafeArchiveError, assert_safe_archive

    infos = zf.infolist()
    try:
        assert_safe_archive(infos)
    except UnsafeArchiveError as exc:
        raise _reject(str(exc)) from exc
    members: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        if info.is_dir():
            continue
        if info.filename in members:
            raise _reject(f"duplicate archive member: {info.filename}")
        if info.flag_bits & 0x1:
            raise _reject(f"encrypted archive member: {info.filename}")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise _reject(f"unsupported compression for {info.filename}: use deflate or store")
        members[info.filename] = info
    return members


def _check_layout(manifest: Manifest, members: dict[str, zipfile.ZipInfo], project_id: str) -> dict[str, str]:
    if manifest.project_ref.erp_project_id not in (None, project_id):
        raise _reject("manifest.project_ref.erp_project_id names another project")
    listed = [f.path for f in manifest.files]
    # Paths are canonical by schema; case variants would still meet on a case-insensitive disk.
    folded = [p.casefold() for p in listed]
    if len(set(folded)) != len(folded):
        raise _reject("manifest.files lists a path twice (paths differ only in case or are equal)")
    if MANIFEST in folded:
        raise _reject("manifest.json must not list itself")
    as_dirs = {"/".join(p.split("/")[:i]) for p in folded for i in range(1, p.count("/") + 1)}
    clash = sorted(set(folded) & as_dirs)
    if clash:
        raise _reject(f"path used both as a file and as a folder: {clash[0]}")
    unlisted = sorted(set(members) - set(listed) - {MANIFEST})
    if unlisted:
        raise _reject(f"files not listed in the manifest: {', '.join(unlisted[:_MAX_ERRORS])}")
    missing = sorted(set(listed) - set(members))
    if missing:
        raise _reject(f"files listed in the manifest but missing: {', '.join(missing[:_MAX_ERRORS])}")
    roles: dict[str, str] = {}
    for f in manifest.files:
        fixed = FIXED_PATHS.get(f.role)
        if fixed is not None:
            if f.path != fixed:
                raise _reject(f"role '{f.role}' must be at '{fixed}', not '{f.path}'")
            if f.role in roles:
                raise _reject(f"role '{f.role}' appears twice")
            roles[f.role] = f.path
        elif f.role == "sheet" and not SHEET_PATH.match(f.path):
            raise _reject(f"sheet '{f.path}' must be sheets/<name>.pdf")
        if members[f.path].file_size != f.bytes:
            raise _reject(f"size of '{f.path}' differs from the manifest")
    if manifest.parent_revision_id is not None and "diff" not in roles:
        raise _reject("diff.json is required when parent_revision_id is set")
    if manifest.source.kind == "generated" and "brief" not in roles:
        raise _reject("brief.json is required when source.kind is 'generated'")
    return roles


def _unpack(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, dest_root: Path, path: str, expect_sha: str, expect_bytes: int
) -> Path:
    root = dest_root.resolve()
    target = (root / path).resolve()
    if root not in target.parents:
        raise _reject(f"path escapes the package: {path}")
    sha = hashlib.sha256()
    written = 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # "xb": a second member resolving to the same file is refused, never overwrites the first.
        with zf.open(info) as src, target.open("xb") as out:
            while chunk := src.read(_CHUNK):
                written += len(chunk)
                if written > expect_bytes:
                    raise _reject(f"'{path}' is larger than the manifest says")
                sha.update(chunk)
                out.write(chunk)
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        raise _reject(f"'{path}' cannot be read from the archive: {exc}") from exc
    if written != expect_bytes:
        raise _reject(f"size of '{path}' differs from the manifest")
    if sha.hexdigest() != expect_sha:
        raise _reject(f"sha256 mismatch for '{path}'")
    return target


def read_glb_nodes(path: Path, max_json: int) -> list[dict[str, Any]]:
    """Nodes of a glTF 2.0 binary (header + JSON chunk only; the BIN chunk is not read)."""
    with path.open("rb") as fh:
        header = fh.read(20)
        if len(header) < 20:
            raise _reject("geometry.glb is not a glTF binary")
        magic, version, length, chunk_len, chunk_type = struct.unpack("<4sIIII", header)
        if magic != b"glTF" or version != 2:
            raise _reject("geometry.glb is not a glTF 2.0 binary")
        if length != path.stat().st_size or chunk_type != 0x4E4F534A or chunk_len > length - 20:
            raise _reject("geometry.glb has a broken header")
        if chunk_len > max_json:
            raise _reject(f"geometry.glb JSON chunk is over the {max_json} byte limit", 413)
        try:
            doc = json.loads(fh.read(chunk_len))
        except ValueError as exc:
            raise _reject("geometry.glb has an unreadable JSON chunk") from exc
    if not isinstance(doc, dict) or len(doc.get("scenes") or [None]) != 1:
        raise _reject("geometry.glb must hold exactly one scene")
    nodes = doc.get("nodes") or []
    return [n for n in nodes if isinstance(n, dict)]


_BATCH = 10_000


def _open_elements(path: Path, max_rows: int):
    import pyarrow as pa
    import pyarrow.parquet as pq

    try:
        # Probe through our own handle: a failed ParquetFile(path) leaks its handle, and an open
        # file blocks removing the temp directory on Windows.
        with open(path, "rb") as fh:
            _ = pq.ParquetFile(fh).schema_arrow
        pf = pq.ParquetFile(path)
        schema = pf.schema_arrow
    except (pa.ArrowException, OSError) as exc:
        raise _reject(f"elements.parquet cannot be read: {exc}") from exc
    try:
        _check_schema(pf, schema, max_rows)
    except BaseException:
        pf.close()  # an open handle blocks removing the temp directory on Windows
        raise
    return pf


def _check_schema(pf, schema, max_rows: int) -> None:
    import pyarrow as pa

    if pf.metadata.num_rows > max_rows:
        raise _reject(f"elements.parquet has {pf.metadata.num_rows} rows, over the {max_rows} row limit", 413)
    names = schema.names
    unknown = sorted(set(names) - set(ALL_COLUMNS))
    if unknown:
        raise _reject(f"elements.parquet has columns outside the contract: {', '.join(unknown)}")
    missing = sorted(set(REQUIRED_COLUMNS) - set(names))
    if missing:
        raise _reject(f"elements.parquet lacks required columns: {', '.join(missing)}")
    for field in schema:
        t = field.type
        if pa.types.is_null(t):
            continue
        if field.name in KEY_COLUMNS + TEXT_COLUMNS:
            ok = pa.types.is_string(t) or pa.types.is_large_string(t)
            want = "string"
        elif field.name in QTY_COLUMNS + BBOX_COLUMNS:
            ok, want = pa.types.is_float64(t), "float64"
        elif field.name in INT_COLUMNS:
            ok, want = pa.types.is_int64(t), "int64"
        else:  # pragma: no cover - ALL_COLUMNS is the union of the groups (test_mirror)
            ok, want = False, "?"
        if not ok:
            raise _reject(f"elements.parquet column '{field.name}' is {t}, expected {want}")


def iter_rows(path: Path, max_rows: int) -> Iterator[dict[str, Any]]:
    """Rows of elements.parquet, read in batches (native types)."""
    import pyarrow as pa

    pf = _open_elements(path, max_rows)
    try:
        for batch in pf.iter_batches(batch_size=_BATCH):
            yield from batch.to_pylist()
    except (pa.ArrowException, OSError) as exc:
        raise _reject(f"elements.parquet cannot be read: {exc}") from exc
    finally:
        pf.close()


def check_elements(path: Path, max_rows: int) -> set[str]:
    """Validate every row against ddc-elements/1; returns the element keys."""
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    rows = iter_rows(path, max_rows)
    for i, row in enumerate(rows):
        try:
            ElementRow.model_validate(row)
        except ValidationError as exc:
            errors.extend(_errors(exc, f"elements.parquet[{i}]"))
        else:
            key = row["element_key"]
            if not (row["id"] == row["stable_id"] == key):
                errors.append({"loc": [f"elements.parquet[{i}]"], "msg": "id, stable_id and element_key differ"})
            elif key in seen:
                errors.append({"loc": [f"elements.parquet[{i}]"], "msg": f"duplicate element_key {key}"})
            seen.add(key)
            props = row.get("props")
            if props is not None:
                try:
                    parsed = json.loads(props)
                except ValueError:
                    parsed = None
                if not isinstance(parsed, dict):
                    errors.append({"loc": [f"elements.parquet[{i}]", "props"], "msg": "props is not a JSON object"})
        if len(errors) >= _MAX_ERRORS:
            break
    rows.close()  # release the file now: Windows cannot remove a directory holding an open handle
    if errors:
        raise _reject(errors[:_MAX_ERRORS])
    return seen


@dataclass(frozen=True)
class Limits:
    max_unpacked: int
    max_json: int
    max_glb_json: int
    max_rows: int


def verify_package(package: Path, work_dir: Path, *, project_id: str, limits: Limits) -> VerifiedPackage:
    try:
        zf = zipfile.ZipFile(package)
    except (zipfile.BadZipFile, OSError) as exc:
        raise _reject("package is not a zip archive") from exc
    with zf:
        members = _member_infos(zf)
        total = sum(max(i.file_size, 0) for i in members.values())
        if total > limits.max_unpacked:
            raise _reject(f"package unpacks to {total} bytes, over the {limits.max_unpacked} byte limit", 413)
        info = members.get(MANIFEST)
        if info is None:
            raise _reject("manifest.json is missing")
        if info.file_size > limits.max_json:
            raise _reject("manifest.json is too large", 413)
        raw = zf.read(info)
        try:
            manifest = Manifest.model_validate_json(raw)
        except ValidationError as exc:
            raise _reject(_errors(exc, MANIFEST)) from exc
        roles = _check_layout(manifest, members, project_id)
        for name in ("diff", "brief"):
            if name in roles and members[roles[name]].file_size > limits.max_json:
                raise _reject(f"{roles[name]} is too large", 413)
        files = {f.path: _unpack(zf, members[f.path], work_dir, f.path, f.sha256, f.bytes) for f in manifest.files}

    diff = None
    if "diff" in roles:
        try:
            diff = Diff.model_validate_json(files[roles["diff"]].read_bytes())
        except ValidationError as exc:
            raise _reject(_errors(exc, "diff.json")) from exc
        if diff.revision_id != manifest.revision_id or diff.parent_revision_id != manifest.parent_revision_id:
            raise _reject("diff.json names other revisions than the manifest")
    if "brief" in roles:
        try:
            brief = json.loads(files[roles["brief"]].read_bytes())
        except ValueError as exc:
            raise _reject("brief.json is not JSON") from exc
        if not isinstance(brief, dict) or brief.get("schema") != "ddc-brief/1":
            raise _reject("brief.json is not ddc-brief/1")

    keys = check_elements(files[roles["elements"]], limits.max_rows)
    node_keys: list[str] = []
    for node in read_glb_nodes(files[roles["geometry"]], limits.max_glb_json):
        extras = node.get("extras")
        key = extras.get("element_key") if isinstance(extras, dict) else None
        if key is None:
            if node.get("mesh") is not None:
                raise _reject(f"geometry.glb mesh node '{node.get('name')}' has no extras.element_key")
            continue  # a pure transform node (scene root, axis conversion) is not an element
        if node.get("name") != key:
            raise _reject(f"geometry.glb node named '{node.get('name')}' carries element_key '{key}'")
        if key not in keys:
            raise _reject(f"geometry.glb node '{key}' has no row in elements.parquet")
        node_keys.append(key)
    return VerifiedPackage(
        manifest=manifest,
        manifest_json=json.loads(raw),
        files=files,
        roles=roles,
        element_count=len(keys),
        max_rows=limits.max_rows,
        diff=diff,
        glb_node_keys=node_keys,
    )
