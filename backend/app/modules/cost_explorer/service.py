# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost Explorer business logic.

Orchestrates the four capabilities of the workspace on top of the reverse
index and the cost / catalog tables:

* :meth:`find_by_resources` - rank priced works by the resources they consume.
* :meth:`find_work`         - free-text search over priced works (lexical; the
  hook for a semantic backend is isolated so it can be swapped in later).
* :meth:`compare`           - the same work item priced across every region.
* :meth:`substitute`        - re-price one resource line and see the rate move.
* :meth:`price_intelligence`- where a resource's price sits and what drives it.

Plus :meth:`reindex`, which (re)builds the reverse index from each cost item's
resource composition. Reads are pure lookups; the ranking / pricing maths live
in the stdlib-only engines (:mod:`.ranking`, :mod:`.pricing`).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from decimal import Decimal

from app.modules.cost_explorer import pricing, ranking, search
from app.modules.cost_explorer.repository import CostExplorerRepository
from app.modules.cost_explorer.schemas import (
    ByResourcesMatch,
    ByResourcesRequest,
    ByResourcesResponse,
    CompareRequest,
    CompareResponse,
    CompareRow,
    FindWorkItem,
    FindWorkRequest,
    FindWorkResponse,
    MatchedResourceOut,
    PriceIntelResponse,
    PriceRegionRow,
    PriceStatsOut,
    PriceUsageWork,
    ReindexResponse,
    SubstituteRequest,
    SubstituteResponse,
)

logger = logging.getLogger(__name__)

# Cap the candidate set a by-resources search pulls in for ranking. The reverse
# lookup is indexed and cheap, but the busiest resource sits in tens of
# thousands of works; ranking them all would be wasteful and the tail never
# reaches the top of the result anyway.
_SCAN_CAP = 600
# Rows per bulk insert during a reindex - bounded so one region never builds an
# unbounded parameter list.
_INSERT_CHUNK = 1000
# Above this many cost items the startup auto-build stands down and leaves the
# index to the admin reindex endpoint, so a huge base never slows a cold boot.
_AUTOBUILD_MAX_ITEMS = 40000

# Resolve a display currency from the region for legacy rows that stored an
# empty currency, exactly as the costs read path does.
try:
    from app.modules.costs.schemas import _REGION_CURRENCY_FALLBACK
except Exception:  # pragma: no cover - costs is a hard dependency; be defensive
    _REGION_CURRENCY_FALLBACK = {}


class CostExplorerNotFound(Exception):
    """A referenced work item or resource does not exist."""


def _fmt(value: Decimal) -> str:
    """Format a Decimal as a plain (non-scientific) string."""
    return format(value, "f")


def _resolve_currency(currency: str | None, region: str | None) -> str:
    """Fill an empty currency from the region tag, mirroring the costs module."""
    if currency and currency.strip():
        return currency.strip()
    if region:
        return _REGION_CURRENCY_FALLBACK.get(region.strip().upper(), "")
    return ""


def _description(item: object) -> str:
    """The best available description string for a cost item (may be None)."""
    if item is None:
        return ""
    return str(getattr(item, "description", "") or "")


def parse_components(raw: object) -> list[dict]:
    """Normalise a cost item's ``components`` into clean resource-line dicts.

    ``components`` is stored as a JSON list (occasionally a JSON string) whose
    entries carry ``code`` / ``name`` / ``type`` / ``quantity`` / ``unit_rate``
    (and sometimes ``cost`` or ``total``). Entries without a resource ``code``
    are dropped - they cannot be indexed or matched. The line cost prefers an
    explicit ``cost`` / ``total``, else ``quantity * unit_rate``.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for comp in raw:
        if not isinstance(comp, dict):
            continue
        code = str(comp.get("code") or "").strip()
        if not code:
            continue
        qty = ranking.to_decimal(comp.get("quantity"))
        unit_rate = ranking.to_decimal(comp.get("unit_rate"))
        raw_cost = comp.get("cost")
        if raw_cost in (None, ""):
            raw_cost = comp.get("total")
        cost = ranking.to_decimal(raw_cost) if raw_cost not in (None, "") else qty * unit_rate
        out.append(
            {
                "resource_code": code[:100],
                "resource_name": str(comp.get("name") or "")[:500],
                "resource_type": str(comp.get("type") or "")[:20],
                "unit": str(comp.get("unit") or "")[:20],
                "quantity": _fmt(qty)[:50],
                "unit_rate": _fmt(unit_rate)[:50],
                "cost": _fmt(cost)[:50],
            }
        )
    return out


def _to_uuid(value: str) -> uuid.UUID:
    """Parse a UUID string, raising :class:`CostExplorerNotFound` on garbage."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise CostExplorerNotFound("invalid id") from exc


