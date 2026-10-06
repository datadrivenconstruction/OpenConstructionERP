# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The description of a module, as data.

A module the builder produces is rendered from this specification and nothing
else. That is the whole safety argument: an assistant drafting a module writes
a :class:`ModuleSpec`, never Python, so the worst a bad draft can do is
describe a module that fails validation here. Generated code is a pure
function of a spec that passed.

It also means the builder works with no assistant connected at all. The wizard
collects the same structure by hand, and the same generator renders it.

Every identifier is checked against three things rather than one: the shape of
a Python identifier, a keyword list, and the names the generated code uses for
itself. A field called ``id`` or ``metadata`` parses fine and collides with the
row's own primary key or SQLAlchemy's registry, and the failure would arrive as
a stack trace at import time on the user's server.
"""

from __future__ import annotations

import keyword
import re
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# snake_case, starting with a letter. Trailing and doubled underscores are
# allowed by Python but not by us: they read as typos in a column name.
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

MAX_FIELDS = 40

FieldType = Literal[
    "text",
    "long_text",
    "integer",
    "number",
    "money",
    "date",
    "datetime",
    "boolean",
    "select",
    "link",
]

# What a ``link`` field may point at. Each one is a record type another module
# owns; :mod:`app.modules.module_builder.links` says which table, which label,
# which project and which permission, and the generator renders the foreign key
# from it. A closed list on purpose: a link is a foreign key into someone
# else's table, and every target here has been read for how its own module
# decides who may see a row.
LinkTarget = Literal["contract", "contact", "schedule_activity", "document", "user"]

# PostgreSQL silently truncates longer names, and SQLAlchemy refuses an explicit
# index name past it, so a module whose names do not fit cannot be installed.
MAX_IDENTIFIER_BYTES = 63

# The newest spec layout. 1 is everything written before links and features;
# 2 is the wizard that knows them. Both validate.
SCHEMA_VERSION = 2

# Names the generated module already uses on its own row or that SQLAlchemy and
# Pydantic claim. A user field of any of these names would shadow something.
RESERVED_FIELD_NAMES = frozenset(
    {
        "id",
        "project_id",
        "created_at",
        "updated_at",
        "created_by",
        "metadata",
        "metadata_",
        "registry",
        "query",
        "self",
        "class",
        "schema",
        "model_config",
        "model_fields",
    }
)

# Module directory names the platform owns. A generated module taking one of
# these is invisible - the shipped module wins the import - so it is refused at
# the spec rather than discovered later by its author wondering why nothing
# changed. Checked against the live shipped tree in :func:`reserved_module_keys`.
STATIC_RESERVED_KEYS = frozenset({"core", "modules", "app", "tests", "migrations", "admin"})


def reserved_module_keys() -> frozenset[str]:
    """Directory names already taken by a module that ships with the platform."""
    from pathlib import Path

    names = set(STATIC_RESERVED_KEYS)
    try:
        from app.core.module_loader import MODULES_DIR

        shipped = Path(MODULES_DIR)
        if shipped.is_dir():
            names.update(d.name for d in shipped.iterdir() if d.is_dir())
    except Exception:  # pragma: no cover - shipped tree unreadable
        pass
    return frozenset(names)


def url_prefix_for(key: str) -> str:
    """The path a module with this key is served from.

    The loader mounts a router at the hyphenated form of the module's directory
    name, so a key with an underscore is reachable at a URL without one. The
    frontend renders every generated module from this prefix, and the wizard
    shows it before installing, so the rule lives here rather than being
    reassembled from the key at each caller.
    """
    return f"/api/v1/{key.replace('_', '-')}"


def _check_name(value: str, what: str) -> str:
    """A name a person reads: no control characters, which no name needs.

    Quotes, backslashes and every script are fine; the generator escapes them
    where it writes names into code. A tab, a newline or a NUL in a name is
    never meant, and in a label or a spreadsheet cell it breaks the line.
    """
    for char in value:
        if unicodedata.category(char) in ("Cc", "Cs", "Zl", "Zp"):
            raise ValueError(f"{what} {value!r} holds a control character ({ord(char):#06x}); remove it.")
    return value


def _no_lone_surrogates(value: Any, where: str = "the module") -> None:
    """Refuse text that cannot be written to a file at all.

    A lone surrogate arrives through JSON escapes and is a valid Python
    string, but no UTF-8 file can hold it, so the install would fail while
    writing ``spec.json``. Checked on every string, descriptions included.
    """
    if isinstance(value, str):
        if any(unicodedata.category(c) == "Cs" for c in value):
            raise ValueError(f"{where} holds a character that cannot be stored (a lone surrogate).")
    elif isinstance(value, dict):
        for key, item in value.items():
            _no_lone_surrogates(item, f"{where} > {key}")
    elif isinstance(value, list | tuple):
        for item in value:
            _no_lone_surrogates(item, where)


def _check_identifier(value: str, what: str) -> str:
    value = (value or "").strip()
    if not IDENTIFIER_RE.match(value):
        raise ValueError(
            f"{what} must be snake_case: a letter, then letters, digits and single underscores. Got {value!r}."
        )
    if keyword.iskeyword(value) or keyword.issoftkeyword(value):
        raise ValueError(f"{what} {value!r} is a Python keyword.")
    return value


class FieldSpec(BaseModel):
    """One column, one form input, one table cell."""

    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    type: FieldType = "text"
    required: bool = False
    help_text: str = ""
    unit: str = ""
    # select only. Stored as text; the options are what the form offers and
    # what the generated validator accepts.
    options: list[str] = Field(default_factory=list)
    # Shown in the list view. A table of forty columns is not a table, so the
    # generator caps what it renders and this is how a spec says which matter.
    in_list: bool = True
    # link only: the record type the field points at. Absent on every other
    # type, and on every spec written before links existed.
    target: LinkTarget | None = None

    @field_validator("name")
    @classmethod
    def _name_is_a_safe_identifier(cls, value: str) -> str:
        value = _check_identifier(value, "field name")
        if value in RESERVED_FIELD_NAMES:
            raise ValueError(
                f"field name {value!r} is reserved - the generated row already has one, and a second would shadow it."
            )
        return value

    @field_validator("label")
    @classmethod
    def _label_is_present(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("every field needs a label - it is what the user reads.")
        return _check_name(value, "field label")

    @field_validator("unit")
    @classmethod
    def _unit_is_a_name(cls, value: str) -> str:
        return _check_name(value, "unit")

    @field_validator("options")
    @classmethod
    def _options_are_names(cls, value: list[str]) -> list[str]:
        for option in value:
            _check_name(option, "option")
        return value

    @model_validator(mode="after")
    def _select_has_options(self) -> FieldSpec:
        if self.type == "select":
            cleaned = [o.strip() for o in self.options if o and o.strip()]
            if len(cleaned) < 2:
                raise ValueError(
                    f"field {self.name!r} is a select with {len(cleaned)} option(s). "
                    "A choice of one is not a choice; use text, or add options."
                )
            if len(set(cleaned)) != len(cleaned):
                raise ValueError(f"field {self.name!r} repeats an option.")
            object.__setattr__(self, "options", cleaned)
        elif self.options:
            raise ValueError(f"field {self.name!r} is {self.type} but carries select options.")
        if self.type == "link" and self.target is None:
            raise ValueError(f"field {self.name!r} is a link but does not say what it links to.")
        if self.type != "link" and self.target is not None:
            raise ValueError(f"field {self.name!r} is {self.type} but names a link target.")
        return self


RuleKind = Literal["required", "positive", "not_future", "range", "one_of", "order"]


class RuleSpec(BaseModel):
    """A validation rule, in the platform's own sense: part of the workflow.

    Every module ships rules. A module with none is refused, which is the
    platform's rule 4 expressed where it can actually be enforced.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    kind: RuleKind
    field: str
    # range only
    min_value: float | None = None
    max_value: float | None = None
    # order only: this field must not be later than `other_field`
    other_field: str = ""
    severity: Literal["error", "warning"] = "error"

    @field_validator("code")
    @classmethod
    def _code_shape(cls, value: str) -> str:
        value = (value or "").strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9_]{2,48}$", value):
            raise ValueError(f"rule code {value!r} must be UPPER_SNAKE, 3 to 49 characters.")
        return value

    @field_validator("message")
    @classmethod
    def _message_present(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 4:
            raise ValueError("a rule needs a message a person can act on.")
        return value

    @model_validator(mode="after")
    def _kind_has_what_it_needs(self) -> RuleSpec:
        if self.kind == "range":
            if self.min_value is None and self.max_value is None:
                raise ValueError(f"rule {self.code} is a range with no bound.")
            if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
                raise ValueError(f"rule {self.code} has min above max.")
        if self.kind == "order" and not self.other_field:
            raise ValueError(f"rule {self.code} compares an order but names only one field.")
        return self


class EntitySpec(BaseModel):
    """The one record type a generated module manages."""

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    plural_name: str = ""
    fields: Annotated[list[FieldSpec], Field(min_length=1, max_length=MAX_FIELDS)]
    # Whether rows belong to a project. Almost everything in this product does,
    # and the generated router scopes reads and writes by it when true.
    project_scoped: bool = True

    @field_validator("name")
    @classmethod
    def _entity_name(cls, value: str) -> str:
        return _check_identifier(value, "entity name")

    @field_validator("display_name", "plural_name")
    @classmethod
    def _entity_names(cls, value: str) -> str:
        return _check_name(value, "record name")

    @model_validator(mode="after")
    def _fields_are_distinct(self) -> EntitySpec:
        names = [f.name for f in self.fields]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"duplicate field name(s): {', '.join(duplicates)}")
        if not self.plural_name:
            object.__setattr__(self, "plural_name", f"{self.display_name}s")
        return self


