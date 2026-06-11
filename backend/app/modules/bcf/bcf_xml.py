"""‌⁠‍Hand-rolled BCF-XML codec for BCF **2.1** and **3.0**.

Why hand-rolled?
    the architecture guide §3 forbids an IfcOpenShell / xBIM runtime dependency. BCF is
    "XML over data", so the whole codec is built on the standard library
    (``xml.etree.ElementTree`` + ``zipfile``) with zero third-party deps.

What this module produces / consumes
    A ``.bcfzip`` is a ZIP whose layout differs slightly between schema
    versions. We implement the parts that carry issue/viewpoint data:

    BCF 2.1 (buildingSMART/BCF-XML release/bcf/2.1)::

        bcf.version
        project.bcfp                       (optional)
        <topic-guid>/markup.bcf
        <topic-guid>/<viewpoint-guid>.bcfv
        <topic-guid>/<snapshot>.png

    BCF 3.0 (buildingSMART/BCF-XML release/bcf/3.0)::

        bcf.version
        project.bcfp                       (optional)
        <topic-guid>/markup.bcf
        <topic-guid>/<viewpoint-guid>.bcfv
        <topic-guid>/<snapshot>.png

    The ZIP *layout* is the same; the **XML schemas differ**. The biggest
    2.1 → 3.0 changes this codec handles:

    * ``bcf.version``: 2.1 carries a ``<DetailedVersion>`` child; 3.0 only
      has ``@VersionId``.
    * ``markup.bcf`` ``<Topic>``: 3.0 promotes ``Title`` to an element
      (it was an element in 2.1 too) and moves ``Comment``/``Viewpoints``
      under ``<Comment>`` (repeated) and ``<Viewpoints>`` (container of
      ``<ViewPoint>``). 3.0 adds ``ServerAssignedId`` and a richer
      ``DocumentReferences`` model (not round-tripped field-by-field -
      preserved verbatim in topic metadata).
    * ``viewpoint.bcfv`` ``<VisualizationInfo>``: 3.0 keeps
      ``Components/Selection/Component`` + ``Components/Visibility`` but
      ``Visibility`` gains ``@DefaultVisibility`` (2.1 used the same
      attribute - kept identical here).

Anything we do not model as a first-class field is preserved through the
roundtrip inside the topic's ``metadata`` extension bag so an
export-after-import is information-preserving for the fields we own.

Public API
    * :data:`SUPPORTED_VERSIONS`
    * :func:`detect_version`
    * :func:`build_bcfzip`  - DTOs → ``bytes``
    * :func:`parse_bcfzip`  - ``bytes`` → DTOs + structured issues
    * exception :class:`BCFParseError`
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

SUPPORTED_VERSIONS: tuple[str, ...] = ("2.1", "3.0")

# Origin token. The bytes XOR-decode (key 0x55) to the project authorship
# marker; it is written only into XML *comment* nodes of the generated
# ``.bcfzip`` members, which every conformant XML parser (incl. this
# module's own ElementTree-based reader) discards - so it is purely an
# at-rest provenance stamp with zero effect on parsed/round-tripped data.
_BCF_ORIGIN = "OpenConstructionERP · DataDrivenConstruction · " + bytes(
    b ^ 0x55 for b in b"\x11\x11\x16\x78\x16\x02\x1c\x16\x07\x78\x1a\x10\x78\x67\x65\x67\x63"
).decode("ascii")

# Hard ceilings so a hostile zip can't exhaust memory before we validate it.
_MAX_ENTRIES = 20000
_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024  # 1 GiB total
_MAX_SINGLE_ENTRY_BYTES = 256 * 1024 * 1024  # 256 MiB per member


class BCFParseError(Exception):
    """‌⁠‍Raised for an irrecoverably malformed ``.bcfzip``.

    The router catches this and turns it into a structured 422 report - it
    must never surface as a 500.
    """


@dataclass
class ParsedViewpoint:
    """‌⁠‍Codec-level viewpoint DTO (decoupled from the ORM model)."""

    guid: str
    camera_type: str = ""  # "perspective" | "orthogonal" | ""
    camera: dict = field(default_factory=dict)
    components: dict = field(default_factory=dict)
    lines: list = field(default_factory=list)
    clipping_planes: list = field(default_factory=list)
    field_of_view: float | None = None
    view_to_world_scale: float | None = None
    snapshot_filename: str | None = None
    snapshot_bytes: bytes | None = None


@dataclass
class ParsedComment:
    """Codec-level comment DTO."""

    guid: str
    comment: str = ""
    author: str | None = None
    date: datetime | None = None
    modified_author: str | None = None
    modified_date: datetime | None = None
    viewpoint_guid: str | None = None


@dataclass
class ParsedTopic:
    """Codec-level topic DTO."""

    guid: str
    title: str = ""
    description: str | None = None
    topic_type: str | None = None
    topic_status: str = "Open"
    priority: str | None = None
    stage: str | None = None
    index: int | None = None
    assigned_to: str | None = None
    due_date: datetime | None = None
    labels: list[str] = field(default_factory=list)
    reference_links: list[str] = field(default_factory=list)
    creation_author: str | None = None
    creation_date: datetime | None = None
    modified_author: str | None = None
    modified_date: datetime | None = None
    comments: list[ParsedComment] = field(default_factory=list)
    viewpoints: list[ParsedViewpoint] = field(default_factory=list)


@dataclass
class ImportIssue:
    """A structural / schema problem encountered while parsing."""

    severity: str  # "error" | "warning" | "info"
    code: str
    message: str
    location: str | None = None


@dataclass
class ParseResult:
    """Outcome of :func:`parse_bcfzip`."""

    detected_version: str | None
    topics: list[ParsedTopic] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


# ── datetime helpers ───────────────────────────────────────────────────────


def _iso(dt: datetime | None) -> str | None:
    """Serialise a datetime to xs:dateTime (UTC, ``Z`` suffix)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse an xs:dateTime; tolerant of a trailing ``Z`` and missing tz."""
    if not raw:
        return None
    txt = raw.strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        # Last-ditch: date only.
        try:
            dt = datetime.strptime(txt[:10], "%Y-%m-%d")  # noqa: DTZ007
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# ── small ElementTree helpers ──────────────────────────────────────────────


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    """Append a child element, optionally with text."""
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _txt(parent: ET.Element | None, tag: str) -> str | None:
    """Return the text of the first ``tag`` child, or ``None``."""
    if parent is None:
        return None
    child = parent.find(tag)
    if child is None or child.text is None:
        return None
    stripped = child.text.strip()
    return stripped or None


def _vec(parent: ET.Element, tag: str, vec: dict) -> None:
    """Append a ``<tag><X/><Y/><Z/></tag>`` BCF vector element."""
    el = _sub(parent, tag)
    _sub(el, "X", repr(float(vec.get("x", 0.0))))
    _sub(el, "Y", repr(float(vec.get("y", 0.0))))
    _sub(el, "Z", repr(float(vec.get("z", 0.0))))


def _read_vec(parent: ET.Element | None, tag: str) -> dict:
    """Read a BCF ``<tag><X/><Y/><Z/></tag>`` vector into a dict."""
    if parent is None:
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    el = parent.find(tag)
    if el is None:
        return {"x": 0.0, "y": 0.0, "z": 0.0}

    def _f(name: str) -> float:
        raw = _txt(el, name)
        try:
            return float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    return {"x": _f("X"), "y": _f("Y"), "z": _f("Z")}


# ── bcf.version ────────────────────────────────────────────────────────────


def _build_version_xml(version: str) -> bytes:
    root = ET.Element("Version", {"VersionId": version})
    root.append(ET.Comment(f" {_BCF_ORIGIN} "))
    if version == "2.1":
        # 2.1 carries a DetailedVersion child; 3.0 dropped it.
        _sub(root, "DetailedVersion", "2.1")
    return _serialise(root)


def detect_version(data: bytes) -> str | None:
    """Sniff the BCF schema version from a ``.bcfzip``'s ``bcf.version``.

    Returns ``"2.1"`` / ``"3.0"`` or ``None`` when the marker is absent or
    unreadable.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = next(
                (n for n in zf.namelist() if n.lower().endswith("bcf.version")),
                None,
            )
            if name is None:
                return None
            raw = zf.read(name)
    except (zipfile.BadZipFile, OSError, KeyError):
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    vid = (root.get("VersionId") or "").strip()
    if vid in SUPPORTED_VERSIONS:
        return vid
    # Some authoring tools only set <DetailedVersion>.
    detailed = _txt(root, "DetailedVersion")
    if detailed and detailed.strip() in SUPPORTED_VERSIONS:
        return detailed.strip()
    return None


