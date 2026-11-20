"""Pydantic mirror of the contract schemas the ERP reads on intake (contract/schemas/*.json).

Kept free of ERP imports so contract/tests can check it against the JSON schemas
(test_mirror.py): every case must be accepted or refused by both alike.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Uuid = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
KEY_PATTERN = r"^[A-Za-z0-9_$][A-Za-z0-9._#/:$-]*$"
Key = Annotated[str, StringConstraints(min_length=1, max_length=255, pattern=KEY_PATTERN)]
_KEY_RE = re.compile(KEY_PATTERN)
IMPORT_KEY_PREFIX = "x/imp/"


def import_key(stable_id: str) -> str:
    """element_key of a converter-imported element (README s1): the stable_id itself when it fits the grammar,
    else ``x/imp/`` + the first 32 hex of SHA-256 over its UTF-8 bytes (same id, same key, in every revision)."""
    import hashlib

    if len(stable_id) <= 255 and _KEY_RE.fullmatch(stable_id):
        return stable_id
    return IMPORT_KEY_PREFIX + hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:32]


ErpUrl = Annotated[
    str,
    StringConstraints(
        pattern=r"^(https://[A-Za-z0-9.-]+(:[0-9]{1,5})?|http://(localhost|127(\.[0-9]{1,3}){3}|\[::1\])(:[0-9]{1,5})?)(/[^?#@\s]*)?$"
    ),
]
IfcClass = Annotated[str, StringConstraints(pattern=r"^Ifc[A-Za-z]+$")]
Qty = Annotated[float | None, Field(ge=0)]

ROLES = ("source", "geometry", "elements", "diff", "sheet", "issues", "ifc", "brief", "thumbnail")
FIXED_PATHS = {
    "source": "model.ddc",
    "geometry": "geometry.glb",
    "elements": "elements.parquet",
    "diff": "diff.json",
    "brief": "brief.json",
    "issues": "issues.bcfzip",
    "ifc": "model.ifc",
}


class _Strict(BaseModel):
    # Optional fields the schema types without null are declared non-optional with default None:
    # an absent field passes, an explicit null is refused, as in the JSON schema.
    model_config = ConfigDict(extra="forbid", strict=True, regex_engine="python-re")


# ── ddc-revision/1 (manifest.json) ──────────────────────────────────────────


class ProjectRef(_Strict):
    erp_project_id: Uuid | None
    erp_url: ErpUrl | None = None
    name: str = Field(default=None, max_length=200)


class Author(_Strict):
    display_name: str = Field(min_length=1, max_length=200)
    erp_user_id: Uuid | None = None


class Generator(_Strict):
    template: str
    version: str
    seed: int = Field(default=None, ge=0)


class Source(_Strict):
    kind: Literal["generated", "edited", "imported"]
    brief_sha256: Sha256 = None
    brief_version: int = Field(default=None, ge=1)
    generator: Generator = None
    imported_from: str = None

    @model_validator(mode="after")
    def _conditional(self) -> Source:
        fields = self.model_fields_set
        if self.kind == "generated" and not {"brief_sha256", "brief_version", "generator"} <= fields:
            raise ValueError("generated source needs brief_sha256, brief_version and generator")
        if self.kind == "imported" and "imported_from" not in fields:
            raise ValueError("imported source needs imported_from")
        return self


class Units(_Strict):
    length: Literal["m"]
    area: Literal["m2"]
    volume: Literal["m3"]
    mass: Literal["kg"]
    angle: Literal["deg"]


class BasePoint(_Strict):
    lat: float | None = Field(ge=-90, le=90)
    lon: float | None = Field(ge=-180, le=180)
    elevation_m: float
    rotation_deg: float = Field(ge=-360, le=360)
    crs: str = None


class Counts(_Strict):
    elements: int = Field(ge=0)
    storeys: int = Field(ge=0)
    types: int = Field(ge=0)
    spaces: int = Field(default=None, ge=0)
    triangles: int = Field(default=None, ge=0)


class Checks(_Strict):
    errors: int = Field(ge=0)
    warnings: int = Field(ge=0)
    issues_file: str = None


class FileEntry(_Strict):
    path: Annotated[
        str, StringConstraints(pattern=r"^(?!.*\.\.)[A-Za-z0-9_-][A-Za-z0-9._-]*(/[A-Za-z0-9_-][A-Za-z0-9._-]*)*$")
    ]
    role: Literal[ROLES]  # type: ignore[valid-type]
    sha256: Sha256
    bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def _fixed_path(self) -> FileEntry:
        fixed = FIXED_PATHS.get(self.role)
        if fixed is not None and self.path != fixed:
            raise ValueError(f"role '{self.role}' must be at '{fixed}'")
        if self.role == "sheet" and not re.match(r"^sheets/[A-Za-z0-9._-]+\.pdf$", self.path):
            raise ValueError("a sheet must be sheets/<name>.pdf")
        return self


class Manifest(_Strict):
    schema_: Literal["ddc-revision/1"] = Field(alias="schema")
    revision_id: Uuid
    project_ref: ProjectRef
    parent_revision_id: Uuid | None
    created_at: datetime
    author: Author
    editor_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$")]
    message: str = Field(default=None, max_length=2000)
    source: Source
    depth_level: Literal["D1", "D2", "D3", "D4", "D5"]
    units: Units
    base_point: BasePoint
    counts: Counts
    locale: Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")] = None
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] = None
    norm_pack: str = None
    checks: Checks = None
    files: list[FileEntry] = Field(min_length=3)

    @model_validator(mode="after")
    def _one_of_each(self) -> Manifest:
        for role in ("geometry", "elements", "source"):
            n = sum(1 for f in self.files if f.role == role)
            if n != 1:
                raise ValueError(f"files must hold exactly one '{role}' entry, found {n}")
        roles = {f.role for f in self.files}
        if self.source.kind == "generated" and "brief" not in roles:
            raise ValueError("a generated revision lists its brief")
        if self.parent_revision_id is not None and "diff" not in roles:
            raise ValueError("a revision with a parent lists its diff")
        return self


# ── ddc-elements/1 (one row of elements.parquet) ────────────────────────────

KEY_COLUMNS = ("id", "stable_id", "element_key")
TEXT_COLUMNS = (
    "element_type",
    "ifc_class",
    "type_key",
    "name",
    "storey",
    "space",
    "discipline",
    "material",
    "phase",
    "geometry_hash",
    "props",
    "space_usage",
)
QTY_COLUMNS = ("length_m", "area_m2", "area_gross_m2", "volume_m3", "volume_gross_m3", "weight_kg")
BBOX_COLUMNS = ("bbox_min_x", "bbox_min_y", "bbox_min_z", "bbox_max_x", "bbox_max_y", "bbox_max_z")
INT_COLUMNS = ("count",)


class ElementRow(_Strict):
    id: Key
    stable_id: Key
    element_key: Key
    element_type: str = Field(min_length=1)
    ifc_class: IfcClass
    type_key: str = Field(min_length=1)
    name: str
    storey: str | None
    space: str | None = None
    discipline: Literal["architecture", "structure", "mep", "site", "other"]
    material: str | None = None
    phase: Literal["new", "existing", "demolished", "temporary"] | None = None
    geometry_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16,64}$")]
    length_m: Qty = None
    area_m2: Qty = None
    area_gross_m2: Qty = None
    volume_m3: Qty = None
    volume_gross_m3: Qty = None
    weight_kg: Qty = None
    count: int | None = Field(default=None, ge=0)
    bbox_min_x: float
    bbox_min_y: float
    bbox_min_z: float
    bbox_max_x: float
    bbox_max_y: float
    bbox_max_z: float
    space_usage: (
        Literal[
            "living", "office", "production", "storage", "education", "care", "other_use", "circulation", "technical"
        ]
        | None
    ) = None
    props: str | None = None


ALL_COLUMNS = tuple(ElementRow.model_fields)
REQUIRED_COLUMNS = tuple(n for n, f in ElementRow.model_fields.items() if f.is_required())


# ── ddc-diff/1 (diff.json) ──────────────────────────────────────────────────

Scalar = str | int | float | bool | None


class FieldChange(_Strict):
    field: str
    old: Scalar
    new: Scalar


class ChangedElement(_Strict):
    element_key: Key
    geometry: bool = None
    fields: list[FieldChange]


class TypeDelta(_Strict):
    type_key: str
    ifc_class: IfcClass
    count_delta: int
    length_m_delta: float = None
    area_m2_delta: float = None
    volume_m3_delta: float = None
    weight_kg_delta: float = None


class Diff(_Strict):
    schema_: Literal["ddc-diff/1"] = Field(alias="schema")
    revision_id: Uuid
    parent_revision_id: Uuid | None
    added: list[Key]
    removed: list[Key]
    changed: list[ChangedElement]
    by_type: list[TypeDelta]

    @model_validator(mode="after")
    def _unique(self) -> Diff:
        for name in ("added", "removed"):
            items = getattr(self, name)
            if len(set(items)) != len(items):
                raise ValueError(f"{name} items must be unique")
        return self