class CostExplorerService:
    """Business logic for the Cost Explorer workspace."""

    def __init__(self, repo: CostExplorerRepository) -> None:
        self.repo = repo

    # ── 1. By resources ──────────────────────────────────────────────────────

    async def find_by_resources(self, req: ByResourcesRequest) -> ByResourcesResponse:
        """Rank priced works by how well they match a weighted resource set."""
        weights = {r.code.strip(): float(r.weight) for r in req.resources if r.code and r.code.strip()}
        codes = list(weights)
        has_region = req.region is not None
        has_sources = bool(req.sources)
        if not codes:
            hint = search.by_resources_hint(requested_count=0, result_count=0)
            return ByResourcesResponse(
                requested_count=0,
                result_count=0,
                results=[],
                hint=hint.message if hint else None,
                hint_code=hint.code if hint else None,
            )

        ids = await self.repo.candidate_item_ids(req.region, codes, req.sources, _SCAN_CAP)
        if not ids:
            hint = search.by_resources_hint(
                requested_count=len(codes),
                result_count=0,
                has_region=has_region,
                has_sources=has_sources,
            )
            return ByResourcesResponse(
                requested_count=len(codes),
                result_count=0,
                results=[],
                hint=hint.message if hint else None,
                hint_code=hint.code if hint else None,
            )

        edges_by_item = await self.repo.edges_for_items(ids)
        items_by_id = await self.repo.cost_items_by_ids(ids)

        candidates: list[ranking.CandidateItem] = []
        for iid in ids:
            item = items_by_id.get(iid)
            if item is None or getattr(item, "is_active", True) is False:
                continue
            lines = [
                ranking.ResourceLine(
                    resource_code=edge.resource_code,
                    cost=ranking.to_decimal(edge.cost),
                    quantity=ranking.to_decimal(edge.quantity),
                    resource_name=edge.resource_name,
                    resource_type=edge.resource_type,
                )
                for edge in edges_by_item.get(iid, [])
            ]
            candidates.append(
                ranking.CandidateItem(
                    cost_item_id=str(iid),
                    rate_code=item.code,
                    region=item.region,
                    item_total=ranking.to_decimal(item.rate),
                    lines=lines,
                )
            )

        scored = ranking.rank(weights, candidates, limit=req.limit)
        items_by_strid = {str(k): v for k, v in items_by_id.items()}

        results: list[ByResourcesMatch] = []
        for match in scored:
            item = items_by_strid.get(match.cost_item_id)
            if item is None:
                continue
            results.append(
                ByResourcesMatch(
                    cost_item_id=match.cost_item_id,
                    code=item.code,
                    description=_description(item),
                    unit=item.unit,
                    rate=_fmt(ranking.to_decimal(item.rate)),
                    currency=_resolve_currency(item.currency, item.region),
                    region=item.region,
                    source=item.source,
                    classification=item.classification or {},
                    score=match.score,
                    coverage=match.coverage,
                    cost_weight=match.cost_weight,
                    matched=[
                        MatchedResourceOut(
                            code=m.resource_code,
                            name=m.resource_name,
                            cost=_fmt(m.cost),
                            quantity=_fmt(m.quantity),
                        )
                        for m in match.matched
                    ],
                    missing_codes=match.missing_codes,
                )
            )
        hint = search.by_resources_hint(
            requested_count=len(codes),
            result_count=len(results),
            has_region=has_region,
            has_sources=has_sources,
        )
        return ByResourcesResponse(
            requested_count=len(codes),
            result_count=len(results),
            results=results,
            hint=hint.message if hint else None,
            hint_code=hint.code if hint else None,
        )

    # ── 2. Find work (lexical text search) ───────────────────────────────────

    async def find_work(self, req: FindWorkRequest) -> FindWorkResponse:
        """Rank priced works by a free-text query over code and description."""
        has_region = req.region is not None
        has_sources = bool(req.sources)
        tokens = [t for t in re.split(r"\s+", req.q.strip()) if t][:8]
        if not tokens:
            hint = search.text_search_hint(query=req.q, result_count=0)
            return FindWorkResponse(
                query=req.q,
                result_count=0,
                results=[],
                hint=hint.message if hint else None,
                hint_code=hint.code if hint else None,
            )

        # Over-fetch so the lexical re-rank has room to promote the best hits.
        # The repository also runs the domain-lexicon spelling pass and hands
        # back a corrected query (or None) for the did-you-mean chip.
        pool, suggestion = await self.repo.search_work(tokens, req.region, req.sources, min(req.limit * 4, 400))
        # Fold the query for accent- and case-insensitive phrase matching, so a
        # search typed without accents still lands on an accented row (and back).
        query_folded = search.fold(req.q)
        # Expand each token to its multilingual construction-synonym group so a
        # hit on a synonym ("reinforcement" for a typed "rebar", "concrete" for a
        # typed "beton") counts as a real token hit and ranks with the word the
        # user meant, matching the synonym-expanded pool the repository returns.
        token_variants = [search.match_terms(tok) for tok in tokens]

        scored: list[tuple[float, object]] = []
        for item in pool:
            hay = search.fold(f"{item.code} {_description(item)}")
            hits = sum(
                1
                for variants in token_variants
                if any(search.variant_matches(v, hay, whole_word=whole) for v, whole in variants)
            )
            token_share = hits / len(token_variants) if token_variants else 0.0
            phrase = 1.0 if query_folded and query_folded in hay else 0.0
            score = min(1.0, 0.5 * phrase + 0.5 * token_share)
            scored.append((score, item))

        scored.sort(key=lambda pair: (pair[0], -len(_description(pair[1]) or "z" * 999)), reverse=True)
        top = scored[: req.limit]

        results = [
            FindWorkItem(
                cost_item_id=str(item.id),
                code=item.code,
                description=_description(item),
                unit=item.unit,
                rate=_fmt(ranking.to_decimal(item.rate)),
                currency=_resolve_currency(item.currency, item.region),
                region=item.region,
                source=item.source,
                classification=item.classification or {},
                score=round(score, 4),
            )
            for score, item in top
        ]
        top_score = results[0].score if results else 0.0
        # Prefer a construction-aware spelling suggestion ("did you mean
        # concrete?") over the generic guidance when the typed query looks
        # misspelled and the results are weak or empty, since correcting the word
        # is the most useful next step. The corrected query rides in the hint
        # message so the client can re-run it from a one-click chip.
        hint = self._find_work_hint(
            query=req.q,
            suggestion=suggestion,
            result_count=len(results),
            top_score=top_score,
            has_region=has_region,
            has_sources=has_sources,
        )
        return FindWorkResponse(
            query=req.q,
            result_count=len(results),
            mode="lexical",
            results=results,
            hint=hint.message if hint else None,
            hint_code=hint.code if hint else None,
        )

    @staticmethod
    def _find_work_hint(
        *,
        query: str,
        suggestion: str | None,
        result_count: int,
        top_score: float,
        has_region: bool,
        has_sources: bool,
    ) -> search.SearchHint | None:
        """Pick the guidance for a find-work result, spelling suggestion first.

        A domain-lexicon spelling suggestion (``cost_explorer.hint.did_you_mean``)
        wins when the query looks misspelled and the results are weak or empty,
        because correcting the word is the most actionable next step; its message
        carries the corrected query verbatim so the client chip can re-run it on
        one click. When the search already returns strong results the suggestion
        stays silent (no nagging), and otherwise the existing no-result /
        low-confidence guidance applies.
        """
        weak = result_count == 0 or top_score < search.LOW_CONFIDENCE_SCORE
        if suggestion and weak and suggestion.strip().casefold() != query.strip().casefold():
            return search.SearchHint("cost_explorer.hint.did_you_mean", suggestion.strip())
        return search.text_search_hint(
            query=query,
            result_count=result_count,
            top_score=top_score,
            has_region=has_region,
            has_sources=has_sources,
        )

    # ── 3. Compare across price bases ────────────────────────────────────────

    async def compare(self, req: CompareRequest) -> CompareResponse:
        """List the same rate code priced in every installed region."""
        code = req.code
        if not code and req.cost_item_id:
            item = await self.repo.get_item(_to_uuid(req.cost_item_id))
            if item is not None:
                code = item.code
        if not code:
            return CompareResponse(code="", rows=[])

        items = await self.repo.items_by_code(code, req.limit)
        rows = [
            CompareRow(
                cost_item_id=str(item.id),
                code=item.code,
                description=_description(item),
                unit=item.unit,
                rate=_fmt(ranking.to_decimal(item.rate)),
                currency=_resolve_currency(item.currency, item.region),
                region=item.region,
                source=item.source,
            )
            for item in items
        ]
        rows.sort(key=lambda r: r.region or "")
        currencies = sorted({r.currency for r in rows if r.currency})
        return CompareResponse(
            code=code,
            unit=rows[0].unit if rows else "",
            description=rows[0].description if rows else "",
            region_count=len(rows),
            currencies=currencies,
            rows=rows,
        )

    # ── 4. Substitute a resource / re-price a line ───────────────────────────

    async def substitute(self, req: SubstituteRequest) -> SubstituteResponse:
        """Re-price one resource line of a work item via the incremental delta."""
        item = await self.repo.get_item(_to_uuid(req.cost_item_id))
        if item is None:
            raise CostExplorerNotFound("cost item not found")

        target = next(
            (c for c in parse_components(item.components) if c["resource_code"] == req.resource_code),
            None,
        )
        if target is None:
            raise CostExplorerNotFound("resource is not part of this work item")

        quantity = ranking.to_decimal(target["quantity"])
        old_unit_rate = ranking.to_decimal(target["unit_rate"])

        sub_name: str | None = None
        sub_unit: str | None = None
        if req.new_unit_rate is not None:
            new_unit_rate = ranking.to_decimal(req.new_unit_rate)
        else:
            # Prefer the substitute's catalog row in the item's own region. Only
            # fall back to another region when that row is priced in the SAME
            # currency as the work, otherwise a foreign price would be silently
            # blended into the rate and the reported delta would mix currencies.
            item_currency = _resolve_currency(item.currency, item.region)
            sub = await self.repo.catalog_resource(req.substitute_resource_code, item.region)
            if sub is None:
                fallback = await self.repo.catalog_resource(req.substitute_resource_code)
                if fallback is not None and fallback.currency == item_currency:
                    sub = fallback
            if sub is None:
                raise CostExplorerNotFound("substitute resource is not priced in this work's region or currency")
            new_unit_rate = ranking.to_decimal(sub.base_price)
            sub_name = sub.name
            sub_unit = (sub.unit or "").strip() or None

        # A swap re-prices the line but keeps the recipe's quantity for it. If
        # the replacement is priced per a different unit than the line is
        # measured in, that quantity no longer lines up and the new rate can be
        # off by the unit ratio. Flag it (only when both units are known, so an
        # unlabelled recipe never raises a false alarm) so the user re-checks
        # the basis instead of trusting a silently skewed number.
        original_unit = (str(target.get("unit") or "")).strip() or None
        unit_mismatch = bool(sub_unit and original_unit and sub_unit.casefold() != original_unit.casefold())

        result = pricing.substitute(item.rate, quantity, old_unit_rate, new_unit_rate)
        return SubstituteResponse(
            cost_item_id=str(item.id),
            code=item.code,
            description=_description(item),
            unit=item.unit,
            currency=_resolve_currency(item.currency, item.region),
            region=item.region,
            resource_code=req.resource_code,
            resource_name=target["resource_name"],
            quantity=_fmt(quantity),
            old_unit_rate=_fmt(old_unit_rate),
            new_unit_rate=_fmt(new_unit_rate),
            substitute_resource_code=req.substitute_resource_code,
            substitute_resource_name=sub_name,
            original_unit=original_unit,
            substitute_unit=sub_unit,
            unit_mismatch=unit_mismatch,
            old_rate=_fmt(result.old_rate),
            new_rate=_fmt(result.new_rate),
            delta=_fmt(result.delta),
            delta_pct=result.delta_pct,
            clamped=result.clamped,
        )

    # ── 5. Price intelligence for one resource ───────────────────────────────

    async def price_intelligence(self, resource_code: str, region: str | None = None) -> PriceIntelResponse:
        """Summarise a resource's price spread, reach and top consuming works."""
        cat = await self.repo.catalog_resource(resource_code, region) or await self.repo.catalog_resource(resource_code)

        # The price spread must stay within one currency. Scope it to the given
        # region, or to the dominant region (most price rows) when none was
        # asked for, so we never blend price bases in different currencies into
        # one meaningless distribution.
        stats_region = region if region is not None else await self.repo.dominant_region_for_resource(resource_code)
        prices = await self.repo.edge_prices_for_resource(resource_code, stats_region)
        stats = pricing.price_stats(prices)
        stats_currency = _resolve_currency(None, stats_region)
        usage = await self.repo.resource_usage_count(resource_code, region)

        cat_rows = await self.repo.catalog_rows_for_resource(resource_code)
        by_region = [
            PriceRegionRow(
                region=row.region,
                unit=row.unit,
                base_price=row.base_price,
                min_price=row.min_price,
                max_price=row.max_price,
                currency=row.currency,
            )
            for row in cat_rows[:50]
        ]

        top_edges = await self.repo.top_works_for_resource(resource_code, region, 20)
        item_map = await self.repo.cost_items_by_ids([e.cost_item_id for e in top_edges])
        top_works = [
            PriceUsageWork(
                cost_item_id=str(edge.cost_item_id),
                code=edge.rate_code,
                description=_description(item_map.get(edge.cost_item_id)),
                region=edge.region,
                quantity=edge.quantity,
                unit_rate=edge.unit_rate,
            )
            for edge in top_edges
        ]

        return PriceIntelResponse(
            resource_code=resource_code,
            resource_name=cat.name if cat else "",
            resource_type=cat.resource_type if cat else "",
            unit=cat.unit if cat else "",
            stats=PriceStatsOut(
                count=stats.count,
                min=_fmt(stats.min),
                p25=_fmt(stats.p25),
                median=_fmt(stats.median),
                p75=_fmt(stats.p75),
                max=_fmt(stats.max),
                mean=_fmt(stats.mean),
                currency=stats_currency,
            ),
            stats_region=stats_region,
            usage_count=usage,
            by_region=by_region,
            top_works=top_works,
        )

    # ── Reindex ──────────────────────────────────────────────────────────────

    async def reindex(self, region: str | None = None) -> ReindexResponse:
        """(Re)build the reverse index for one region, or all when region is None.

        Each region bucket is wiped and rebuilt in one transaction-visible pass,
        so a rebuild is idempotent and never leaves half-updated edges. Items are
        streamed and edges flushed in bounded batches, so even a large single
        region never materialises its whole item set (with the heavy components
        JSON) in memory at once.
        """
        if region is not None:
            buckets: list[str | None] = [region]
        else:
            buckets = list(await self.repo.distinct_regions())
            if await self.repo.has_null_region_items():
                buckets.append(None)

        items_scanned = 0
        edges_written = 0
        resources_seen: set[str] = set()
        done: list[str] = []

        for bucket in buckets:
            await self.repo.delete_edges_for_region(bucket)
            edge_rows: list[dict] = []
            async for item_id, code, item_region, _source, components in self.repo.stream_items_in_region(bucket):
                items_scanned += 1
                for comp in parse_components(components):
                    edge_rows.append(
                        {
                            "cost_item_id": item_id,
                            "rate_code": (code or "")[:100],
                            "region": item_region,
                            "resource_code": comp["resource_code"],
                            "resource_name": comp["resource_name"],
                            "resource_type": comp["resource_type"],
                            "quantity": comp["quantity"],
                            "unit_rate": comp["unit_rate"],
                            "cost": comp["cost"],
                        }
                    )
                    resources_seen.add(comp["resource_code"])
                if len(edge_rows) >= _INSERT_CHUNK:
                    await self.repo.bulk_insert_edges(edge_rows)
                    edges_written += len(edge_rows)
                    edge_rows = []
            if edge_rows:
                await self.repo.bulk_insert_edges(edge_rows)
                edges_written += len(edge_rows)
            done.append(bucket if bucket is not None else "(none)")

        return ReindexResponse(
            regions=done,
            items_scanned=items_scanned,
            edges_written=edges_written,
            resources_seen=len(resources_seen),
        )

    async def reindex_guarded(self, region: str | None = None) -> ReindexResponse | None:
        """Rebuild under the shared advisory lock; None when another build holds it.

        Every rebuild path (startup, post-import, the admin endpoint) funnels
        through this one transaction-scoped lock so two rebuilds can never
        interleave their per-region delete-then-insert passes and double-insert
        edges. The edge table has no unique key to fall back on (a work may list
        the same resource on more than one component line), so serialising the
        writers is the guard. The caller commits the session, which releases the
        lock; on ``None`` the caller should not commit (nothing was written).
        """
        if not await _try_build_lock(self.repo.session):
            return None
        return await self.reindex(region)

    async def index_status(self) -> dict:
        """Reverse-index health for the status endpoint and the rebuild prompt.

        ``unindexed_regions`` lists regions that carry component-bearing works
        yet have no index edges, so the UI can prompt a rebuild for exactly the
        bases missing from search (not only when the whole index is empty).
        Regions whose works carry no resource breakdown are skipped, so a
        breakdown-less base never shows as permanently stale.
        """
        indexed_edges = await self.repo.count_edges()
        cost_items = await self.repo.count_cost_items()
        unindexed: list[str] = []
        if indexed_edges and cost_items:
            item_regions = set(await self.repo.distinct_regions())
            edge_regions = set(await self.repo.distinct_edge_regions())
            for region in sorted(item_regions - edge_regions):
                if await self._region_has_indexable_work(region):
                    unindexed.append(region)
        return {
            "indexed_edges": indexed_edges,
            "cost_items": cost_items,
            "unindexed_regions": unindexed,
        }

    async def _region_has_indexable_work(self, region: str) -> bool:
        """True when a region has an active work whose components would form edges.

        Scans a bounded prefix of the region's items (a genuinely stale region's
        first item already carries a breakdown), so a region of breakdown-less
        items does not turn the rebuild prompt into a permanent false alarm.
        """
        scanned = 0
        async for _id, _code, _region, _source, components in self.repo.stream_items_in_region(region, batch_size=200):
            if parse_components(components):
                return True
            scanned += 1
            if scanned >= 2000:
                break
        return False

    async def refresh_item(self, item_id: uuid.UUID) -> int:
        """Rebuild the reverse-index edges for one cost item (incremental sync).

        Wipes the item's edges and re-derives them from its current components,
        keeping the index in step with a create / update without a full rebuild.
        A missing or soft-deleted item is left with no edges. Returns the number
        of edges written.
        """
        await self.repo.delete_edges_for_item(item_id)
        item = await self.repo.get_item(item_id)
        if item is None or getattr(item, "is_active", True) is False:
            return 0
        edge_rows = [
            {
                "cost_item_id": item.id,
                "rate_code": (item.code or "")[:100],
                "region": item.region,
                "resource_code": comp["resource_code"],
                "resource_name": comp["resource_name"],
                "resource_type": comp["resource_type"],
                "quantity": comp["quantity"],
                "unit_rate": comp["unit_rate"],
                "cost": comp["cost"],
            }
            for comp in parse_components(item.components)
        ]
        await self.repo.bulk_insert_edges(edge_rows)
        return len(edge_rows)