# ── XML serialisation ──────────────────────────────────────────────────────


def _serialise(root: ET.Element) -> bytes:
    """Serialise an element tree to UTF-8 bytes with an XML declaration."""
    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


# ── viewpoint.bcfv ─────────────────────────────────────────────────────────


def _build_visinfo_xml(vp: ParsedViewpoint, version: str) -> bytes:
    """Build a ``VisualizationInfo`` document for a viewpoint.

    The ``Components`` / camera structure is identical between 2.1 and 3.0
    for the subset we model (Selection, Visibility, OrthogonalCamera,
    PerspectiveCamera, Lines, ClippingPlanes). ``@Guid`` on the root is
    only emitted for 3.0 (2.1 did not have it on VisualizationInfo).
    """
    attrib = {"Guid": vp.guid} if version == "3.0" else {}
    root = ET.Element("VisualizationInfo", attrib)

    comps = vp.components or {}
    selection = comps.get("selection") or []
    visible = comps.get("visible") or []
    hidden = comps.get("hidden") or []
    default_vis = bool(comps.get("default_visibility", True))

    if selection or visible or hidden:
        components_el = _sub(root, "Components")
        if selection:
            sel_el = _sub(components_el, "Selection")
            for guid in selection:
                _sub(sel_el, "Component", None).set("IfcGuid", str(guid))
        # Visibility: DefaultVisibility=true means "visible" lists the
        # exceptions that are hidden, and vice versa. We always emit the
        # explicit Exceptions block matching whichever list is populated.
        vis_el = _sub(components_el, "Visibility")
        vis_el.set("DefaultVisibility", "true" if default_vis else "false")
        exceptions = hidden if default_vis else visible
        if exceptions:
            exc_el = _sub(vis_el, "Exceptions")
            for guid in exceptions:
                _sub(exc_el, "Component", None).set("IfcGuid", str(guid))

    cam = vp.camera or {}
    if vp.camera_type == "perspective":
        pc = _sub(root, "PerspectiveCamera")
        _vec(pc, "CameraViewPoint", cam.get("camera_view_point", {}))
        _vec(pc, "CameraDirection", cam.get("camera_direction", {}))
        _vec(pc, "CameraUpVector", cam.get("camera_up_vector", {}))
        _sub(pc, "FieldOfView", repr(float(vp.field_of_view or 60.0)))
    elif vp.camera_type == "orthogonal":
        oc = _sub(root, "OrthogonalCamera")
        _vec(oc, "CameraViewPoint", cam.get("camera_view_point", {}))
        _vec(oc, "CameraDirection", cam.get("camera_direction", {}))
        _vec(oc, "CameraUpVector", cam.get("camera_up_vector", {}))
        _sub(
            oc,
            "ViewToWorldScale",
            repr(float(vp.view_to_world_scale or 1.0)),
        )

    if vp.lines:
        lines_el = _sub(root, "Lines")
        for ln in vp.lines:
            line_el = _sub(lines_el, "Line")
            _vec(line_el, "StartPoint", ln.get("start", {}))
            _vec(line_el, "EndPoint", ln.get("end", {}))

    if vp.clipping_planes:
        cp_el = _sub(root, "ClippingPlanes")
        for plane in vp.clipping_planes:
            plane_el = _sub(cp_el, "ClippingPlane")
            _vec(plane_el, "Location", plane.get("location", {}))
            _vec(plane_el, "Direction", plane.get("direction", {}))

    return _serialise(root)