# The status column is String(32), so a code longer than that cannot be stored.
STATUS_CODE_MAX = 32


class StateSpec(BaseModel):
    """One stage a record moves through, such as "open" or "approved"."""

    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    # A record in a done state is finished: it is not reminded of its date.
    done: bool = False

    @field_validator("code")
    @classmethod
    def _code_shape(cls, value: str) -> str:
        value = _check_identifier(value, "status code")
        if len(value) > STATUS_CODE_MAX:
            raise ValueError(f"status code {value!r} is longer than {STATUS_CODE_MAX} characters.")
        return value

    @field_validator("label")
    @classmethod
    def _label_present(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("every status needs a label - it is what the user reads.")
        return _check_name(value, "status label")


class StatusFeature(BaseModel):
    """Records move through a short list of states. The first is where they start."""

    model_config = ConfigDict(extra="forbid")

    states: Annotated[list[StateSpec], Field(min_length=2, max_length=8)]

    @model_validator(mode="after")
    def _distinct(self) -> StatusFeature:
        codes = [s.code for s in self.states]
        duplicates = sorted({c for c in codes if codes.count(c) > 1})
        if duplicates:
            raise ValueError(f"duplicate status code(s): {', '.join(duplicates)}")
        return self


class DueFeature(BaseModel):
    """One date field is a deadline: it shows up in the deadline register and is reminded."""

    model_config = ConfigDict(extra="forbid")

    field: str
    remind_days_before: int = Field(default=3, ge=0, le=30)


class FeatureSpec(BaseModel):
    """What a module does besides keeping records. Every part is off by default."""

    model_config = ConfigDict(extra="forbid")

    status: StatusFeature | None = None
    due: DueFeature | None = None
    export: bool = False
    comments: bool = False


FEATURE_NAMES = ("status", "due", "export", "comments")

# The column the status feature adds, and the code of the rule that checks it.
STATUS_COLUMN = "status"
STATUS_RULE_CODE = "STATUS_KNOWN"


class ModuleSpec(BaseModel):
    """Everything the generator needs, and nothing it does not."""

    model_config = ConfigDict(extra="forbid")

    key: str
    display_name: str
    description: str = ""
    category: Literal["community", "integration", "regional"] = "community"
    icon: str = "Boxes"
    version: str = "0.1.0"
    author: str = ""
    entity: EntitySpec
    rules: Annotated[list[RuleSpec], Field(min_length=1, max_length=60)]

    #: Who wrote this specification, as opposed to what the generated module
    #: later does. ``assistant`` means a model drafted it from a sentence;
    #: ``wizard`` means a person filled the form in, which is the default
    #: because a hand-built spec never passes through ``draft_spec``.
    #:
    #: It stays ``assistant`` after a person edits the draft, because that is
    #: what happened: a model wrote the first version and a person changed it.
    #: Clearing it on the first keystroke would report a hand-written spec as
    #: soon as somebody fixed a typo.
    #:
    #: This is a statement about the artefact, not about the module's runtime.
    #: The generated manifest separately declares ``InferenceRole.NONE``, which
    #: remains true: the module the generator emits calls no model.
    drafted_by: Literal["assistant", "wizard"] = "wizard"

    #: Which layout this spec was written in. Absent from every spec.json
    #: written before links and features, which therefore reads as 1.
    schema_version: int = Field(default=1, ge=1, le=SCHEMA_VERSION)

    #: Off unless asked for. A spec without it is exactly the module it always was.
    features: FeatureSpec = Field(default_factory=FeatureSpec)

    @field_validator("key")
    @classmethod
    def _key_shape(cls, value: str) -> str:
        value = _check_identifier(value, "module key")
        if len(value) < 3:
            raise ValueError("module key is too short to be recognisable.")
        return value

    @field_validator("version")
    @classmethod
    def _version_shape(cls, value: str) -> str:
        value = (value or "").strip()
        if not re.match(r"^\d+\.\d+\.\d+$", value):
            raise ValueError(f"version {value!r} must be MAJOR.MINOR.PATCH.")
        return value

    @field_validator("display_name")
    @classmethod
    def _display_name_present(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("a module needs a name a person can read.")
        return _check_name(value, "module name")

    @model_validator(mode="before")
    @classmethod
    def _storable(cls, data: Any) -> Any:
        _no_lone_surrogates(data)
        return data

    @model_validator(mode="after")
    def _coherent(self) -> ModuleSpec:
        taken = reserved_module_keys()
        if self.key in taken:
            raise ValueError(
                f"module key {self.key!r} is already used by a module that ships with the "
                "platform. The shipped one would win and this one would never load."
            )

        known = {f.name: f for f in self.entity.fields}
        for rule in self.rules:
            if rule.field not in known:
                raise ValueError(f"rule {rule.code} names field {rule.field!r}, which does not exist.")
            if rule.kind == "order":
                if rule.other_field not in known:
                    raise ValueError(f"rule {rule.code} compares against {rule.other_field!r}, which does not exist.")
                if rule.other_field == rule.field:
                    raise ValueError(f"rule {rule.code} compares a field with itself.")
                kinds = {known[rule.field].type, known[rule.other_field].type}
                if not kinds <= {"date", "datetime"}:
                    raise ValueError(f"rule {rule.code} orders fields that are not dates.")
            if rule.kind in {"positive", "range"} and known[rule.field].type not in {
                "integer",
                "number",
                "money",
            }:
                raise ValueError(f"rule {rule.code} is numeric but {rule.field!r} is {known[rule.field].type}.")
            if rule.kind == "one_of" and known[rule.field].type != "select":
                raise ValueError(f"rule {rule.code} restricts choices on a field that has none.")
            if rule.kind == "not_future" and known[rule.field].type not in {"date", "datetime"}:
                raise ValueError(f"rule {rule.code} is about time but {rule.field!r} is not a date.")

        codes = [r.code for r in self.rules]
        duplicates = sorted({c for c in codes if codes.count(c) > 1})
        if duplicates:
            raise ValueError(f"duplicate rule code(s): {', '.join(duplicates)}")

        self._features_fit(known)
        self._names_fit()
        return self

    def _features_fit(self, known: dict[str, FieldSpec]) -> None:
        features = self.features
        if features.status is not None:
            # Reserved only while the feature is on: modules built before it
            # may well have a field called status, and they still validate.
            if STATUS_COLUMN in known:
                raise ValueError(
                    "a field is called status and the status feature would add a column of the same "
                    "name. Rename the field or leave the feature off."
                )
            if STATUS_RULE_CODE in {r.code for r in self.rules}:
                raise ValueError(f"rule code {STATUS_RULE_CODE} is used by the status feature.")
        if features.due is not None:
            field = known.get(features.due.field)
            if field is None:
                raise ValueError(f"the deadline is field {features.due.field!r}, which does not exist.")
            if field.type not in {"date", "datetime"}:
                raise ValueError(f"the deadline field {field.name!r} is {field.type}, not a date.")
            if not self.entity.project_scoped:
                raise ValueError("deadlines are reminded per project, so they need records that belong to one.")
        if features.comments and not self.entity.project_scoped:
            raise ValueError("comments are shared within a project, so they need records that belong to one.")

    def _names_fit(self) -> None:
        """Every name the generator gives the database fits PostgreSQL's limit.

        Checked for the names links and the status feature add, and for every
        name once a spec is written in the current layout. Specs written before
        are not held to it, so a module already installed keeps validating.
        """
        names = list(self.new_index_names)
        if self.schema_version >= 2:
            names += [self.table_name, *self.base_index_names]
        for name in names:
            if len(name.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
                raise ValueError(
                    f"the database name {name!r} is longer than {MAX_IDENTIFIER_BYTES} bytes. "
                    "Use a shorter module key, record name or field name."
                )

    @property
    def link_fields(self) -> list[FieldSpec]:
        return [f for f in self.entity.fields if f.type == "link"]

    @property
    def base_index_names(self) -> list[str]:
        """The indexes every generated table has carried since the first generator."""
        names = [f"ix_{self.table_name}_created"]
        if self.entity.project_scoped:
            names.insert(0, f"ix_{self.table_name}_project")
        return names

    @property
    def new_index_names(self) -> list[str]:
        """The indexes links and the status feature add."""
        names = [f"ix_{self.table_name}_{f.name}" for f in self.link_fields]
        if self.features.status is not None:
            names.append(f"ix_{self.table_name}_{STATUS_COLUMN}")
        return names

    @property
    def status_codes(self) -> list[str]:
        status = self.features.status
        return [s.code for s in status.states] if status is not None else []

    @property
    def table_name(self) -> str:
        """The physical table. Prefixed like every other table in the platform."""
        return f"oe_{self.key}_{self.entity.name}"

    @property
    def module_name(self) -> str:
        """The manifest name, in the ``oe_*`` namespace the loader expects."""
        return f"oe_{self.key}"

    @property
    def class_name(self) -> str:
        return "".join(part.title() for part in self.entity.name.split("_"))

    @property
    def url_prefix(self) -> str:
        """Where the loader will mount this module's router."""
        return url_prefix_for(self.key)
