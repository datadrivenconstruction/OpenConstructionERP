# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍BCF 3.0 zip reader — mirror of :mod:`app.modules.bcf.writer`.

Why a second parser?
--------------------
The platform already carries :func:`app.modules.bcf.bcf_xml.parse_bcfzip`
which dual-targets BCF 2.1 and 3.0 and is wired into
:class:`BCFService.import_bcfzip` (Topics CRUD). This module is the
**clash-coordination** read surface: it mirrors :mod:`writer` exactly so
the round-trip writer-→-reader closes byte-for-byte for the 3.0-only
clash export, and it produces frozen / immutable dataclasses that the
:class:`BCFImportService` can map straight onto the ``ClashIssue`` row.

Design constraints (per task brief)
-----------------------------------
1. **Stdlib only.** ``zipfile``, ``xml.etree``, ``defusedxml`` (already a
   project dep — disables DTD / external-entity attacks), ``io``, ``re``,
   ``hashlib``. No lxml, no bcfzip-py.
2. **Zip-bomb defence.** Configurable caps on total uncompressed size
   (default 100 MB) and entry count (default 10 000).
3. **Path-traversal safe.** Any zip entry whose normalised path escapes
   the archive root (``..`` component, absolute path, drive letter)
   raises :class:`BCFSecurityError` before any read happens.
4. **Resilient per-topic.** A malformed ``markup.bcf`` inside one topic
   folder is captured in :attr:`ParsedTopic.parse_error` instead of
   aborting the whole archive — the importer can then surface a
   structured ``errors`` entry per topic without losing the good ones.
5. **Frozen / hashable.** Every dataclass is ``frozen=True`` with
   ``tuple`` collections, so a parse result is safely sharable across
   async tasks without copy ceremony.

Public surface
--------------
* :class:`BCFReader`           — entry point (``from_bytes``, ``from_file``)
* :class:`ParsedBCF`           — top-level archive DTO
* :class:`ParsedProject`       — project.bcfp contents
* :class:`ParsedExtensions`    — extensions.xml enums
* :class:`ParsedTopic`         — Topic + nested Comments / Viewpoints
* :class:`ParsedComment`
* :class:`ParsedViewpoint`     — camera + components + clipping planes
* :class:`ParsedClippingPlane`
* :class:`BCFReaderError`      — base error for unrecoverable problems
* :class:`BCFSecurityError`    — zip-bomb / path-traversal
* :class:`BCFFormatError`      — not a bcf zip, no bcf.version
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

# defusedxml is a transitive runtime dep (see pyproject.toml). Using its
# ElementTree shim disables entity expansion / external-entity loading —
# the standard hardening for any path that ingests third-party XML.
from defusedxml import ElementTree as ET  # noqa: N817

__all__ = [
    "BCFFormatError",
    "BCFReader",
    "BCFReaderError",
    "BCFSecurityError",
    "ParsedBCF",
    "ParsedClippingPlane",
    "ParsedComment",
    "ParsedExtensions",
    "ParsedProject",
    "ParsedTopic",
    "ParsedViewpoint",
]


# ── safety limits ──────────────────────────────────────────────────────────

DEFAULT_MAX_TOTAL_BYTES: int = 100 * 1024 * 1024  # 100 MiB total uncompressed
DEFAULT_MAX_ENTRIES: int = 10_000

# Match writer.py's GUID rules exactly so a writer-→-reader round-trip
# carries every emitted folder name through without a rename.
_GUID_RE = re.compile(
    r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
)
_HEX_SIG_RE = re.compile(r"^[0-9a-fA-F]{8,64}$")

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ── exceptions ─────────────────────────────────────────────────────────────


class BCFReaderError(Exception):
    """‌⁠‍Base class for all reader-emitted errors."""


class BCFSecurityError(BCFReaderError):
    """‌⁠‍A zip-bomb, path-traversal or absurd member size was detected."""


