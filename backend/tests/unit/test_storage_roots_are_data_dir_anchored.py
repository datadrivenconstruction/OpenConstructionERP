"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The guard that stops a module writing uploads next to whatever directory it was started in.

A module that declares ``ATTACHMENTS_DIR = Path("uploads/rfi/attachments")`` has
not chosen a directory. It has chosen whatever the process happened to be
started in, and every deployment starts the process somewhere different. Under
``make dev-backend`` that is the repo root and the files look fine. Under a
per-machine Windows install the Start Menu shortcut starts the app in the
install folder beneath Program Files, where an unelevated user cannot create a
directory at all, so the first ``mkdir`` raises ``PermissionError`` and
attaching a file to an RFI answers a bare 500 with no message a user can act
on. Between those two extremes sits the quieter failure: a service restarted
from a different directory writes new attachments somewhere the old ones are
not, and nothing anywhere reports that the files split into two piles.

The platform already resolves this centrally. ``app.core.storage.resolve_data_dir``
honours ``OE_DATA_DIR`` > ``DATA_DIR`` > ``OE_CLI_DATA_DIR`` and falls back to a
location that is persistent for the install shape it finds itself in, and the
desktop CLI exports ``OE_CLI_DATA_DIR`` before anything under ``app`` is
imported. Modules reach it through ``module_uploads_dir`` / ``module_data_dir``.
Nothing forced them to, which is why ten modules did not.

This guard is a ratchet on the class, not a list of the nineteen sites that had
it. The rule it enforces is mechanical: a relative string literal must not
become a directory the platform writes blobs into. Two shapes count as that.
A ``Path("...")`` whose first segment names one of the platform's own blob
directories is one, because those names only ever appear at the top of a write
root. An ``os.makedirs`` or ``.mkdir()`` applied straight to a relative literal
is the other, because creating a directory is itself the proof it is a write
root, whatever it is called.

Both halves matter. Without the first, a module can declare the root far from
where it creates it and the guard sees only an innocent-looking constant.
Without the second, a module can invent a blob directory under a name this file
has never heard of. Neither half needs a per-file exception list, which is the
point: ``boq/cad_import.py`` may keep ``Path("converters/bin")`` because a
read-only search path for an external binary is neither shape, not because
somebody blessed that line number. An exclusion list nobody can re-derive is
the thing that rots, and the ratchet it protects rots with it.

The scanner is asserted against the live tree, and reports how many files it
read. A tree walk that visits nothing and prints OK is indistinguishable from a
tree walk that found nothing wrong, and this repository has shipped that mistake
before.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / "backend" / "app"

#: Top-level directory names the platform writes blobs into, relative to the
#: resolved data dir. A relative literal that STARTS with one of these is
#: naming a storage root; there is no other reason for the word to appear in
#: that position. Kept deliberately short - this is not a keyword blocklist,
#: it is the list of directories that actually exist under a data dir.
_BLOB_ROOT_SEGMENTS: frozenset[str] = frozenset(
    {
        "uploads",
        "data",
        "storage",
        "photos",
        "attachments",
        "blobs",
        "media",
    }
)

#: Calls that create a directory. Passing a relative literal to one of these is
#: a write root by definition, whatever the directory is named.
_DIRECTORY_CREATING_CALLS: frozenset[str] = frozenset({"makedirs", "mkdir"})


@dataclass(frozen=True)
class RelativeRoot:
    """One site where a storage root is pinned to the working directory."""

    path: str
    line: int
    literal: str
    source: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.source}  (literal: {self.literal!r})"


def _relative_literal(node: ast.AST) -> str | None:
    """Return the string literal of ``node`` when it is a relative path.

    Absolute paths, drive-qualified Windows paths, ``~``-anchored paths and
    explicitly dot-relative paths are all deliberate about where they point,
    so none of them is the defect this guard looks for.

    Args:
        node: The AST node in argument position.

    Returns:
        The literal text, or ``None`` when the node is not a relative path
        literal.
    """
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    text = node.value
    if not text:
        return None
    if text.startswith(("/", "\\", "~", ".")):
        return None
    if len(text) > 1 and text[1] == ":":
        return None
    if Path(text).is_absolute():
        return None
    return text


def _first_segment(literal: str) -> str:
    """Return the first path segment of a relative literal, lowercased."""
    normalised = literal.replace("\\", "/")
    head = normalised.split("/", 1)[0]
    return head.lower()