# Advisory-lock namespace so two instances booting against an empty index do
# not both run a full build (PostgreSQL only; single-process SQLite needs none).
_BUILD_LOCK_KEY = 0x0C05E7E5


async def _try_build_lock(session: object) -> bool:
    """Take a transaction-scoped advisory lock on PostgreSQL; True if acquired.

    Returns True on non-PostgreSQL backends (no cross-process race to guard) and
    is best-effort: any failure to read the dialect or take the lock falls back
    to proceeding, so a lock hiccup never blocks the build.
    """
    try:
        from sqlalchemy import text

        dialect = getattr(getattr(session, "bind", None), "dialect", None)
        if getattr(dialect, "name", "") != "postgresql":
            return True
        got = (await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _BUILD_LOCK_KEY})).scalar()
        return bool(got)
    except Exception:  # pragma: no cover - lock is advisory; proceed on any hiccup
        return True


async def build_index_if_empty() -> None:
    """Build the reverse index on startup when it is empty and small enough.

    No-op when the index already has rows (a rebuild is the admin endpoint's
    job) or when the base is large (the auto-build stands down so a cold boot
    stays fast). Runs in its own session and swallows every error so module
    startup never fails on it.
    """
    from app.database import async_session_factory

    try:
        async with async_session_factory() as session:
            if not await _try_build_lock(session):
                # Another instance is already building the index; let it finish.
                return
            repo = CostExplorerRepository(session)
            if await repo.count_edges() > 0:
                return
            item_count = await repo.count_cost_items()
            if item_count == 0:
                return
            if item_count > _AUTOBUILD_MAX_ITEMS:
                logger.info(
                    "Cost Explorer: %d cost items exceed the auto-build cap; "
                    "run POST /api/v1/cost-explorer/reindex to build the index.",
                    item_count,
                )
                return
            report = await CostExplorerService(repo).reindex()
            await session.commit()
            logger.info(
                "Cost Explorer: built reverse index (%d items -> %d edges, %d resources).",
                report.items_scanned,
                report.edges_written,
                report.resources_seen,
            )
    except Exception:
        logger.warning("Cost Explorer: startup index build skipped after an error.", exc_info=True)