class BCFFormatError(BCFReaderError):
    """‌⁠‍The bytes are not a BCF ``.bcfzip`` (no ``bcf.version``, bad zip)."""


# ── DTOs (all frozen, all tuples) ──────────────────────────────────────────


@dataclass(frozen=True)
class ParsedClippingPlane:
    """A single clipping plane: a point + a normal."""

    location: tuple[float, float, float]
    direction: tuple[float, float, float]


@dataclass(frozen=True)
class ParsedComment:
    """A single ``<Comment>`` inside a Topic."""

    guid: str
    date: datetime | None
    author: str | None
    comment: str
    viewpoint_guid: str | None = None
    modified_date: datetime | None = None
    modified_author: str | None = None
    status: str | None = None  # BCF 2.1 optional <Status> child


@dataclass(frozen=True)
class ParsedViewpoint:
    """A ``viewpoint.bcfv`` decoded into a hashable record."""

    guid: str
    camera_type: str  # "perspective" | "orthogonal" | ""
    camera_view_point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    camera_direction: tuple[float, float, float] = (0.0, -1.0, 0.0)
    camera_up_vector: tuple[float, float, float] = (0.0, 0.0, 1.0)
    field_of_view: float | None = None
    view_to_world_scale: float | None = None
    aspect_ratio: float | None = None
    default_visibility: bool = True
    visible: tuple[str, ...] = ()
    hidden: tuple[str, ...] = ()
    selection: tuple[str, ...] = ()
    clipping_planes: tuple[ParsedClippingPlane, ...] = ()


@dataclass(frozen=True)
class ParsedTopic:
    """A single ``markup.bcf`` Topic + its comments / viewpoints / snapshots.

    A topic with a structural problem in its ``markup.bcf`` is still
    returned, but with :attr:`parse_error` populated — the caller can
    then surface a structured per-topic error report without losing the
    good neighbours.
    """

    guid: str
    topic_type: str
    topic_status: str
    title: str
    creation_date: datetime
    creation_author: str
    server_assigned_id: str | None = None
    priority: str | None = None
    description: str | None = None
    assigned_to: str | None = None
    due_date: datetime | None = None
    stage: str | None = None
    labels: tuple[str, ...] = ()
    reference_links: tuple[str, ...] = ()
    modified_date: datetime | None = None
    modified_author: str | None = None
    comments: tuple[ParsedComment, ...] = ()
    viewpoints: tuple[ParsedViewpoint, ...] = ()
    # filename → raw PNG bytes. ``snapshot.png`` is the canonical key
    # name (writer.py emits exactly that). Empty when no image present.
    snapshots: dict[str, bytes] = field(default_factory=dict)
    parse_error: str | None = None


@dataclass(frozen=True)
class ParsedProject:
    """``project.bcfp`` contents (optional in a BCF archive)."""

    project_id: str
    name: str


@dataclass(frozen=True)
class ParsedExtensions:
    """``extensions.xml`` enum lists (empty tuples when missing)."""

    topic_types: tuple[str, ...] = ()
    topic_statuses: tuple[str, ...] = ()
    priorities: tuple[str, ...] = ()
    topic_labels: tuple[str, ...] = ()
    users: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()
    snippet_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedBCF:
    """The parsed archive — root return type of :class:`BCFReader`."""

    version: str
    project: ParsedProject | None
    extensions: ParsedExtensions
    topics: tuple[ParsedTopic, ...]


# ── helpers ────────────────────────────────────────────────────────────────