def _call_name(node: ast.Call) -> str | None:
    """Return the callable's bare name for ``Path(...)`` / ``x.mkdir(...)`` alike."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def scan_source(source: str, *, path: str) -> list[RelativeRoot]:
    """Return every working-directory-relative storage root in one module.

    Args:
        source: Python source text.
        path: Display path used in the returned findings.

    Returns:
        The findings, in source order. Empty when the module is clean.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # A module that does not parse is not this guard's problem; the import
        # gate and the test suite both fail on it far more loudly than we could.
        return []
    lines = source.splitlines()
    found: dict[tuple[str, int], RelativeRoot] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name is None:
            continue
        creates_directory = name in _DIRECTORY_CREATING_CALLS
        if name not in ("Path", "PurePath") and not creates_directory:
            continue
        for arg in node.args:
            literal = _relative_literal(arg)
            if literal is None:
                continue
            # Creating a directory from a relative literal is a write root
            # whatever it is called; otherwise the first segment has to name
            # one of the platform's own blob directories.
            if not creates_directory and _first_segment(literal) not in _BLOB_ROOT_SEGMENTS:
                continue
            key = (path, node.lineno)
            if key in found:
                continue
            found[key] = RelativeRoot(
                path=path,
                line=node.lineno,
                literal=literal,
                source=lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
            )
    return [found[key] for key in sorted(found)]


def scan_app_tree() -> tuple[list[RelativeRoot], int]:
    """Scan every module under ``backend/app``.

    Returns:
        The findings and the number of files actually read, so a caller can
        prove the walk saw the tree rather than an empty directory.
    """
    findings: list[RelativeRoot] = []
    files_read = 0
    for file_path in sorted(APP_ROOT.rglob("*.py")):
        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        files_read += 1
        display = file_path.relative_to(REPO_ROOT).as_posix()
        findings.extend(scan_source(source, path=display))
    return findings, files_read


# ── The scanner's own behaviour ───────────────────────────────────────────


def test_scanner_reads_the_tree_it_claims_to_guard() -> None:
    """A walk that reads nothing must not be able to report success."""
    _, files_read = scan_app_tree()
    assert files_read > 500, (
        f"The storage-root guard read only {files_read} files under {APP_ROOT}. "
        "It is supposed to walk the whole backend package - a guard that scans "
        "an empty tree reports OK forever and gates nothing."
    )


def test_scanner_flags_a_relative_upload_root() -> None:
    """The shape this guard exists for: a constant pinned to the working directory."""
    source = 'from pathlib import Path\n\nATTACHMENTS_DIR = Path("uploads/widgets/attachments")\n'
    findings = scan_source(source, path="fake.py")
    assert len(findings) == 1, findings
    assert findings[0].literal == "uploads/widgets/attachments"


def test_scanner_flags_a_relative_directory_creation_under_any_name() -> None:
    """A module cannot escape by inventing a blob directory this file never heard of."""
    source = 'import os\n\nos.makedirs("widget_evidence/scans", exist_ok=True)\n'
    findings = scan_source(source, path="fake.py")
    assert len(findings) == 1, findings


def test_scanner_accepts_a_root_anchored_on_the_data_dir() -> None:
    """The sanctioned escape: go through the canonical resolver."""
    source = (
        "from app.core.storage import module_uploads_dir\n\n"
        'ATTACHMENTS_DIR = module_uploads_dir("widgets", "attachments")\n'
    )
    assert scan_source(source, path="fake.py") == []


def test_scanner_ignores_a_read_only_search_path() -> None:
    """A relative path we only ever READ from is not a storage root.

    ``boq/cad_import.py`` probes ``converters/bin`` for an external binary. It
    creates nothing and writes nothing, so widening the rule to catch it would
    buy a false positive and an exception list to suppress it.
    """
    source = 'from pathlib import Path\n\nCANDIDATES = [Path("converters/bin")]\n'
    assert scan_source(source, path="fake.py") == []


def test_scanner_ignores_an_absolute_or_home_anchored_root() -> None:
    """Absolute and home-anchored roots are decisions, not accidents."""
    source = (
        "from pathlib import Path\n\n"
        'ABS = Path("/var/lib/openestimate/uploads")\n'
        'HOME = Path("~/.openestimate/uploads").expanduser()\n'
    )
    assert scan_source(source, path="fake.py") == []


# ── The gate ──────────────────────────────────────────────────────────────


def test_no_module_pins_a_storage_root_to_the_working_directory() -> None:
    """No module under ``backend/app`` may declare a CWD-relative storage root."""
    findings, files_read = scan_app_tree()
    assert not findings, (
        f"{len(findings)} storage root(s) in {files_read} scanned files resolve against the "
        "process working directory instead of the platform data directory.\n\n"
        "User-visible symptom: on a per-machine Windows install the Start Menu "
        "shortcut starts the app inside the install folder under Program Files, "
        "where an unelevated user cannot create a directory. The first upload "
        "hits mkdir, raises PermissionError, and attaching a file answers a bare "
        "500 with nothing the user can act on. On a server the same defect is "
        "quieter and worse: restart the process from a different directory and "
        "new attachments land where the old ones are not, with no error at all.\n\n"
        "Fix: anchor the root on app.core.storage.module_uploads_dir(...) or "
        "module_data_dir(...), which resolve through resolve_data_dir() and so "
        "honour OE_DATA_DIR / DATA_DIR / OE_CLI_DATA_DIR. Keep the existing "
        "subdirectory names so installed deployments keep finding their files.\n\n"
        "Sites:\n" + "\n".join(f"  {finding}" for finding in findings)
    )
