# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍BCF 3.0 zip writer — high-level builder API.

This module provides :class:`BCFWriter`, an instance-style builder that
assembles a valid BCF 3.0 ``.bcfzip`` from clash topics + viewpoints
without any third-party dependencies (``zipfile`` + ``xml.etree`` only).

Design goals
------------
1. **No IfcOpenShell.** CLAUDE.md §3 forbids a runtime BIM-toolkit
   dependency. BCF is "XML over data", so the writer is stdlib-only.
2. **Production-deterministic.** The XML attribute order is stable
   (Python 3.8+ dict insertion order) and dates always serialise as ISO
   8601 UTC with the ``Z`` suffix, so two exports of the same data are
   byte-identical for a clean diff workflow.
3. **Shorter-list visibility encoding.** BCF 3.0 ``Visibility`` carries
   a ``DefaultVisibility`` bool + an ``Exceptions`` list. We always
   emit whichever side (visible / hidden) is shorter and flip
   ``DefaultVisibility`` to match — exactly per the BCF 3.0 markup.xsd
   guidance.
4. **Safe filenames.** Topic-folder names come from the Topic GUID
   (validated as RFC 4122) — never from user-controlled text — so a
   malicious title can never escape the archive root.

Public API
----------
* :class:`BCFTopic`             — topic data transfer object
* :class:`BCFComment`           — comment DTO
* :class:`BCFViewpoint`         — viewpoint DTO (camera + components)
* :class:`BCFWriter`            — the builder
* :data:`BCF_VERSION`           — the schema version this writer emits

The writer is purposely **3.0-only** — the platform's BCF 2.1 export
already lives in :mod:`app.modules.bcf.bcf_xml.build_bcfzip`; this
module is the new clash-coordination surface and ships the modern
schema by default.
"""

from __future__ import annotations

import io
import re
import uuid as _uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime

BCF_VERSION: str = "3.0"

# BCF 3.0 fixed enum lists per extensions.xsd. Callers can override via
# ``BCFWriter.add_extension_list`` but these stay the defaults so an
# export without explicit configuration still round-trips cleanly.
_DEFAULT_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "TopicTypes": ("Issue", "Information", "Clash", "Inquiry", "Solution"),
    "TopicStatuses": ("Open", "In Progress", "Closed", "ReOpened"),
    "Priorities": ("Critical", "Major", "Normal", "Minor"),
    "TopicLabels": (),
    "Users": (),
    "Stages": (),
    "SnippetTypes": (".docx", ".pdf", ".txt"),
}

# Topic GUIDs we accept. RFC 4122 hex form with optional braces. The
# writer always strips the braces and lowercases the result before using
# it as a directory name inside the archive.
_GUID_RE = re.compile(
    r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
)

# The clash module currently uses a 16-char SHA-1 hex prefix as a stable
# clash signature. We accept it as a topic id as well so the
# clash-→-BCF export can use the signature for deterministic round-trip.
_HEX_SIG_RE = re.compile(r"^[0-9a-fA-F]{8,64}$")


# ── DTOs ───────────────────────────────────────────────────────────────────


@dataclass
class BCFViewpoint:
    """‌⁠‍Viewpoint DTO ready for BCF 3.0 serialisation.

    A viewpoint must declare exactly one of perspective / orthogonal
    camera, plus its component visibility model. ``visible`` /
    ``hidden`` are IFC GUID lists; whichever is shorter is emitted as
    the ``<Exceptions>`` block (with ``DefaultVisibility`` flipped
    accordingly), per BCF 3.0 spec.
    """

    guid: str
    camera_type: str = "perspective"  # "perspective" | "orthogonal"
    camera_view_point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    camera_direction: tuple[float, float, float] = (0.0, -1.0, 0.0)
    camera_up_vector: tuple[float, float, float] = (0.0, 0.0, 1.0)
    field_of_view: float = 60.0
    view_to_world_scale: float = 1.0
    aspect_ratio: float = 1.7777778  # 16:9 default — matches buildingSMART samples
    default_visibility: bool = True
    visible: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    selection: list[str] = field(default_factory=list)
    snapshot_png: bytes | None = None


@dataclass
class BCFComment:
    """‌⁠‍Comment DTO (the four BCF 3.0 required fields)."""

    guid: str
    date: datetime
    author: str
    comment: str
    viewpoint_guid: str | None = None
    modified_date: datetime | None = None
    modified_author: str | None = None


@dataclass
class BCFTopic:
    """‌⁠‍Topic DTO — only the BCF 3.0 mandatory fields are required.

    See https://github.com/buildingSMART/BCF-XML/blob/release_3_0/Schemas/markup.xsd
    for the authoritative schema. Anything not modelled here (custom
    DocumentReferences, BimSnippets) is currently out of scope for the
    clash-coordination export path.
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
    labels: list[str] = field(default_factory=list)
    reference_links: list[str] = field(default_factory=list)
    modified_date: datetime | None = None
    modified_author: str | None = None
    comments: list[BCFComment] = field(default_factory=list)
    viewpoints: list[BCFViewpoint] = field(default_factory=list)


