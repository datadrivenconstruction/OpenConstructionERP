# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request-parameter checks and the ``bi_feed`` validation rule set.

Rules (all ERROR; they guard the catalogue, not a person's data):

* ``bi_feed.columns_exist``      R1 every column of every feed exists on its model.
* ``bi_feed.no_sensitive_names`` R2 no column name matches the deny pattern.
* ``bi_feed.money_has_currency`` R3 a feed with a money column has a currency column.
* ``bi_feed.limit_cap``          R4 the page limit never exceeds the cap.
* ``bi_feed.feed_ids``           R5 feed ids are unique and snake_case.
* ``bi_feed.view_parity``        R6 the SQL view of a feed lists the same columns as the feed.

The rules take a plain dict so they run without a session::

    {"specs": {id: FeedSpec}, "feeds": {id: ResolvedFeed}, "view_columns": {id: [names]} | None}
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.bi_feed.feeds import (
    CURRENCY_COLUMNS,
    DENY_COLUMN_RE,
    FEED_ID_RE,
    FEEDS,
    MAX_LIMIT,
    NUMERIC_KINDS,
    FeedDefinitionError,
    FeedSpec,
    resolve,
)

logger = logging.getLogger(__name__)

BI_FEED_RULE_SET = "bi_feed"
ALLOWED_PARAMS = frozenset({"project_id", "updated_since", "limit", "offset", "after"})


class BiFeedError(Exception):
    """A request the feed endpoints refuse; carries the HTTP status and a stable code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FeedParams:
    """Parsed query parameters of a feed request."""

    project_id: uuid.UUID | None = None
    updated_since: datetime | None = None
    limit: int | None = None
    offset: int = 0
    after: uuid.UUID | None = None


def _bad(message: str) -> BiFeedError:
    return BiFeedError(400, "BI_FEED_BAD_PARAM", message)


def _uuid(name: str, value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise _bad(f"{name} must be a UUID") from None


def _integer(name: str, value: str, *, minimum: int) -> int:
    try:
        number = int(value)
    except ValueError:
        raise _bad(f"{name} must be an integer") from None
    if number < minimum:
        raise _bad(f"{name} must be at least {minimum}")
    return number


def parse_params(raw: Mapping[str, str]) -> FeedParams:
    """Validate the query string. Unknown parameters are refused, not ignored."""
    unknown = sorted(set(raw) - ALLOWED_PARAMS)
    if unknown:
        raise _bad(f"unknown parameter: {', '.join(unknown)}")
    limit = None
    if "limit" in raw:
        limit = _integer("limit", raw["limit"], minimum=1)
        if limit > MAX_LIMIT:
            raise BiFeedError(400, "BI_FEED_LIMIT", f"limit cannot exceed {MAX_LIMIT}")
    since = None
    if "updated_since" in raw:
        try:
            since = datetime.fromisoformat(raw["updated_since"].replace("Z", "+00:00"))
        except ValueError:
            raise _bad("updated_since must be an ISO 8601 date or time") from None
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
    return FeedParams(
        project_id=_uuid("project_id", raw["project_id"]) if "project_id" in raw else None,
        updated_since=since,
        limit=limit,
        offset=_integer("offset", raw["offset"], minimum=0) if "offset" in raw else 0,
        after=_uuid("after", raw["after"]) if "after" in raw else None,
    )


# ── Catalogue checks (pure) ─────────────────────────────────────────────────


def unresolvable_columns(specs: Mapping[str, FeedSpec]) -> list[str]:
    """R1: ``feed: reason`` for every feed that does not resolve against its models."""
    problems = []
    for spec in specs.values():
        try:
            resolve(spec)
        except FeedDefinitionError as exc:
            problems.append(str(exc))
    return problems


def sensitive_columns(specs: Mapping[str, FeedSpec]) -> list[str]:
    """R2: ``feed.column`` for every column whose name or source matches the deny pattern."""
    return [
        f"{s.id}.{c.name}"
        for s in specs.values()
        for c in s.columns
        if DENY_COLUMN_RE.search(c.name) or DENY_COLUMN_RE.search(c.attr)
    ]


def money_without_currency(specs: Mapping[str, FeedSpec]) -> list[str]:
    """R3: feeds with a money column and no currency column."""
    return [
        s.id
        for s in specs.values()
        if any(c.kind == "money" for c in s.columns) and not any(c.name in CURRENCY_COLUMNS for c in s.columns)
    ]


def bad_feed_ids(specs: Mapping[str, FeedSpec]) -> list[str]:
    """R5: ids that are not snake_case, keys that differ from the spec id."""
    return [key for key, s in specs.items() if key != s.id or not FEED_ID_RE.match(s.id)]


def view_mismatches(specs: Mapping[str, FeedSpec], view_columns: Mapping[str, list[str]]) -> list[str]:
    """R6: feeds whose SQL view column list differs from the feed's (names and order)."""
    return [s.id for s in specs.values() if s.id in view_columns and view_columns[s.id] != [c.name for c in s.columns]]


# ── Rules ───────────────────────────────────────────────────────────────────


def _payload(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _specs(payload: dict[str, Any]) -> Mapping[str, FeedSpec]:
    return payload.get("specs") or FEEDS


class _CatalogueRule(ValidationRule):
    standard = "bi_feed"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE

    def _result(self, problems: list[str], ok_message: str) -> list[RuleResult]:
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=not problems,
                message=ok_message if not problems else "; ".join(problems),
                details={"problems": problems},
                suggestion=None if not problems else "Fix the feed definition in feeds.py.",
            )
        ]