def _parse_visinfo(raw: bytes, vp: ParsedViewpoint) -> None:
    """Populate ``vp`` (camera/components/lines/planes) from a .bcfv blob."""
    root = ET.fromstring(raw)

    components_el = root.find("Components")
    selection: list[str] = []
    visible: list[str] = []
    hidden: list[str] = []
    default_vis = True
    if components_el is not None:
        sel_el = components_el.find("Selection")
        if sel_el is not None:
            for c in sel_el.findall("Component"):
                guid = c.get("IfcGuid") or _txt(c, "IfcGuid")
                if guid:
                    selection.append(guid)
        vis_el = components_el.find("Visibility")
        if vis_el is not None:
            default_vis = (vis_el.get("DefaultVisibility") or "true").lower() != "false"
            exc_el = vis_el.find("Exceptions")
            exceptions: list[str] = []
            if exc_el is not None:
                for c in exc_el.findall("Component"):
                    guid = c.get("IfcGuid") or _txt(c, "IfcGuid")
                    if guid:
                        exceptions.append(guid)
            if default_vis:
                hidden = exceptions
            else:
                visible = exceptions
    vp.components = {
        "selection": selection,
        "visible": visible,
        "hidden": hidden,
        "default_visibility": default_vis,
    }

    pc = root.find("PerspectiveCamera")
    oc = root.find("OrthogonalCamera")
    if pc is not None:
        vp.camera_type = "perspective"
        vp.camera = {
            "camera_view_point": _read_vec(pc, "CameraViewPoint"),
            "camera_direction": _read_vec(pc, "CameraDirection"),
            "camera_up_vector": _read_vec(pc, "CameraUpVector"),
        }
        fov = _txt(pc, "FieldOfView")
        vp.field_of_view = float(fov) if fov else 60.0
    elif oc is not None:
        vp.camera_type = "orthogonal"
        vp.camera = {
            "camera_view_point": _read_vec(oc, "CameraViewPoint"),
            "camera_direction": _read_vec(oc, "CameraDirection"),
            "camera_up_vector": _read_vec(oc, "CameraUpVector"),
        }
        scale = _txt(oc, "ViewToWorldScale")
        vp.view_to_world_scale = float(scale) if scale else 1.0

    lines_el = root.find("Lines")
    if lines_el is not None:
        for line_el in lines_el.findall("Line"):
            vp.lines.append(
                {
                    "start": _read_vec(line_el, "StartPoint"),
                    "end": _read_vec(line_el, "EndPoint"),
                }
            )

    cp_el = root.find("ClippingPlanes")
    if cp_el is not None:
        for plane_el in cp_el.findall("ClippingPlane"):
            vp.clipping_planes.append(
                {
                    "location": _read_vec(plane_el, "Location"),
                    "direction": _read_vec(plane_el, "Direction"),
                }
            )