def _is_unsafe_zip_path(name: str) -> bool:
    """Return True for any entry name that escapes the archive root.

    Rejects absolute paths (``/foo``, ``C:\\foo``), drive letters, and
    any path whose normalised parts contain a ``..`` component. This is
    the standard zip-slip defence as recommended by the Python docs.
    """
    if not name:
        return True
    # Reject Windows-style absolute paths first (PurePosixPath would let
    # them through). A colon in the second position is a drive letter.
    if len(name) >= 2 and name[1] == ":":
        return True
    if name.startswith("/") or name.startswith("\\"):
        return True
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return any(p == ".." for p in parts)


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse an xs:dateTime / ISO 8601 string.

    Accepts:
        2026-05-21T12:34:56Z              (UTC zulu)
        2026-05-21T12:34:56+02:00         (offset)
        2026-05-21T12:34:56.123456+02:00  (fractional)
        2026-05-21T12:34:56               (naive — assumed UTC)
        2026-05-21                        (date only — midnight UTC)
    """
    if not raw:
        return None
    txt = raw.strip()
    if not txt:
        return None
    # Normalise the Zulu literal to a numeric offset Python understands.
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        # Date-only fallback: an ISO date is a valid BCF DueDate.
        try:
            return datetime.fromisoformat(txt[:10]).replace(tzinfo=UTC)
        except ValueError:
            return None
    if dt.tzinfo is None:
        # BCF mandates UTC; naive timestamps imply UTC in practice.
        dt = dt.replace(tzinfo=UTC)
    return dt


def _to_float(raw: str | None, default: float = 0.0) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _read_xyz(parent, tag: str) -> tuple[float, float, float]:
    """Read a BCF ``<tag><X/><Y/><Z/></tag>`` triple. Missing → zeros."""
    if parent is None:
        return (0.0, 0.0, 0.0)
    el = parent.find(tag)
    if el is None:
        return (0.0, 0.0, 0.0)
    return (
        _to_float((el.findtext("X") or "").strip() or None),
        _to_float((el.findtext("Y") or "").strip() or None),
        _to_float((el.findtext("Z") or "").strip() or None),
    )


def _text_or_none(el, tag: str) -> str | None:
    if el is None:
        return None
    child = el.find(tag)
    if child is None or child.text is None:
        return None
    s = child.text.strip()
    return s or None


def _text_list(parent, container_tag: str, child_tag: str) -> tuple[str, ...]:
    """Read ``<container_tag><child_tag>val</child_tag>...</container_tag>``."""
    if parent is None:
        return ()
    container = parent.find(container_tag)
    if container is None:
        return ()
    out: list[str] = []
    for c in container.findall(child_tag):
        if c.text is None:
            continue
        s = c.text.strip()
        if s:
            out.append(s)
    return tuple(out)


def _normalize_guid(guid: str | None) -> str:
    """Strip braces and lowercase. Matches :func:`writer._normalize_guid`."""
    if not guid:
        return ""
    return guid.strip().strip("{}").lower()


def _is_safe_guid(guid: str) -> bool:
    """Mirror :func:`writer._safe_dir` — accept UUID or hex signature."""
    g = _normalize_guid(guid)
    return bool(_GUID_RE.match(g) or _HEX_SIG_RE.match(g))


# ── reader ─────────────────────────────────────────────────────────────────


class BCFReader:
    """‌⁠‍Read a BCF 3.0 ``.bcfzip`` into immutable :class:`ParsedBCF` DTOs.

    Usage
    -----
    >>> reader = BCFReader()
    >>> parsed = reader.from_bytes(open("topic.bcfzip", "rb").read())
    >>> for topic in parsed.topics:
    ...     print(topic.guid, topic.title)

    The reader is **stateless** apart from the configured safety limits;
    the same instance is safe to reuse across requests / async tasks.
    """

    def __init__(
        self,
        *,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        if max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.max_total_bytes = max_total_bytes
        self.max_entries = max_entries

    # ── public API ───────────────────────────────────────────────────

    @classmethod
    def from_bytes(cls, raw: bytes, **kwargs: object) -> ParsedBCF:
        """Convenience: parse a raw byte string with a default reader."""
        return cls(**kwargs).parse(raw)  # type: ignore[arg-type]

    @classmethod
    def from_file(cls, path: str | Path, **kwargs: object) -> ParsedBCF:
        """Convenience: read a ``.bcfzip`` from disk."""
        data = Path(path).read_bytes()
        return cls(**kwargs).parse(data)  # type: ignore[arg-type]

    def parse(self, raw: bytes) -> ParsedBCF:
        """Parse ``raw`` (a complete ``.bcfzip``) into a :class:`ParsedBCF`.

        Raises:
            BCFSecurityError: zip bomb, path traversal, entry-count cap.
            BCFFormatError: not a ZIP / no ``bcf.version`` / version is
                not 3.0 (the reader is the 3.0 surface — sibling parser
                handles 2.1).
        """
        # Hard size cap before we even open the archive — prevents
        # zip-bomb headers from making us touch a multi-GB payload.
        if len(raw) > self.max_total_bytes:
            raise BCFSecurityError(f"BCF archive is {len(raw)} bytes, exceeds cap {self.max_total_bytes}")

        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as exc:
            raise BCFFormatError(f"Not a valid ZIP archive: {exc}") from exc

        with zf:
            # ── safety sweep ────────────────────────────────────────
            self._enforce_safety(zf)
            names = zf.namelist()
            lower_names = {n.lower(): n for n in names}

            # ── bcf.version ─────────────────────────────────────────
            version = self._read_version(zf, lower_names)
            if not version.startswith("3"):
                # 3.0 only — the sibling 2.1 reader lives in bcf_xml.py.
                raise BCFFormatError(f"Reader supports BCF 3.x only; got {version!r}")

            # ── project.bcfp (optional) ─────────────────────────────
            project = self._read_project(zf, lower_names)

            # ── extensions.xml (optional) ───────────────────────────
            extensions = self._read_extensions(zf, lower_names)

            # ── per-topic ───────────────────────────────────────────
            topics = self._read_topics(zf, names)

        return ParsedBCF(
            version=version,
            project=project,
            extensions=extensions,
            topics=tuple(topics),
        )

    # ── internals ───────────────────────────────────────────────────

    def _enforce_safety(self, zf: zipfile.ZipFile) -> None:
        """Reject path-traversal, count and uncompressed-size limits.

        Walks ``zf.infolist`` once — every member is checked before any
        ``read()`` happens. A single bad entry aborts the whole parse
        (a malicious archive shouldn't get partial-results).
        """
        infos = zf.infolist()
        if len(infos) > self.max_entries:
            raise BCFSecurityError(f"BCF archive has {len(infos)} entries (cap {self.max_entries})")
        total = 0
        for info in infos:
            if _is_unsafe_zip_path(info.filename):
                raise BCFSecurityError(f"Unsafe zip entry path: {info.filename!r}")
            total += info.file_size
            if total > self.max_total_bytes:
                raise BCFSecurityError(f"BCF archive uncompressed size exceeds cap ({total} > {self.max_total_bytes})")

    def _parse_xml(self, raw: bytes):
        """Defused XML parse — disables DTD / external entities."""
        return ET.fromstring(raw)

    def _read_version(self, zf: zipfile.ZipFile, lower_names: dict[str, str]) -> str:
        """Read ``bcf.version`` → VersionId string."""
        key = lower_names.get("bcf.version")
        if key is None:
            raise BCFFormatError("Archive has no bcf.version marker")
        try:
            root = self._parse_xml(zf.read(key))
        except ET.ParseError as exc:
            raise BCFFormatError(f"bcf.version is not valid XML: {exc}") from exc
        vid = (root.get("VersionId") or "").strip()
        if not vid:
            # Some tools nest <DetailedVersion>3.0</DetailedVersion>.
            detailed = (root.findtext("DetailedVersion") or "").strip()
            vid = detailed or ""
        if not vid:
            raise BCFFormatError("bcf.version has no VersionId attribute")
        return vid

    def _read_project(self, zf: zipfile.ZipFile, lower_names: dict[str, str]) -> ParsedProject | None:
        """Read ``project.bcfp`` — both ProjectInfo and ProjectExtension layouts."""
        key = lower_names.get("project.bcfp")
        if key is None:
            return None
        try:
            root = self._parse_xml(zf.read(key))
        except ET.ParseError:
            return None
        # writer.py emits <ProjectInfo><Project ProjectId=.../></ProjectInfo>
        # bcf_xml.py emits <ProjectExtension><Project ProjectId=.../></...>
        # Accept either.
        proj_el = root.find("Project")
        if proj_el is None:
            return None
        pid = (proj_el.get("ProjectId") or "").strip()
        name = (proj_el.findtext("Name") or "").strip()
        if not pid and not name:
            return None
        return ParsedProject(project_id=pid, name=name)

    def _read_extensions(self, zf: zipfile.ZipFile, lower_names: dict[str, str]) -> ParsedExtensions:
        """Read ``extensions.xml`` enum lists."""
        key = lower_names.get("extensions.xml")
        if key is None:
            return ParsedExtensions()
        try:
            root = self._parse_xml(zf.read(key))
        except ET.ParseError:
            return ParsedExtensions()

        def _enum(container: str, child: str) -> tuple[str, ...]:
            return _text_list(root, container, child)

        return ParsedExtensions(
            topic_types=_enum("TopicTypes", "TopicType"),
            topic_statuses=_enum("TopicStatuses", "TopicStatus"),
            priorities=_enum("Priorities", "Priority"),
            topic_labels=_enum("TopicLabels", "TopicLabel"),
            users=_enum("Users", "User"),
            stages=_enum("Stages", "Stage"),
            snippet_types=_enum("SnippetTypes", "SnippetType"),
        )

    def _read_topics(self, zf: zipfile.ZipFile, names: list[str]) -> list[ParsedTopic]:
        """Read every ``markup.bcf`` + its sibling .bcfv / .png files."""
        markup_names = [n for n in names if n.lower().endswith("markup.bcf")]
        topics: list[ParsedTopic] = []
        for markup_name in markup_names:
            topic_dir = markup_name.rsplit("/", 1)[0] if "/" in markup_name else ""
            topic = self._read_one_topic(zf, names, markup_name, topic_dir)
            if topic is not None:
                topics.append(topic)
        return topics

    def _read_one_topic(
        self,
        zf: zipfile.ZipFile,
        names: list[str],
        markup_name: str,
        topic_dir: str,
    ) -> ParsedTopic | None:
        """Decode a single Topic. Resilient: a bad XML body → parse_error."""
        # Read viewpoints + snapshots that live next to this markup.
        siblings = (
            [n for n in names if topic_dir and n.startswith(f"{topic_dir}/") and n != markup_name]
            if topic_dir
            else [n for n in names if "/" not in n and n != markup_name]
        )

        snapshots: dict[str, bytes] = {}
        bcfv_blobs: dict[str, bytes] = {}
        for s in siblings:
            base = s.rsplit("/", 1)[-1].lower()
            try:
                blob = zf.read(s)
            except KeyError:
                continue
            if base.endswith(".bcfv"):
                bcfv_blobs[base] = blob
            elif base.endswith(".png") and blob[: len(_PNG_MAGIC)] == _PNG_MAGIC:
                snapshots[s.rsplit("/", 1)[-1]] = blob

        try:
            raw_markup = zf.read(markup_name)
        except KeyError:
            return ParsedTopic(
                guid=topic_dir or "?",
                topic_type="",
                topic_status="",
                title="",
                creation_date=datetime(1970, 1, 1, tzinfo=UTC),
                creation_author="",
                parse_error=f"markup.bcf missing for {markup_name!r}",
                snapshots=snapshots,
            )

        try:
            root = self._parse_xml(raw_markup)
        except ET.ParseError as exc:
            return ParsedTopic(
                guid=topic_dir or "?",
                topic_type="",
                topic_status="",
                title="",
                creation_date=datetime(1970, 1, 1, tzinfo=UTC),
                creation_author="",
                parse_error=(f"markup.bcf is not well-formed XML ({markup_name}): {exc}"),
                snapshots=snapshots,
            )

        topic_el = root.find("Topic")
        if topic_el is None:
            return ParsedTopic(
                guid=topic_dir or "?",
                topic_type="",
                topic_status="",
                title="",
                creation_date=datetime(1970, 1, 1, tzinfo=UTC),
                creation_author="",
                parse_error=(f"markup.bcf has no <Topic> element ({markup_name})"),
                snapshots=snapshots,
            )

        guid = _normalize_guid(topic_el.get("Guid"))
        if not guid:
            return ParsedTopic(
                guid=topic_dir or "?",
                topic_type="",
                topic_status="",
                title="",
                creation_date=datetime(1970, 1, 1, tzinfo=UTC),
                creation_author="",
                parse_error="Topic missing required @Guid attribute",
                snapshots=snapshots,
            )

        # Required fields from markup.xsd. A missing Title is fatal for
        # this topic but doesn't poison the archive.
        title = (_text_or_none(topic_el, "Title") or "").strip()
        creation_date = _parse_dt(_text_or_none(topic_el, "CreationDate"))
        creation_author = _text_or_none(topic_el, "CreationAuthor") or ""
        topic_type = topic_el.get("TopicType") or _text_or_none(topic_el, "TopicType") or ""
        topic_status = topic_el.get("TopicStatus") or _text_or_none(topic_el, "TopicStatus") or ""
        missing: list[str] = []
        if not title:
            missing.append("Title")
        if creation_date is None:
            missing.append("CreationDate")
        if not creation_author:
            missing.append("CreationAuthor")
        if not topic_type:
            missing.append("TopicType")
        if not topic_status:
            missing.append("TopicStatus")
        if missing:
            return ParsedTopic(
                guid=guid,
                topic_type=topic_type or "",
                topic_status=topic_status or "",
                title=title,
                creation_date=creation_date or datetime(1970, 1, 1, tzinfo=UTC),
                creation_author=creation_author,
                parse_error=(f"Topic {guid} missing required field(s): {', '.join(missing)} (in {markup_name})"),
                snapshots=snapshots,
            )

        # ── optional scalar fields ──
        server_assigned_id = topic_el.get("ServerAssignedId")
        priority = _text_or_none(topic_el, "Priority")
        description = _text_or_none(topic_el, "Description")
        assigned_to = _text_or_none(topic_el, "AssignedTo")
        due_date = _parse_dt(_text_or_none(topic_el, "DueDate"))
        stage = _text_or_none(topic_el, "Stage")
        modified_date = _parse_dt(_text_or_none(topic_el, "ModifiedDate"))
        modified_author = _text_or_none(topic_el, "ModifiedAuthor")

        # ── labels (3.0 nests inside <Labels><Label>val</Label></Labels>)
        labels_container = topic_el.find("Labels")
        if labels_container is not None:
            labels = tuple(
                (lab.text or "").strip() for lab in labels_container.findall("Label") if lab.text and lab.text.strip()
            )
        else:
            # 2.1-style fallback: repeated <Labels>val</Labels> siblings.
            labels = tuple(
                (lab.text or "").strip() for lab in topic_el.findall("Labels") if lab.text and lab.text.strip()
            )

        # ── reference links ──
        reference_links = tuple(
            (rl.text or "").strip() for rl in topic_el.findall("ReferenceLink") if rl.text and rl.text.strip()
        )

        # ── comments ──
        comments = self._read_comments(topic_el, root)

        # ── viewpoints ──
        viewpoints = self._read_viewpoints(topic_el, root, bcfv_blobs)

        return ParsedTopic(
            guid=guid,
            topic_type=topic_type,
            topic_status=topic_status,
            title=title,
            creation_date=creation_date,
            creation_author=creation_author,
            server_assigned_id=server_assigned_id,
            priority=priority,
            description=description,
            assigned_to=assigned_to,
            due_date=due_date,
            stage=stage,
            labels=labels,
            reference_links=reference_links,
            modified_date=modified_date,
            modified_author=modified_author,
            comments=comments,
            viewpoints=viewpoints,
            snapshots=snapshots,
        )

    def _read_comments(self, topic_el, markup_root) -> tuple[ParsedComment, ...]:
        """Collect every ``<Comment>`` under the topic (3.0 + 2.1 layouts)."""
        comment_els: list = []
        # 3.0: direct children of <Topic>
        comment_els.extend(topic_el.findall("Comment"))
        # 3.0 variant: <Topic><Comments><Comment/></Comments></Topic>
        comments_container = topic_el.find("Comments")
        if comments_container is not None:
            comment_els.extend(comments_container.findall("Comment"))
        # 2.1 fallback: <Markup><Comment/></Markup>
        for c in markup_root.findall("Comment"):
            if c not in comment_els:
                comment_els.append(c)

        out: list[ParsedComment] = []
        seen_guids: set[str] = set()
        for c_el in comment_els:
            guid = _normalize_guid(c_el.get("Guid")) or ""
            # Dedupe by guid in case both layouts are present.
            if guid and guid in seen_guids:
                continue
            if guid:
                seen_guids.add(guid)
            vp_ref_el = c_el.find("Viewpoint")
            vp_guid = (
                _normalize_guid(vp_ref_el.get("Guid")) if vp_ref_el is not None and vp_ref_el.get("Guid") else None
            )
            out.append(
                ParsedComment(
                    guid=guid,
                    date=_parse_dt(_text_or_none(c_el, "Date")),
                    author=_text_or_none(c_el, "Author"),
                    comment=(_text_or_none(c_el, "Comment") or ""),
                    viewpoint_guid=vp_guid,
                    modified_date=_parse_dt(_text_or_none(c_el, "ModifiedDate")),
                    modified_author=_text_or_none(c_el, "ModifiedAuthor"),
                    status=_text_or_none(c_el, "Status"),
                )
            )
        return tuple(out)

    def _read_viewpoints(
        self,
        topic_el,
        markup_root,
        bcfv_blobs: dict[str, bytes],
    ) -> tuple[ParsedViewpoint, ...]:
        """Resolve each ``<ViewPoint>`` entry against its sibling .bcfv blob."""
        containers: list = []
        vc = topic_el.find("Viewpoints")
        if vc is not None:
            containers.append(vc)
        # 2.1 fallback (Viewpoints sibling of Topic).
        vc2 = markup_root.find("Viewpoints")
        if vc2 is not None and vc2 is not vc:
            containers.append(vc2)

        out: list[ParsedViewpoint] = []
        for container in containers:
            for vp_el in container.findall("ViewPoint"):
                guid = _normalize_guid(vp_el.get("Guid"))
                if not guid:
                    continue
                bcfv_ref = (_text_or_none(vp_el, "Viewpoint") or f"{guid}.bcfv").lower()
                blob = bcfv_blobs.get(bcfv_ref)
                vp = self._parse_viewpoint_blob(guid, blob)
                if vp is not None:
                    out.append(vp)
        return tuple(out)

    def _parse_viewpoint_blob(self, guid: str, blob: bytes | None) -> ParsedViewpoint | None:
        """Decode one .bcfv file into a :class:`ParsedViewpoint`.

        Missing / unreadable .bcfv → return a viewpoint with the guid
        but no camera (so the consumer still sees the reference).
        """
        if blob is None:
            return ParsedViewpoint(guid=guid, camera_type="")
        try:
            root = self._parse_xml(blob)
        except ET.ParseError:
            return ParsedViewpoint(guid=guid, camera_type="")

        # Camera
        camera_type = ""
        view_point = direction = up = (0.0, 0.0, 0.0)
        fov: float | None = None
        v2w: float | None = None
        aspect: float | None = None

        pc = root.find("PerspectiveCamera")
        oc = root.find("OrthogonalCamera")
        if pc is not None:
            camera_type = "perspective"
            view_point = _read_xyz(pc, "CameraViewPoint")
            direction = _read_xyz(pc, "CameraDirection")
            up = _read_xyz(pc, "CameraUpVector")
            fov_raw = (pc.findtext("FieldOfView") or "").strip() or None
            fov = _to_float(fov_raw) if fov_raw else None
            aspect_raw = (pc.findtext("AspectRatio") or "").strip() or None
            aspect = _to_float(aspect_raw) if aspect_raw else None
        elif oc is not None:
            camera_type = "orthogonal"
            view_point = _read_xyz(oc, "CameraViewPoint")
            direction = _read_xyz(oc, "CameraDirection")
            up = _read_xyz(oc, "CameraUpVector")
            v2w_raw = (oc.findtext("ViewToWorldScale") or "").strip() or None
            v2w = _to_float(v2w_raw) if v2w_raw else None
            aspect_raw = (oc.findtext("AspectRatio") or "").strip() or None
            aspect = _to_float(aspect_raw) if aspect_raw else None

        # Components
        default_vis, visible, hidden, selection = self._decode_components(root)

        # Clipping planes
        cp_root = root.find("ClippingPlanes")
        clipping: list[ParsedClippingPlane] = []
        if cp_root is not None:
            for plane in cp_root.findall("ClippingPlane"):
                clipping.append(
                    ParsedClippingPlane(
                        location=_read_xyz(plane, "Location"),
                        direction=_read_xyz(plane, "Direction"),
                    )
                )

        return ParsedViewpoint(
            guid=guid,
            camera_type=camera_type,
            camera_view_point=view_point,
            camera_direction=direction,
            camera_up_vector=up,
            field_of_view=fov,
            view_to_world_scale=v2w,
            aspect_ratio=aspect,
            default_visibility=default_vis,
            visible=tuple(visible),
            hidden=tuple(hidden),
            selection=tuple(selection),
            clipping_planes=tuple(clipping),
        )

    def _decode_components(self, root) -> tuple[bool, list[str], list[str], list[str]]:
        """Decode Visibility + Selection per BCF 3.0 components.xsd.

        Visibility rule (inverse of :func:`writer._build_visinfo_xml`):
        if ``DefaultVisibility="true"``, the Exceptions list is the
        *hidden* set; if ``DefaultVisibility="false"``, Exceptions is
        the *visible* set. Two callers can populate ``visible`` and
        ``hidden`` mutually-exclusively this way and the reader will
        always recover one populated list per topic.
        """
        comps_el = root.find("Components")
        default_vis = True
        visible: list[str] = []
        hidden: list[str] = []
        selection: list[str] = []
        if comps_el is None:
            return default_vis, visible, hidden, selection

        sel_el = comps_el.find("Selection")
        if sel_el is not None:
            for c in sel_el.findall("Component"):
                gid = c.get("IfcGuid")
                if gid:
                    selection.append(gid)

        vis_el = comps_el.find("Visibility")
        if vis_el is not None:
            raw_default = (vis_el.get("DefaultVisibility") or "true").strip()
            default_vis = raw_default.lower() != "false"
            exc_el = vis_el.find("Exceptions")
            exceptions: list[str] = []
            if exc_el is not None:
                for c in exc_el.findall("Component"):
                    gid = c.get("IfcGuid")
                    if gid:
                        exceptions.append(gid)
            if default_vis:
                hidden = exceptions
            else:
                visible = exceptions
        return default_vis, visible, hidden, selection


# ── BCF 2.1 timezone helper (Python <3.11 compat) ─────────────────────────
#
# Some authoring tools emit Indian / Nepalese half-hour offsets ("+05:30",
# "+05:45") which Python parses fine — but we still document the support
# matrix here so a future maintainer doesn't try to "simplify" _parse_dt.
_FRACTIONAL_OFFSETS_OK = (
    timezone(timedelta(hours=5, minutes=30)),
    timezone(timedelta(hours=5, minutes=45)),
)