# ── helpers ────────────────────────────────────────────────────────────────


def _iso_utc(dt: datetime) -> str:
    """Serialise ``dt`` as ISO 8601 in UTC with the literal ``Z`` suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize_guid(guid: str) -> str:
    """Return ``guid`` stripped of braces & lowercased.

    A non-RFC-4122 / non-hex-signature value is left as-is so a caller
    that already has a deterministic clash-signature id (16-hex SHA-1
    prefix) can still use it as a Topic GUID. Filename safety is
    enforced separately by :func:`_safe_dir`.
    """
    g = guid.strip().strip("{}").lower()
    return g


def _safe_dir(guid: str) -> str:
    """Reject any topic GUID that isn't pure hex / RFC-4122.

    Topic folder names go straight into the zip's internal path, so
    they must never contain a slash, dot-dot, or shell-special char.
    """
    g = _normalize_guid(guid)
    if _GUID_RE.match(g) or _HEX_SIG_RE.match(g):
        return g
    raise ValueError(f"BCF topic GUID {guid!r} is not a valid RFC 4122 UUID or hex signature")


def _serialise(root: ET.Element) -> bytes:
    """Serialise an element tree with the UTF-8 XML declaration."""
    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def _vec(parent: ET.Element, tag: str, xyz: tuple[float, float, float]) -> None:
    """Append a ``<tag><X/><Y/><Z/></tag>`` block. Stable child order."""
    el = ET.SubElement(parent, tag)
    ET.SubElement(el, "X").text = repr(float(xyz[0]))
    ET.SubElement(el, "Y").text = repr(float(xyz[1]))
    ET.SubElement(el, "Z").text = repr(float(xyz[2]))


# ── per-document builders ──────────────────────────────────────────────────


def build_version_xml() -> bytes:
    """Build the BCF 3.0 ``bcf.version`` document."""
    root = ET.Element("Version", {"VersionId": BCF_VERSION})
    return _serialise(root)


def build_project_xml(project_id: str, project_name: str) -> bytes:
    """Build a BCF 3.0 ``project.bcfp`` (ProjectInfo wrapper)."""
    root = ET.Element("ProjectInfo")
    proj = ET.SubElement(root, "Project", {"ProjectId": project_id})
    ET.SubElement(proj, "Name").text = project_name
    return _serialise(root)


def build_extensions_xml(lists: dict[str, tuple[str, ...]]) -> bytes:
    """Build the BCF 3.0 ``extensions.xml`` document.

    Every list emits as ``<{Kind}><{Singular}>value</{Singular}></{Kind}>``,
    with the singular tag derived by chopping a trailing ``s`` — matches
    the schema's element naming (``<TopicTypes><TopicType>`` etc.).
    """
    root = ET.Element("Extensions")
    for kind, values in lists.items():
        if not values:
            # Still emit the container so consumers can detect "empty" vs "absent".
            ET.SubElement(root, kind)
            continue
        container = ET.SubElement(root, kind)
        # Singular: ``TopicTypes`` → ``TopicType``; ``SnippetTypes`` → ``SnippetType``.
        # Irregulars: ``Priorities`` → ``Priority``; ``TopicStatuses`` → ``TopicStatus``.
        _IRREGULAR = {
            "Priorities": "Priority",
            "TopicStatuses": "TopicStatus",
        }
        singular = _IRREGULAR[kind] if kind in _IRREGULAR else kind[:-1] if kind.endswith("s") else kind
        for v in values:
            ET.SubElement(container, singular).text = v
    return _serialise(root)


def build_markup_xml(topic: BCFTopic) -> bytes:
    """Build a BCF 3.0 ``markup.bcf`` document for one topic.

    The XML element order matches the markup.xsd ordering so a strict
    XSD-aware reader is happy. Empty optional containers are dropped.
    """
    root = ET.Element("Markup")

    attrib: dict[str, str] = {"Guid": _normalize_guid(topic.guid)}
    if topic.server_assigned_id:
        attrib["ServerAssignedId"] = str(topic.server_assigned_id)
    if topic.topic_type:
        attrib["TopicType"] = topic.topic_type
    if topic.topic_status:
        attrib["TopicStatus"] = topic.topic_status
    topic_el = ET.SubElement(root, "Topic", attrib)

    for link in topic.reference_links:
        ET.SubElement(topic_el, "ReferenceLink").text = link

    ET.SubElement(topic_el, "Title").text = topic.title or ""

    if topic.priority:
        ET.SubElement(topic_el, "Priority").text = topic.priority

    if topic.labels:
        labels_el = ET.SubElement(topic_el, "Labels")
        for lab in topic.labels:
            ET.SubElement(labels_el, "Label").text = lab

    ET.SubElement(topic_el, "CreationDate").text = _iso_utc(topic.creation_date)
    ET.SubElement(topic_el, "CreationAuthor").text = topic.creation_author

    if topic.modified_date:
        ET.SubElement(topic_el, "ModifiedDate").text = _iso_utc(topic.modified_date)
    if topic.modified_author:
        ET.SubElement(topic_el, "ModifiedAuthor").text = topic.modified_author

    if topic.assigned_to:
        ET.SubElement(topic_el, "AssignedTo").text = topic.assigned_to
    if topic.stage:
        ET.SubElement(topic_el, "Stage").text = topic.stage
    if topic.description:
        ET.SubElement(topic_el, "Description").text = topic.description
    if topic.due_date:
        ET.SubElement(topic_el, "DueDate").text = _iso_utc(topic.due_date)

    # Comments — repeated under <Topic> in 3.0.
    for c in topic.comments:
        c_el = ET.SubElement(topic_el, "Comment", {"Guid": _normalize_guid(c.guid)})
        ET.SubElement(c_el, "Date").text = _iso_utc(c.date)
        ET.SubElement(c_el, "Author").text = c.author
        ET.SubElement(c_el, "Comment").text = c.comment or ""
        if c.modified_date:
            ET.SubElement(c_el, "ModifiedDate").text = _iso_utc(c.modified_date)
        if c.modified_author:
            ET.SubElement(c_el, "ModifiedAuthor").text = c.modified_author
        if c.viewpoint_guid:
            ET.SubElement(c_el, "Viewpoint").set("Guid", _normalize_guid(c.viewpoint_guid))

    # Viewpoints — one <Viewpoints><DocumentReference>-style block in 3.0.
    if topic.viewpoints:
        vps_el = ET.SubElement(topic_el, "Viewpoints")
        for vp in topic.viewpoints:
            vp_el = ET.SubElement(vps_el, "ViewPoint", {"Guid": _normalize_guid(vp.guid)})
            ET.SubElement(vp_el, "Viewpoint").text = f"{_normalize_guid(vp.guid)}.bcfv"
            if vp.snapshot_png is not None:
                ET.SubElement(vp_el, "Snapshot").text = "snapshot.png"

    return _serialise(root)


def build_visinfo_xml(vp: BCFViewpoint) -> bytes:
    """Build a BCF 3.0 ``viewpoint.bcfv`` document.

    Emits exactly one camera (perspective or orthogonal) and a
    ``Components`` block whose visibility uses the shorter-list rule:
    the side that yields fewer ``<Component>`` entries becomes the
    explicit Exceptions block, with ``DefaultVisibility`` flipped to
    match. Selection components emit unconditionally.
    """
    root = ET.Element("VisualizationInfo", {"Guid": _normalize_guid(vp.guid)})

    # Components block first (markup.xsd order).
    has_components = vp.selection or vp.visible or vp.hidden
    if has_components:
        comps_el = ET.SubElement(root, "Components")
        # Selection
        if vp.selection:
            sel_el = ET.SubElement(comps_el, "Selection")
            for guid in vp.selection:
                ET.SubElement(sel_el, "Component", {"IfcGuid": guid})
        # Visibility — shorter-list rule
        vis_el = ET.SubElement(comps_el, "Visibility")
        # If both sides are populated, the one with fewer entries wins. If
        # only one side is populated we still flip DefaultVisibility to
        # encode the right meaning (a "visible" list of N items means
        # "everything else is hidden", so DefaultVisibility=false +
        # Exceptions=visible).
        if vp.visible and vp.hidden:
            if len(vp.visible) <= len(vp.hidden):
                default_vis = False
                exceptions = vp.visible
            else:
                default_vis = True
                exceptions = vp.hidden
        elif vp.visible and not vp.hidden:
            default_vis = False
            exceptions = vp.visible
        elif vp.hidden and not vp.visible:
            default_vis = True
            exceptions = vp.hidden
        else:
            default_vis = vp.default_visibility
            exceptions = []
        vis_el.set("DefaultVisibility", "true" if default_vis else "false")
        if exceptions:
            exc_el = ET.SubElement(vis_el, "Exceptions")
            for guid in exceptions:
                ET.SubElement(exc_el, "Component", {"IfcGuid": guid})

    # Camera — exactly one.
    if vp.camera_type == "orthogonal":
        cam_el = ET.SubElement(root, "OrthogonalCamera")
        _vec(cam_el, "CameraViewPoint", vp.camera_view_point)
        _vec(cam_el, "CameraDirection", vp.camera_direction)
        _vec(cam_el, "CameraUpVector", vp.camera_up_vector)
        ET.SubElement(cam_el, "ViewToWorldScale").text = repr(float(vp.view_to_world_scale))
        ET.SubElement(cam_el, "AspectRatio").text = repr(float(vp.aspect_ratio))
    else:
        cam_el = ET.SubElement(root, "PerspectiveCamera")
        _vec(cam_el, "CameraViewPoint", vp.camera_view_point)
        _vec(cam_el, "CameraDirection", vp.camera_direction)
        _vec(cam_el, "CameraUpVector", vp.camera_up_vector)
        ET.SubElement(cam_el, "FieldOfView").text = repr(float(vp.field_of_view))
        ET.SubElement(cam_el, "AspectRatio").text = repr(float(vp.aspect_ratio))

    return _serialise(root)


# ── builder ────────────────────────────────────────────────────────────────


class BCFWriter:
    """‌⁠‍Fluent builder for a BCF 3.0 ``.bcfzip`` archive.

    Usage
    -----
    >>> w = BCFWriter()
    >>> w.set_project("proj-1", "My Project")
    >>> w.add_topic(topic)
    >>> blob = w.build_bytes()

    The builder accumulates topics + extensions in memory and writes
    everything in one shot inside :meth:`build_bytes`. There is no
    incremental zip streaming on purpose: a BCF coordination archive is
    small (markup + tiny PNGs) and an atomic ``bytes`` return makes the
    caller's life easier (HTTP body, tests, blob storage).
    """

    def __init__(self) -> None:
        self._topics: list[BCFTopic] = []
        self._extensions: dict[str, tuple[str, ...]] = dict(_DEFAULT_EXTENSIONS)
        self._project_id: str | None = None
        self._project_name: str | None = None
        self._seen_guids: set[str] = set()

    # ── public API ───────────────────────────────────────────────────

    def set_project(self, project_id: str, project_name: str) -> BCFWriter:
        """Stamp a ``project.bcfp`` into the archive (optional but recommended)."""
        if not project_id:
            raise ValueError("project_id must be a non-empty string")
        self._project_id = str(project_id)
        self._project_name = str(project_name or "")
        return self

    def add_extension_list(self, kind: str, values: list[str] | tuple[str, ...]) -> BCFWriter:
        """Override a default extension enum list.

        Args:
            kind: ``"TopicTypes" | "TopicStatuses" | "Priorities" |
                "TopicLabels" | "Users" | "Stages" | "SnippetTypes"``.
            values: Allowed values for that enum.

        Raises:
            ValueError: if ``kind`` is unknown.
        """
        if kind not in _DEFAULT_EXTENSIONS:
            raise ValueError(f"Unknown extension list {kind!r}; expected one of {sorted(_DEFAULT_EXTENSIONS)}")
        # Stable de-duplication preserving first-seen order.
        seen: set[str] = set()
        cleaned: list[str] = []
        for v in values:
            s = str(v)
            if s and s not in seen:
                seen.add(s)
                cleaned.append(s)
        self._extensions[kind] = tuple(cleaned)
        return self

    def add_topic(self, topic: BCFTopic) -> BCFWriter:
        """Append a topic to the archive.

        Validates the GUID (RFC 4122 or hex signature), the required
        fields and rejects a duplicate GUID. Comment / viewpoint GUIDs
        get the same sanity pass.
        """
        if not isinstance(topic, BCFTopic):
            raise TypeError(f"expected BCFTopic, got {type(topic).__name__}")
        guid = _safe_dir(topic.guid)
        if guid in self._seen_guids:
            raise ValueError(f"duplicate BCF topic GUID {guid!r}")
        if not topic.topic_type:
            raise ValueError("BCFTopic.topic_type is required")
        if not topic.topic_status:
            raise ValueError("BCFTopic.topic_status is required")
        if not topic.title:
            raise ValueError("BCFTopic.title is required")
        if not topic.creation_date:
            raise ValueError("BCFTopic.creation_date is required")
        if not topic.creation_author:
            raise ValueError("BCFTopic.creation_author is required")
        for c in topic.comments:
            _safe_dir(c.guid)
            if not c.date:
                raise ValueError(f"comment {c.guid!r} on topic {guid!r}: date is required")
            if not c.author:
                raise ValueError(f"comment {c.guid!r} on topic {guid!r}: author is required")
        for v in topic.viewpoints:
            _safe_dir(v.guid)
            if v.camera_type not in ("perspective", "orthogonal"):
                raise ValueError(f"viewpoint {v.guid!r} on topic {guid!r}: unknown camera_type {v.camera_type!r}")
        self._topics.append(topic)
        self._seen_guids.add(guid)
        return self

    @property
    def topics(self) -> tuple[BCFTopic, ...]:
        """Read-only view of the accumulated topics (for tests / debugging)."""
        return tuple(self._topics)

    def build_bytes(self) -> bytes:
        """Materialise the BCF 3.0 zip and return its raw bytes."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bcf.version", build_version_xml())
            zf.writestr("extensions.xml", build_extensions_xml(self._extensions))
            if self._project_id is not None:
                zf.writestr(
                    "project.bcfp",
                    build_project_xml(self._project_id, self._project_name or self._project_id),
                )
            for topic in self._topics:
                folder = _safe_dir(topic.guid)
                zf.writestr(f"{folder}/markup.bcf", build_markup_xml(topic))
                for vp in topic.viewpoints:
                    vp_name = _safe_dir(vp.guid)
                    zf.writestr(
                        f"{folder}/{vp_name}.bcfv",
                        build_visinfo_xml(vp),
                    )
                    if vp.snapshot_png is not None:
                        if not vp.snapshot_png.startswith(b"\x89PNG\r\n\x1a\n"):
                            raise ValueError(f"viewpoint {vp.guid!r}: snapshot_png is not a PNG")
                        zf.writestr(f"{folder}/snapshot.png", vp.snapshot_png)
        return buf.getvalue()


# ── convenience: synthesize a viewpoint from a clash centroid ─────────────


def synthesize_viewpoint_from_centroid(
    centroid: tuple[float, float, float],
    *,
    distance_m: float = 5.0,
    selection: list[str] | None = None,
    aspect_ratio: float = 1.7777778,
) -> BCFViewpoint:
    """Construct a perspective viewpoint 5m back from ``centroid``.

    Looks down the +Y axis at the centroid with +Z up — the canonical
    "isometric-ish" coordination camera. Handy when a clash row has a
    centroid but no native viewpoint of its own.
    """
    cx, cy, cz = centroid
    return BCFViewpoint(
        guid=str(_uuid.uuid4()),
        camera_type="perspective",
        camera_view_point=(cx, cy - distance_m, cz + distance_m * 0.5),
        camera_direction=(0.0, 1.0, -0.4),
        camera_up_vector=(0.0, 0.0, 1.0),
        field_of_view=60.0,
        aspect_ratio=aspect_ratio,
        selection=list(selection or []),
    )