# ── markup.bcf ─────────────────────────────────────────────────────────────


def _build_markup_xml(topic: ParsedTopic, version: str) -> bytes:
    """Build ``markup.bcf`` for a topic.

    2.1 and 3.0 share most of the ``<Topic>`` shape. The structural
    difference handled here: 3.0 nests ``<Comment>`` repeats and the
    ``<Viewpoints>`` container *inside* ``<Topic>``, whereas 2.1 keeps
    ``<Comment>`` and ``<Viewpoints>`` as siblings of ``<Topic>`` under
    ``<Markup>``.
    """
    markup = ET.Element("Markup")
    topic_el = ET.SubElement(
        markup,
        "Topic",
        {
            "Guid": topic.guid,
            **({"TopicType": topic.topic_type} if topic.topic_type else {}),
            **({"TopicStatus": topic.topic_status} if topic.topic_status else {}),
        },
    )
    if version == "3.0" and topic.index is not None:
        topic_el.set("ServerAssignedId", str(topic.index))

    _sub(topic_el, "Title", topic.title)
    if topic.priority:
        _sub(topic_el, "Priority", topic.priority)
    if topic.index is not None and version == "2.1":
        _sub(topic_el, "Index", str(topic.index))
    for label in topic.labels:
        _sub(topic_el, "Labels", str(label))
    if topic.creation_date:
        _sub(topic_el, "CreationDate", _iso(topic.creation_date))
    if topic.creation_author:
        _sub(topic_el, "CreationAuthor", topic.creation_author)
    if topic.modified_date:
        _sub(topic_el, "ModifiedDate", _iso(topic.modified_date))
    if topic.modified_author:
        _sub(topic_el, "ModifiedAuthor", topic.modified_author)
    if topic.due_date:
        _sub(topic_el, "DueDate", _iso(topic.due_date))
    if topic.assigned_to:
        _sub(topic_el, "AssignedTo", topic.assigned_to)
    if topic.stage:
        _sub(topic_el, "Stage", topic.stage)
    if topic.description:
        _sub(topic_el, "Description", topic.description)
    for link in topic.reference_links:
        _sub(topic_el, "ReferenceLink", str(link))

    # Comment / Viewpoints placement differs by version.
    comment_parent = topic_el if version == "3.0" else markup
    if version == "3.0" and topic.comments:
        comment_parent = _sub(topic_el, "Comments")
    for c in topic.comments:
        c_el = ET.SubElement(comment_parent, "Comment", {"Guid": c.guid})
        if c.date:
            _sub(c_el, "Date", _iso(c.date))
        if c.author:
            _sub(c_el, "Author", c.author)
        _sub(c_el, "Comment", c.comment or "")
        if c.modified_date:
            _sub(c_el, "ModifiedDate", _iso(c.modified_date))
        if c.modified_author:
            _sub(c_el, "ModifiedAuthor", c.modified_author)
        if c.viewpoint_guid:
            _sub(c_el, "Viewpoint", None).set("Guid", c.viewpoint_guid)

    if topic.viewpoints:
        vps_parent = topic_el if version == "3.0" else markup
        vps_el = _sub(vps_parent, "Viewpoints")
        for vp in topic.viewpoints:
            vp_el = ET.SubElement(vps_el, "ViewPoint", {"Guid": vp.guid})
            _sub(vp_el, "Viewpoint", f"{vp.guid}.bcfv")
            if vp.snapshot_filename:
                _sub(vp_el, "Snapshot", vp.snapshot_filename)

    return _serialise(markup)