class ColumnsExistRule(_CatalogueRule):
    rule_id = "bi_feed.columns_exist"
    name = "Feed columns exist on their models"
    description = "Every column of every feed names an attribute that exists on its model."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return self._result(unresolvable_columns(_specs(_payload(context))), "Every feed column exists.")


class NoSensitiveNamesRule(_CatalogueRule):
    rule_id = "bi_feed.no_sensitive_names"
    name = "No sensitive column names in feeds"
    description = "No feed column is named like a hash, token, secret, password, email or API key."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return self._result(sensitive_columns(_specs(_payload(context))), "No sensitive column names.")


class MoneyHasCurrencyRule(_CatalogueRule):
    rule_id = "bi_feed.money_has_currency"
    name = "Money columns come with a currency"
    description = "A feed with money columns also exports a currency column."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return self._result(money_without_currency(_specs(_payload(context))), "Every money feed has a currency.")


class LimitCapRule(_CatalogueRule):
    rule_id = "bi_feed.limit_cap"
    name = "Page limit within the cap"
    description = "The configured page limit does not exceed the cap the endpoints enforce."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        configured = int(_payload(context).get("max_limit", MAX_LIMIT))
        problems = [] if configured <= MAX_LIMIT else [f"max_limit {configured} exceeds {MAX_LIMIT}"]
        return self._result(problems, f"Limit is capped at {MAX_LIMIT}.")


class FeedIdsRule(_CatalogueRule):
    rule_id = "bi_feed.feed_ids"
    name = "Feed ids are unique snake_case"
    description = "Feed ids are unique, snake_case and match their catalogue key."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return self._result(bad_feed_ids(_specs(_payload(context))), "Feed ids are well formed.")


class ViewParityRule(_CatalogueRule):
    rule_id = "bi_feed.view_parity"
    name = "SQL views match the feeds"
    description = "Each SQL view lists the same columns, in the same order, as its file feed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        views = _payload(context).get("view_columns")
        if views is None:
            return self._result([], "SQL views are not enabled.")
        return self._result(view_mismatches(_specs(_payload(context)), views), "Views match the feeds.")


BI_FEED_RULES: tuple[type[ValidationRule], ...] = (
    ColumnsExistRule,
    NoSensitiveNamesRule,
    MoneyHasCurrencyRule,
    LimitCapRule,
    FeedIdsRule,
    ViewParityRule,
)


def register_bi_feed_rules() -> None:
    """Register every rule under the ``bi_feed`` rule set (idempotent: the registry keys on rule id)."""
    for rule_cls in BI_FEED_RULES:
        rule_registry.register(rule_cls(), [BI_FEED_RULE_SET])
    logger.debug("Registered %d bi_feed validation rules", len(BI_FEED_RULES))


__all__ = [
    "ALLOWED_PARAMS",
    "BI_FEED_RULES",
    "BI_FEED_RULE_SET",
    "NUMERIC_KINDS",
    "BiFeedError",
    "FeedParams",
    "parse_params",
    "register_bi_feed_rules",
]