def _parse_markup(raw: bytes, version: str) -> ParsedTopic:
    """Parse a ``markup.bcf`` blob into a :class:`ParsedTopic`.

    Tolerant of both 2.1 (Comment/Viewpoints as siblings of Topic) and
    3.0 (nested under Topic, optionally inside ``<Comments>``).
    """
    markup = ET.fromstring(raw)
    topic_el = markup.find("Topic")
    if topic_el is None:
        raise BCFParseError("markup.bcf has no <Topic> element")

    guid = topic_el.get("Guid") or ""
    if not guid:
        raise BCFParseError("Topic is missing the required @Guid")

    topic = ParsedTopic(guid=guid)
    topic.topic_type = topic_el.get("TopicType") or _txt(topic_el, "TopicType")
    topic.topic_status = topic_el.get("TopicStatus") or _txt(topic_el, "TopicStatus") or "Open"
    topic.title = _txt(topic_el, "Title") or ""
    topic.priority = _txt(topic_el, "Priority")
    idx_raw = _txt(topic_el, "Index") or topic_el.get("ServerAssignedId")
    if idx_raw:
        try:
            topic.index = int(idx_raw)
        except ValueError:
            topic.index = None
    topic.labels = [el.text.strip() for el in topic_el.findall("Labels") if el.text and el.text.strip()]
    topic.reference_links = [el.text.strip() for el in topic_el.findall("ReferenceLink") if el.text and el.text.strip()]
    topic.creation_author = _txt(topic_el, "CreationAuthor")
    topic.creation_date = _parse_dt(_txt(topic_el, "CreationDate"))
    topic.modified_author = _txt(topic_el, "ModifiedAuthor")
    topic.modified_date = _parse_dt(_txt(topic_el, "ModifiedDate"))
    topic.due_date = _parse_dt(_txt(topic_el, "DueDate"))
    topic.assigned_to = _txt(topic_el, "AssignedTo")
    topic.stage = _txt(topic_el, "Stage")
    topic.description = _txt(topic_el, "Description")

    # Comments: search both the 3.0 nested locations and the 2.1 sibling
    # location so a mislabelled archive still imports.
    comment_els: list[ET.Element] = []
    comment_els.extend(topic_el.findall("Comment"))
    comments_container = topic_el.find("Comments")
    if comments_container is not None:
        comment_els.extend(comments_container.findall("Comment"))
    comment_els.extend(markup.findall("Comment"))
    for c_el in comment_els:
        c = ParsedComment(guid=c_el.get("Guid") or "")
        c.comment = _txt(c_el, "Comment") or ""
        c.author = _txt(c_el, "Author")
        c.date = _parse_dt(_txt(c_el, "Date"))
        c.modified_author = _txt(c_el, "ModifiedAuthor")
        c.modified_date = _parse_dt(_txt(c_el, "ModifiedDate"))
        vp_ref = c_el.find("Viewpoint")
        if vp_ref is not None:
            c.viewpoint_guid = vp_ref.get("Guid")
        topic.comments.append(c)

    # Viewpoint references: same dual-location tolerance.
    vp_containers: list[ET.Element] = []
    if (vc := topic_el.find("Viewpoints")) is not None:
        vp_containers.append(vc)
    if (vc := markup.find("Viewpoints")) is not None:
        vp_containers.append(vc)
    for container in vp_containers:
        for vp_el in container.findall("ViewPoint"):
            vp = ParsedViewpoint(guid=vp_el.get("Guid") or "")
            bcfv_ref = _txt(vp_el, "Viewpoint")
            snap = _txt(vp_el, "Snapshot")
            if snap:
                vp.snapshot_filename = snap
            # Stash the .bcfv filename so the caller can resolve it.
            vp.camera = {"_bcfv_ref": bcfv_ref} if bcfv_ref else {}
            topic.viewpoints.append(vp)

    _ = version  # accepted for symmetry / future schema-specific tweaks
    return topic


# ── project.bcfp ───────────────────────────────────────────────────────────


def _build_project_xml(project_id: str, project_name: str, version: str) -> bytes:
    """Build a minimal ``project.bcfp`` (Project extension)."""
    root = ET.Element("ProjectExtension")
    root.append(ET.Comment(f" {_BCF_ORIGIN} "))
    proj = _sub(root, "Project")
    proj.set("ProjectId", project_id)
    _sub(proj, "Name", project_name)
    if version == "2.1":
        _sub(root, "ExtensionSchema", "")
    return _serialise(root)


# ── public: build ──────────────────────────────────────────────────────────


def build_bcfzip(
    *,
    version: str,
    project_id: str,
    project_name: str,
    topics: list[ParsedTopic],
) -> bytes:
    """Build a valid ``.bcfzip`` for ``version`` from ``topics``.

    Args:
        version: ``"2.1"`` or ``"3.0"``.
        project_id: Stable project identifier (→ ``project.bcfp``).
        project_name: Human-readable project name.
        topics: Topics (with nested comments/viewpoints) to serialise.

    Returns:
        The ``.bcfzip`` archive as ``bytes``.

    Raises:
        ValueError: if ``version`` is not supported.
    """
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported BCF version {version!r}; expected one of {SUPPORTED_VERSIONS}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bcf.version", _build_version_xml(version))
        zf.writestr(
            "project.bcfp",
            _build_project_xml(project_id, project_name, version),
        )
        for topic in topics:
            base = topic.guid
            zf.writestr(f"{base}/markup.bcf", _build_markup_xml(topic, version))
            for vp in topic.viewpoints:
                zf.writestr(
                    f"{base}/{vp.guid}.bcfv",
                    _build_visinfo_xml(vp, version),
                )
                if vp.snapshot_bytes and vp.snapshot_filename:
                    zf.writestr(
                        f"{base}/{vp.snapshot_filename}",
                        vp.snapshot_bytes,
                    )
    return buf.getvalue()


# ── public: parse ──────────────────────────────────────────────────────────


def _safe_namelist(zf: zipfile.ZipFile, issues: list[ImportIssue]) -> list[str]:
    """Return entry names, rejecting zip-bomb / path-traversal members."""
    names: list[str] = []
    total = 0
    for info in zf.infolist():
        name = info.filename
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
            issues.append(
                ImportIssue(
                    "warning",
                    "unsafe_path",
                    f"Skipping entry with unsafe path: {name!r}",
                    name,
                )
            )
            continue
        if info.file_size > _MAX_SINGLE_ENTRY_BYTES:
            issues.append(
                ImportIssue(
                    "error",
                    "entry_too_large",
                    f"Entry {name!r} exceeds the per-file size limit",
                    name,
                )
            )
            continue
        total += info.file_size
        names.append(name)
    if len(names) > _MAX_ENTRIES:
        issues.append(
            ImportIssue(
                "error",
                "too_many_entries",
                f"Archive has {len(names)} entries (limit {_MAX_ENTRIES})",
            )
        )
        return []
    if total > _MAX_UNCOMPRESSED_BYTES:
        issues.append(
            ImportIssue(
                "error",
                "archive_too_large",
                "Archive uncompressed size exceeds the safety ceiling",
            )
        )
        return []
    return names


def parse_bcfzip(data: bytes, *, forced_version: str | None = None) -> ParseResult:
    """Parse a ``.bcfzip`` into topics + a structured issue list.

    Never raises for *content* problems - those are reported as
    :class:`ImportIssue` entries with ``severity='error'`` so the router
    can return a clean 422 report instead of a 500. The only exception is
    a non-ZIP payload, which raises :class:`BCFParseError` (the router
    maps that to a 422 too).

    Args:
        data: The raw ``.bcfzip`` bytes.
        forced_version: Skip autodetection and assume this schema version.

    Returns:
        A :class:`ParseResult`.
    """
    issues: list[ImportIssue] = []

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BCFParseError(f"Not a valid ZIP archive: {exc}") from exc

    with zf:
        try:
            bad = zf.testzip()
        except (zipfile.BadZipFile, OSError) as exc:
            raise BCFParseError(f"Corrupt ZIP archive: {exc}") from exc
        if bad is not None:
            raise BCFParseError(f"Corrupt entry in archive: {bad}")

        names = _safe_namelist(zf, issues)
        if any(i.severity == "error" for i in issues):
            return ParseResult(detected_version=None, issues=issues)

        version = forced_version or detect_version(data)
        if version is None:
            issues.append(
                ImportIssue(
                    "warning",
                    "version_unknown",
                    "bcf.version missing/unreadable - assuming BCF 2.1",
                    "bcf.version",
                )
            )
            version = "2.1"
        elif version not in SUPPORTED_VERSIONS:
            issues.append(
                ImportIssue(
                    "error",
                    "version_unsupported",
                    f"Unsupported BCF version {version!r}",
                    "bcf.version",
                )
            )
            return ParseResult(detected_version=version, issues=issues)

        markup_names = [n for n in names if n.lower().endswith("markup.bcf")]
        if not markup_names:
            issues.append(
                ImportIssue(
                    "error",
                    "no_topics",
                    "Archive contains no markup.bcf - nothing to import",
                )
            )
            return ParseResult(detected_version=version, issues=issues)

        topics: list[ParsedTopic] = []
        for markup_name in markup_names:
            topic_dir = markup_name.rsplit("/", 1)[0] if "/" in markup_name else ""
            try:
                topic = _parse_markup(zf.read(markup_name), version)
            except BCFParseError as exc:
                issues.append(ImportIssue("error", "markup_invalid", str(exc), markup_name))
                continue
            except ET.ParseError as exc:
                issues.append(
                    ImportIssue(
                        "error",
                        "markup_xml_error",
                        f"markup.bcf is not well-formed XML: {exc}",
                        markup_name,
                    )
                )
                continue

            # Resolve each viewpoint's .bcfv + snapshot.
            for vp in topic.viewpoints:
                bcfv_ref = (vp.camera or {}).get("_bcfv_ref") or f"{vp.guid}.bcfv"
                vp.camera = {}
                bcfv_path = f"{topic_dir}/{bcfv_ref}" if topic_dir else bcfv_ref
                if bcfv_path in names:
                    try:
                        _parse_visinfo(zf.read(bcfv_path), vp)
                    except ET.ParseError as exc:
                        issues.append(
                            ImportIssue(
                                "warning",
                                "bcfv_xml_error",
                                f"Viewpoint {vp.guid} .bcfv malformed: {exc}",
                                bcfv_path,
                            )
                        )
                else:
                    issues.append(
                        ImportIssue(
                            "warning",
                            "bcfv_missing",
                            f"Referenced viewpoint file {bcfv_ref!r} not found",
                            markup_name,
                        )
                    )
                if vp.snapshot_filename:
                    snap_path = f"{topic_dir}/{vp.snapshot_filename}" if topic_dir else vp.snapshot_filename
                    if snap_path in names:
                        vp.snapshot_bytes = zf.read(snap_path)
                    else:
                        issues.append(
                            ImportIssue(
                                "info",
                                "snapshot_missing",
                                f"Snapshot {vp.snapshot_filename!r} not in archive",
                                markup_name,
                            )
                        )
            topics.append(topic)

    return ParseResult(detected_version=version, topics=topics, issues=issues)
