#!/usr/bin/env python3
"""Refuse a half-migrated collection endpoint.

An endpoint that returns ``{items, total, offset, limit}`` breaks every caller
still expecting a bare array. TypeScript catches most of that, but NOT the
case this guard exists for: React Query caches by key, and the key is a
string. If two files share ``queryKey: ['schedules']`` and only one is
migrated, the cache hands the wrong shape to the other at RUNTIME. ``npm run
build`` is green and the screen is broken.

So the unit of migration is one endpoint plus every consumer of it, in one
commit. This script counts both sides and fails when they disagree.

Usage:
    python scripts/check_page_envelope_consumers.py
    python scripts/check_page_envelope_consumers.py --self-test

Exit codes:
    0  every migrated endpoint has every consumer migrated
    1  at least one endpoint is half migrated
    2  the scan found no consumers at all (broken instrument, not a pass)
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend" / "src"

# Endpoints already migrated to the envelope. Add a line here in the same
# commit that migrates the endpoint, never later.
MIGRATED_ENDPOINTS: dict[str, str] = {
    "/v1/schedule/schedules/": "schedule list",
    "/v1/schedule/schedules/{}/activities/": "schedule activities",
    "/v1/finance/": "finance invoices",
    "/v1/finance/budgets/": "finance budgets",
    "/v1/finance/payments/": "finance payments",
    "/v1/transmittals/": "transmittals list",
    # Wave 2. No trailing slash on purpose: both callers write
    # `/v1/notifications?...`, and `url_shape` cuts at the `?`, so the route
    # this scan sees is the bare path.
    "/v1/notifications": "notifications list",
    # Wave 3. `GET /v1/punchlist/` is the same handler under a root alias and
    # is enveloped too, but no frontend caller uses it - every call goes to
    # `/items/`. Listing it would print "0 call sites, 0 migrated" and pass
    # without reading anything, which is the decorative entry the wave 2 note
    # above bans, so only the route with readers is listed.
    "/v1/punchlist/items/": "punchlist items",
    "/v1/correspondence/": "correspondence list",
    "/v1/inspections/": "inspections list",
    "/v1/daily-diary/diaries/": "daily diary list",
    "/v1/daily-diary/diaries/{}/entries": "daily diary entries",
    "/v1/daily-diary/photos/": "daily diary photos",
    # Wave 4, the documents module. The register is the widest-read list in
    # the product: sixteen call sites, most of them file pickers in other
    # modules rather than the register page itself.
    "/v1/documents/": "documents register",
    "/v1/documents/photos/": "site photos",
    # Timeline used to answer with date groups; grouping moved to the client,
    # because a list of days cannot say how many photos it left out.
    #
    # There is deliberately no "/v1/documents/photos/gallery/" entry here any
    # more. That route returned the same body as this one from a body that was
    # identical line for line, and the helper calling it was never called, so
    # both were retired rather than enveloped twice. An entry naming a route
    # that no longer exists would print "0 call sites, 0 migrated" forever,
    # which is the decorative entry this guard is not allowed to grow.
    "/v1/documents/photos/timeline/": "site photo timeline",
    "/v1/documents/sheets/": "drawing sheets",
    # Two readers at two different limits, 100 in the drawer and 20 in the
    # preview pane. See the shared-key note on "document-activity" below.
    "/v1/documents/{}/activity/": "document activity",
    # Wave 5, the question-and-defect registers: rfi, risk, ncr. All three
    # backends already computed the total and threw it away, and the rfi one
    # had gone further and switched the COUNT off on the grounds that a bare
    # list could not carry it.
    #
    # This entry is thinner than its name suggests and the count below will
    # not say so. The register's own client writes
    # `/v1/rfi/${qs ? `?${qs}` : ''}`, and this scan does not see that line AT
    # ALL: the URL pattern's character class excludes whitespace, so it stops
    # dead at the space before the `?` and no route is extracted. (An earlier
    # version of this note said the shape collapsed to `/v1/rfi/{}` and
    # collided with `getRFI`. Wrong mechanism, same conclusion, and measured:
    # 105 URL literals across 45 files use that suffix idiom and are invisible
    # here. Widening the pattern is a tree-wide change, because the idiom puts
    # a `?` INSIDE the interpolation and `url_shape` splits on `?` before it
    # collapses `${...}`. Worth doing, not worth doing mid-wave.)
    # What this entry sees is the three pickers and widgets that write the
    # route out in full. The register client is covered by the "rfis" cache
    # key below instead, which is where a wrapper caller can be caught.
    "/v1/rfi/": "rfi register",
    "/v1/rfi/{}/activity/": "rfi activity",
    "/v1/risk/": "risk register",
    # Same collapsing idiom as rfi, so this sees only the safety dashboard's
    # rollup. The register client is covered by the "ncrs" key below.
    "/v1/ncr/": "ncr register",
    # Wave 6, the contract-change registers. All seven list routes in the
    # variations module wrote `rows, _ = await <repo>.list_for_project(...)`,
    # discarding a total the repository had already counted over the filtered
    # set. Unlike rfi and ncr these need no cache-key entry: the api layer
    # writes `/v1/variations/notices/?${qs}` and `url_shape` cuts at the `?`,
    # so the register and the single-item read are two distinct shapes. The
    # note at the end of SHARED_QUERY_KEYS explains why reaching for that dict
    # here would not work.
    "/v1/variations/notices/": "variation notices",
    "/v1/variations/variation-requests/": "variation requests",
    "/v1/variations/variation-orders/": "variation orders",
    "/v1/variations/daywork-sheets/": "daywork sheets",
    "/v1/variations/eot-claims/": "eot claims",
    #
    # Two of the seven are enveloped in the router and deliberately absent
    # here: `/v1/variations/site-measurements/` and
    # `/v1/variations/disruption-claims/`. Nothing in the app reads either
    # one, so an entry would report "0 call sites, 0 migrated" and pass
    # without reading anything - the decorative entry this guard refuses to
    # grow. Add them the day a caller appears, not before.
    #
    # Not a register at all: the equipment taxonomy is read whole, by a
    # repository method that takes no offset or limit, so its `total` can
    # never exceed its `items`. It is enveloped and listed anyway so callers
    # do not have to carry a mental list of which routes describe themselves.
    "/v1/equipment/types/": "equipment types",
    # The fleet register, which is a register: the repository counted the yard
    # on every call and the route dropped the number.
    #
    # One call site, and one is the right number. Every reader goes through
    # `listEquipment` in features/equipment/api.ts, so the wrapper's return
    # type is what binds them and tsc enforces the rest. That wrapper had to
    # stop writing its query suffix as `${q ? `?${q}` : ''}` to be seen here at
    # all - see the rfi note above for why. The cache key cannot carry this
    # one: all three readers key ['equipment', 'list', ...], but so does
    # ['equipment', 'detail', id], a single-unit apiGet<Equipment> that carries
    # no envelope, and QUERY_KEY_RE anchors the first element only. Listing
    # "equipment" would report the detail drawer UNMIGRATED forever. Renaming
    # the list key to escape that would be worse than useless: three mutations
    # invalidate the bare prefix ['equipment'], and React Query prefix-matches,
    # so a renamed key stops refreshing the register after create and delete.
    "/v1/equipment/equipment/": "equipment fleet",
    "/v1/resources/resources/": "resources register",
    # The quality module. Five registers the page browses and three child
    # lists it opens underneath them. All five registers cap at 200 in the
    # route signature and the page asks for exactly 200, so every one of them
    # could hand back a full page and say nothing.
    #
    # The three child lists take no offset or limit and are uncapped in the
    # repository, so they report length as total and the notice never draws.
    # They are listed anyway, unlike the decorative entries the notes above
    # ban, because each has a real reader whose type argument this scan
    # checks: the gallery, the NCR drawer and the ITP drawer all decode these
    # bodies by hand and nothing else would catch one drifting back.
    "/v1/qms/itp-plans": "qms itp plans",
    "/v1/qms/itp-plans/{}/items": "qms itp items",
    "/v1/qms/inspections": "qms inspections",
    "/v1/qms/inspections/{}/evidence": "qms inspection evidence",
    "/v1/qms/ncrs": "qms ncr register",
    "/v1/qms/ncrs/{}/actions": "qms ncr actions",
    "/v1/qms/punch-items": "qms punch items",
    "/v1/qms/audits": "qms audits",
    # Wave 7, the commercial spine. Two of the fifteen bare-list routes in the
    # contracts module accept offset and limit, so those two are the only two
    # that truncate today; the other thirteen answer whole and are a separate
    # job. Both repositories already counted the filtered set and both routes
    # wrote `items, _total = ...` and dropped the number.
    #
    # No cache-key entry, and "contracts" specifically MUST NOT be added:
    # QUERY_KEY_RE anchors the first array element only, and this module keys
    # ['contracts', 'list', ...], ['contracts', 'claims', ...] alongside
    # ['contracts', 'lines', ...] and ['contracts', 'claim-history', ...],
    # neither of which is enveloped. The entry would report those UNMIGRATED
    # forever - the daily-diary trap. The change-order picker keys under
    # ['changeorders', ...] and shares nothing.
    #
    # One call site each, and one is the right number: every reader goes
    # through `listContracts` / `listProgressClaims` in features/contracts/
    # api.ts, so the wrapper's return type binds them and tsc enforces the
    # rest. Both wrappers had to stop fetching through a path-taking helper to
    # be seen here at all. `safeGetPage(path)` hid the URL and the type
    # argument in different functions, and this scan binds a URL literal to the
    # call it stands next to, so both entries reported "0 call sites, 0
    # migrated" - the decorative entry the notes above ban. The helper now
    # takes the request instead of the path, which puts `apiGet<Page<Row>>`
    # against the URL and names the row type where it is asked for.
    "/v1/contracts/contracts/": "contracts register",
    "/v1/contracts/progress-claims/": "progress claims",
    # Wave 8, the registers a site reads daily. Ten routes across six modules,
    # ranked by how fast the table behind each one fills against whether a
    # screen actually reads it, and every one of them had a repository that
    # already counted the matching set while the route wrote `items, _ = ...`.
    #
    # The subcontractor directory is the widest-read of them: five callers in
    # five features, and two of those were asking for `limit: 500` against a
    # route capped at `le=200`, so FastAPI answered 422 and the picker on the
    # contracts page and in the timesheet editor was empty rather than short.
    # Both now ask for the ceiling. Its wrapper also had to stop writing the
    # `${q ? `?${q}` : ''}` suffix to be visible here at all - see the rfi and
    # equipment notes above for the mechanism.
    "/v1/subcontractors/subcontractors/": "subcontractor directory",
    # Both supplier registers are read by one page that asks for exactly the
    # route's ceiling of 200 at three call sites, which is the shape the qms
    # note above describes: a full page is the one answer that means "there is
    # more" rather than "that is all". Their api layer interpolated a `qs()`
    # helper that carries its own `?`, so `url_shape` never saw the route; a
    # sibling `query()` helper returning the same string without the leading
    # `?` puts the literal back where this scan can read it.
    "/v1/supplier-catalogs/catalog-items": "supplier catalog items",
    "/v1/supplier-catalogs/vendors": "vendor register",
    # Rows are workers times days, so this fills faster than anything else in
    # the wave. Its api layer built every path from a module-level BASE, which
    # is the idiom the wave-2 note names as invisible here; the list call now
    # writes its route out in full while the rest of the file keeps BASE.
    "/v1/field-time/timesheets/": "field timesheets",
    # Four readers across three features and not one of them sends a limit, so
    # all four took the default page of fifty and presented it as the register.
    # One of those readers, the HSE picker, already decoded the envelope
    # correctly as `Row[] | { items: Row[] }` - an inline union that is right
    # about the shape and that BARE_ARRAY_HINT convicts anyway, because the
    # `[]` inside the type argument matches. It names `Page<Row>` now, which is
    # the only spelling this scan reads as migrated.
    "/v1/safety/incidents/": "safety incident register",
    "/v1/service/tickets/": "service tickets",
    "/v1/service/work-orders/": "service work orders",
    # One reader, the machine drawer, which sends no limit either.
    "/v1/equipment/maintenance-work-orders/": "equipment maintenance orders",
    "/v1/tasks/": "task register",
    "/v1/tasks/my-tasks/": "my tasks",
    #
    # Deliberately absent, and this is the wave's one departure from its own
    # ranking: `/v1/equipment/fuel-logs/`. It is enveloped in the router
    # because a refuel is logged every time a machine is filled and the table
    # outgrows its page within a season, but nothing in the application reads
    # it - no wrapper, no page, no picker. An entry here would report "0 call
    # sites, 0 migrated" and pass without reading anything, which is the
    # decorative entry the notes above ban three times. Add it the day a caller
    # appears. `/v1/variations/site-measurements/` sits in the same position
    # for the same reason.
    #
    # Wave 6. One reader, the procurement api wrapper, and it had to be made
    # visible before this line was worth writing: it built the route with the
    # query string interpolated as one suffix, so the literal collapsed to
    # `.../committed-by-position/{}` and no entry could have matched it. The
    # route now carries its own `?`, which is what `/v1/transmittals/` does and
    # why that one is guarded. Worth knowing before enveloping anything else:
    # an endpoint can be correct, enveloped, read, and still unguardable
    # because of where a caller put a `?`.
    "/v1/procurement/project/{}/committed-by-position/": "committed by BOQ position",
    #
    # Deliberately absent, same rule as fuel-logs above: the funding
    # application's four child registers, `/disbursements/`, `/proofs/`,
    # `/obligations/` and `/allocations/`. All four are enveloped, and the
    # application detail response embeds the four lists whole, so the interface
    # never reads the paged routes - it POSTs to them and reads the detail.
    # Nothing to count, so nothing to list yet.
    #
    # The lines of one subcontractor pay application. This one is read by
    # somebody approving an amount on every line and reading a payable total
    # underneath, so a first page would have them confirm part of a payment
    # on a screen that reads as the whole of it. Its api wrapper follows the
    # pages to the end for that reason, which is a use of the envelope rather
    # than a way round it: without a total there is nothing to say a page was
    # short, and the wrapper would have no way to know it had everything.
    "/v1/subcontractors/payment-applications/{}/lines": "pay application lines",
    # Not paged: every pair on the project comes back and `total` says so. The
    # CVR claim picker went to the same shape at the same time, but its caller
    # builds the URL on a `${BASE}` prefix this scan cannot read, so it is not
    # listed rather than listed at zero call sites.
    "/v1/subcontractors/unlinked-twins/": "subcontract twin pairs",
}

# Left bare on purpose in wave 4: `/v1/documents/photos/recent/`. It is a
# dashboard feed of the twelve newest photos across every project the caller
# can open, hard-capped at 48 by the route signature, and its heading says
# "Latest site photos". A feed that names itself a sample is not claiming to
# be a register, so there is no truncation for the envelope to disclose.

# Wave 2 measured five more enveloped endpoints - file_comments,
# file_distribution, file_references, file_saved_views, file_trash - and
# deliberately lists none of them, because an entry for any of them would
# report "0 call sites, 0 migrated" and pass without reading a thing. Their
# api layers build every URL from a module-level `const BASE = '/v1/file-x'`,
# so the only `/v1/` literal in the file sits on the BASE line, where the
# nearest preceding verb is whatever `api*` the import statement named. The
# same idiom hides their cache keys from the query-key scan below: those are
# written `queryKey: [fileTrashKeys.list, ...]`, a const reference, and
# QUERY_KEY_RE needs a quoted literal. A decorative entry is worse than no
# entry - it reads as coverage.

# React Query cache keys that must move in one commit with the endpoint they
# read. This is a SECOND constraint, not a restatement of the one above.
#
#   * the endpoint's response type binds every caller of the endpoint, and
#     TypeScript enforces that for us,
#   * a shared cache key binds every caller holding that key, and NOTHING
#     enforces that. The key is a string. React Query will hand a value
#     cached by a migrated file straight to an unmigrated one, at runtime,
#     with tsc and the build both green.
#
# So a key listed here is asserted to be wholly migrated the moment its
# endpoint appears in MIGRATED_ENDPOINTS. Keys that merely look related do
# NOT belong here: ['projects-switcher'] and ['projects'] are different
# cache entries and share nothing.
SHARED_QUERY_KEYS: dict[str, str] = {
    # "projects": "/v1/projects/",   # W1, 107 call sites across 81 files
    # Two readers (SchedulePage, ProjectDetailPage) cache Schedule rows under
    # this key. tsc caught SchedulePage consuming the raw Page envelope only
    # because the wrapper's return type happened to flow through; the URL
    # scan above never sees wrapper callers at all.
    "schedules": "/v1/schedule/schedules/",
    # Finance reads the invoice register twice under one prefix: the Insights
    # panel at page level with no direction filter, and the Invoices tab per
    # sub-tab. Different third elements, so different cache entries, but one
    # endpoint and one shape - migrating either alone leaves the other reading
    # an envelope as an array.
    "finance-invoices": "/v1/finance/",
    "finance-budgets": "/v1/finance/budgets/",
    "finance-payments": "/v1/finance/payments/",
    "transmittals": "/v1/transmittals/",
    # Notifications has two readers of one endpoint and no key to list: the
    # bell caches under ['notifications-list'], the inbox page under
    # ['notifications-page', filter, page]. Different first elements, so
    # different cache entries that cannot hand each other a value - the
    # ['projects-switcher'] vs ['projects'] case named above. Listing either
    # would assert a sharing that does not exist.
    #
    # Punchlist reads its list endpoint from three places and none of them
    # share a cache entry: the register under ['punchlist', project, ...4
    # filters], the pin board under ['punchlist-pins', project], the issue
    # hub under ['issues-hub', 'punch', project]. So there is nothing here to
    # assert. "punchlist" specifically MUST NOT be added: QUERY_KEY_RE anchors
    # only the FIRST array element, so it also matches PunchDetailDrawer's
    # ['punchlist', 'item', itemId] - a single-item apiGet<PunchItem> that
    # carries no `Page<`, no `.items` and no `items:`. ENVELOPE_HINT fails on
    # it, the gate reports the drawer UNMIGRATED, and no edit to a correct
    # file can clear it. ['punchlist-kpi'] used to exist and was renamed to
    # ['punchlist-pins'] when the KPI band stopped reading rows.
    #
    # Correspondence has one reader, the register itself. A one-reader key
    # cannot disagree with anything today, but it is the key the next reader
    # of that endpoint will copy, and this is where that reader gets caught.
    "correspondence": "/v1/correspondence/",
    # Inspections has two readers of one endpoint under one first element:
    # the register under ['inspections', project, status, type] and the
    # dashboard quality card under ['inspections', 'dashboard-quality',
    # project]. Different second elements, so different cache entries, but
    # both go through fetchInspections and both had to move together.
    "inspections": "/v1/inspections/",
    # NOT listable, on purpose: "daily-diary". QUERY_KEY_RE anchors only the
    # FIRST array element, and that module namespaces about thirty keys under
    # it - weather, workforce, signatures, completeness, one diary by id.
    # None of those are pages, none carry `Page<`, `.items` or `items:`, so
    # the entry would report every one of them UNMIGRATED and no edit to a
    # correct file could clear it. Its three list endpoints are covered by
    # the URL scan above instead, which does see them.
    #
    # Wave 4. Four surfaces cache the document register under ['documents',
    # <project>, ...]: the register page, the shared file picker, the
    # dashboard upload card and the map placer. Nothing under that first
    # element is a single-document read, so the entry is clearable - which is
    # the check the punchlist note above says to run before listing a key.
    "documents": "/v1/documents/",
    # One reader each, the gallery grid and the timeline. A one-reader key
    # cannot disagree with itself today; it is listed for the same reason
    # "correspondence" is, being the key the next reader will copy.
    "photos": "/v1/documents/photos/",
    "photos-timeline": "/v1/documents/photos/timeline/",
    # The sharpest case in this wave: the file drawer and the preview pane
    # cached one document's history under the identical key while asking the
    # server for different amounts of it, 100 events against 20. React Query
    # handed whichever landed first to both, so the pane could render a page
    # whose `limit` it never requested. Both keys now carry the limit as a
    # third element, so the two are separate cache entries. The first element
    # is unchanged, which is why this listing still matches both call sites:
    # QUERY_KEY_RE anchors the first element only. Putting a page size in the
    # URL and not in the key is the general form of that bug - if you add a
    # second reader of a paged endpoint at a different limit, key the limit.
    "document-activity": "/v1/documents/{}/activity/",
    # Wave 5. These four carry the weight the URL scan cannot: rfi and ncr
    # both build their register URL with an interpolated query suffix, so the
    # route the scan sees is `{}` rather than the collection, and the only
    # readers it would otherwise judge are pickers in other modules.
    #
    # Clearable, which is the check the punchlist note above says to run
    # first. Nothing under ['rfis'] or ['ncrs'] is a single-item read - those
    # live under ['rfi', id] and there is no ['ncrs', id] - and the neighbours
    # that look related are separate cache entries: ['rfi', 'stats'],
    # ['rfi-stats'], ['ncrs-summary'], ['risk', id], ['risk-summary'],
    # ['risk-matrix']. QUERY_KEY_RE anchors the closing quote, so 'ncrs' does
    # not match 'ncrs-summary'.
    "rfis": "/v1/rfi/",
    "rfi-activity": "/v1/rfi/{}/activity/",
    "risks": "/v1/risk/",
    "ncrs": "/v1/ncr/",
    # NOT listable, on purpose: "variations". Reach for this dict when you
    # migrate that module and it will look like the obvious move, because all
    # five of its register queries are keyed ['variations', <thing>, ...]. It
    # is the "daily-diary" trap above wearing different clothes: the same
    # first element also covers ['variations', 'projects'] and ['variations',
    # 'dashboard', <project>], which are not pages and never will be, so the
    # entry would report them UNMIGRATED forever.
    #
    # It is also unnecessary there. The URL scan already covers that module
    # cleanly, which is what makes variations unlike rfi and ncr above:
    # url_shape() cuts at the `?`, so the register reads as
    # `/v1/variations/notices/` and the single-item read as
    # `/v1/variations/notices/{}`. Two different shapes, no collision, so the
    # list endpoint can be named in MIGRATED_ENDPOINTS on its own.
}

QUERY_KEY_RE = r"queryKey:\s*\[\s*['\"`]{key}['\"`]"

# The calls that read a collection, and the calls that do not. `apiGet` is
# the shared client; the rest are wrappers around it that a feature wrote for
# itself, and every one of them has to be named here or its callers are not
# scanned at all - not counted, not judged, silently absent from the report.
#
# The bar for adding a wrapper is exact: the URL literal and the type argument
# must both appear AT THE CALL SITE. That is what lets the scan bind them to
# each other, and it is why `useGracefulQuery` qualifies. A helper written as
# `fetchRows(path)` does not, however convenient it looks: it holds the type
# argument in its own body, several hundred characters away in another
# function, so naming it here would count its callers while inspecting none of
# them. That is the decorative entry the notes above refuse, and it reads as
# coverage. The fix for that shape is at the caller - hand the helper the
# request instead of the path, so each caller names its own row type.
READ_CALLS: tuple[str, ...] = ("apiGet", "useGracefulQuery")
WRITE_CALLS: tuple[str, ...] = ("apiPost", "apiPatch", "apiPut", "apiDelete")
# Longest first, so a name that is a prefix of another cannot shadow it.
CALL_RE = re.compile("|".join(re.escape(n) for n in sorted((*READ_CALLS, *WRITE_CALLS), key=len, reverse=True)))

# A call is migrated when it names the envelope type. A call that still
# names a bare array of the row type is not, and neither is one hedging
# between the two: `apiGet<Row[] | {items: Row[]}>` unwraps whichever shape
# turns up and throws `total` away, which is the state this whole programme
# exists to leave behind. So the bare hint reads the type argument up to its
# first `>` and asks whether an array is in there at all - `Page<Row>` and
# `Pick<Page<Row>, 'items' | 'total'>` carry none, the union carries two.
#
# The bare hint is built from READ_CALLS rather than written out, because a
# hint that knows fewer calls than the binder above is worse than no hint: the
# call gets counted as a consumer and then judged on the envelope hint alone,
# and `.items` belonging to some neighbouring line inside the window is enough
# to acquit a caller that reads a bare array.
ENVELOPE_HINT = re.compile(r"Page<|\.items\b|items:\s")
BARE_ARRAY_HINT = re.compile(r"(?:" + "|".join(re.escape(n) for n in READ_CALLS) + r")<[^>]*\[\]")


def url_shape(url: str) -> str:
    """Reduce a URL to its route, with every interpolation collapsed."""
    url = url.split("?")[0]
    url = re.sub(r"\$\{[^}]*\}", "{}", url)
    return re.sub(r"/+", "/", url)


def scan(root: Path) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    """Return (consumers, unmigrated) keyed by migrated endpoint route."""
    consumers: dict[str, list[Path]] = {k: [] for k in MIGRATED_ENDPOINTS}
    unmigrated: dict[str, list[Path]] = {k: [] for k in MIGRATED_ENDPOINTS}

    for path in root.rglob("*.ts*"):
        if "node_modules" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(r"[`'\"]((?:/api)?/v1/[^`'\"\s]*)[`'\"]", text):
            raw = m.group(1)
            shape = url_shape(raw).removeprefix("/api")
            if shape not in MIGRATED_ENDPOINTS:
                continue
            # Doc comments quote these routes constantly. A comment is not a
            # consumer, and counting one produces a failure nobody can fix.
            line_start = text.rfind("\n", 0, m.start()) + 1
            if text[line_start : m.start()].lstrip().startswith(("*", "//", "/*")):
                continue
            # Only a GET reads the collection. The same route is also a POST
            # target (create) and a DELETE target (clear); neither returns a
            # page, so neither can be half migrated.
            #
            # Bind to the NEAREST preceding call, not to any call in a window:
            # these api objects list one route per line, so a window wide
            # enough to hold the call is wide enough to hold its neighbour's.
            before = text[max(0, m.start() - 400) : m.start()]
            calls = CALL_RE.findall(before)
            if not calls or calls[-1] not in READ_CALLS:
                continue
            consumers[shape].append(path)
            # Judge the call this URL belongs to, not the neighbourhood it
            # sits in. A window wide enough to hold the call is wide enough
            # to hold the previous one's type argument, and link pickers come
            # in runs: documents, transmittals, RFIs, one useQuery after
            # another. The documents route is bare and the transmittals route
            # is not, so a windowed read convicts the migrated call of its
            # neighbour's shape and no edit to the file can clear it.
            # The tail stops at the next call for the same reason the head
            # starts at this one. Both windows used to borrow from the
            # neighbour; only the head was ever narrowed, and the tail can go
            # wrong in both directions. It can convict a migrated call of the
            # bare array belonging to the call underneath it, and it can
            # acquit an untyped `apiGet(url)` on an `.items` that is the next
            # call's unwrapping. 200 characters is three or four lines, which
            # is well inside the next entry of any api object in this tree.
            tail = text[m.start() : m.start() + 200]
            following = CALL_RE.search(tail)
            if following:
                tail = tail[: following.start()]
            call = before[before.rfind(calls[-1]) :] + tail
            if BARE_ARRAY_HINT.search(call) or not ENVELOPE_HINT.search(call):
                unmigrated[shape].append(path)
    return consumers, unmigrated


def scan_query_keys(root: Path) -> dict[str, tuple[list[Path], list[Path]]]:
    """Return {key: (reading call sites, unmigrated call sites)}.

    Only reads count. ``invalidateQueries({queryKey: ['projects']})`` names
    the key without consuming the value, so it cannot be handed the wrong
    shape and must not be counted; a ``queryFn`` in the window is what
    separates the two. Requiring ``apiGet`` instead would miss readers that
    fetch through an api wrapper (``scheduleApi.listSchedules(...)``), and a
    wrapper caller was exactly the consumer tsc caught unmigrated while this
    scan reported the key clean.
    """
    out: dict[str, tuple[list[Path], list[Path]]] = {k: ([], []) for k in SHARED_QUERY_KEYS}
    if not SHARED_QUERY_KEYS:
        return out
    patterns = {k: re.compile(QUERY_KEY_RE.format(key=re.escape(k))) for k in SHARED_QUERY_KEYS}

    for path in root.rglob("*.ts*"):
        if "node_modules" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for key, pat in patterns.items():
            for m in pat.finditer(text):
                # The queryFn follows the key, so look forward from it - but
                # only as far as the next key. A second `queryKey:` starts a
                # second call object, and a queryFn past it belongs to that
                # one. Without the cut, an `invalidateQueries` that happens to
                # sit within 600 characters of the next `useQuery` borrows its
                # fetcher, counts as a read, and is then judged against a type
                # argument that is not its own: ProcurementPage invalidates
                # ['finance-invoices'] in a mutation and the next query up the
                # file reads a different endpoint entirely. No edit to that
                # file could clear the failure, because the file is right.
                window = text[m.start() : m.start() + 600]
                nxt = re.search(r"queryKey:\s*\[", window[1:])
                if nxt:
                    window = window[: nxt.start() + 1]
                if "queryFn" not in window:
                    continue
                reads, bad = out[key]
                reads.append(path)
                if BARE_ARRAY_HINT.search(window) or not ENVELOPE_HINT.search(window):
                    bad.append(path)
    return out


def report(root: Path) -> int:
    consumers, unmigrated = scan(root)
    total_consumers = sum(len(v) for v in consumers.values())
    if total_consumers == 0:
        print("FAIL: found no consumers of any migrated endpoint.")
        print("      A zero here means the scan is broken, not that the tree is clean.")
        return 2

    failed = False
    for route, label in MIGRATED_ENDPOINTS.items():
        seen = consumers[route]
        bad = unmigrated[route]
        print(f"{label}: {len(seen)} call sites, {len(seen) - len(bad)} migrated")
        for p in sorted(set(bad)):
            print(f"  UNMIGRATED  {p.relative_to(REPO)}")
            failed = True
    # One tree walk for every key, not one walk per key: this used to sit
    # inside the loop, so each key added to the dict above cost another full
    # pass over frontend/src and the guard grew slower every wave.
    by_key = scan_query_keys(root)
    for key, endpoint in SHARED_QUERY_KEYS.items():
        if endpoint not in MIGRATED_ENDPOINTS:
            continue
        reads, bad = by_key[key]
        print(f"queryKey ['{key}']: {len(reads)} reading call sites, {len(reads) - len(bad)} migrated")
        for p in sorted(set(bad)):
            print(f"  UNMIGRATED  {p.relative_to(REPO)}")
            failed = True

    if failed:
        print()
        print("FAIL: an endpoint returns the envelope but some callers still read a bare array.")
        print("      Migrate every consumer in this commit. A shared React Query key means")
        print("      a partial migration breaks at runtime and the build cannot see it.")
        return 1
    print("\nOK: every migrated endpoint has every consumer migrated.")
    return 0


def self_test() -> int:
    """Prove the guard can refuse.

    A guard nobody has watched fail is indistinguishable from one whose
    argument is ignored, so this plants a consumer that reads a bare array
    and asserts the scan rejects it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp)
        (fake / "Good.tsx").write_text(
            "const page = await apiGet<Page<Row>>(`/v1/schedule/schedules/?project_id=${id}`);\nreturn page.items;\n",
            encoding="utf-8",
        )
        consumers, unmigrated = scan(fake)
        if len(consumers["/v1/schedule/schedules/"]) != 1 or unmigrated["/v1/schedule/schedules/"]:
            print("SELF-TEST FAIL: a correctly migrated consumer was not accepted.")
            return 1

        (fake / "Bad.tsx").write_text(
            "const rows = await apiGet<ScheduleRow[]>(`/v1/schedule/schedules/?project_id=${id}`);\nreturn rows;\n",
            encoding="utf-8",
        )
        consumers, unmigrated = scan(fake)
        if len(unmigrated["/v1/schedule/schedules/"]) != 1:
            print("SELF-TEST FAIL: the guard accepted a consumer still reading a bare array.")
            print("                It cannot refuse, so a green run from it means nothing.")
            return 1

        # The narrowings have to be proven too, or a later tightening could
        # silence the refusal above without anyone noticing.
        (fake / "Bad.tsx").unlink()
        # The read sits a few lines above the writers, exactly as it does in
        # the real feature api objects. A window-based check passes this file
        # by borrowing the neighbouring apiGet, so it has to be in the fixture.
        (fake / "Writer.tsx").write_text(
            "export const api = {\n"
            "  getGantt: (id) => apiGet<GanttData>(`/v1/schedule/schedules/${id}/gantt/`),\n"
            "  createActivity: (id, body) =>\n"
            "    apiPost<Activity>(`/v1/schedule/schedules/${id}/activities/`, body),\n"
            "  clearActivities: (id) =>\n"
            "    apiDelete<Cleared>(`/v1/schedule/schedules/${id}/activities/`),\n"
            "};\n",
            encoding="utf-8",
        )
        (fake / "Doc.tsx").write_text(
            "/** See `/v1/schedule/schedules/?project_id=...` for the shape. */\n",
            encoding="utf-8",
        )
        consumers, unmigrated = scan(fake)
        if unmigrated["/v1/schedule/schedules/{}/activities/"]:
            print("SELF-TEST FAIL: a POST/DELETE on the route was counted as a truncated read.")
            return 1
        if len(consumers["/v1/schedule/schedules/"]) != 1:
            print("SELF-TEST FAIL: a doc comment quoting the route was counted as a consumer.")
            return 1

        # A migrated call standing next to a bare read of some OTHER route.
        # Link pickers are written this way everywhere, and the neighbour's
        # route may have no envelope to migrate to, so convicting on it is a
        # failure the file cannot be edited out of.
        for f in fake.glob("*.tsx"):
            f.unlink()
        (fake / "Pickers.tsx").write_text(
            "const docs = useQuery({\n"
            "  queryFn: () => apiGet<PickerDocument[]>(`/v1/documents/?project_id=${id}`),\n"
            "});\n"
            "const schedules = useQuery({\n"
            "  queryFn: () => apiGet<Page<ScheduleRow>>(`/v1/schedule/schedules/?project_id=${id}`),\n"
            "});\n",
            encoding="utf-8",
        )
        consumers, unmigrated = scan(fake)
        if unmigrated["/v1/schedule/schedules/"]:
            print("SELF-TEST FAIL: a migrated call was convicted of its neighbour's bare array.")
            print("                Nothing in the file can clear that, so the guard blocks a")
            print("                correct migration instead of an incorrect one.")
            return 1

        # The union that reads either shape is what the migration replaces, so
        # the guard has to refuse it. It is the easiest thing to mistake for
        # migrated: it does mention `items`.
        (fake / "Pickers.tsx").unlink()
        (fake / "Hedge.tsx").write_text(
            "const rows = await apiGet<ScheduleRow[] | { items: ScheduleRow[] }>(\n"
            "  `/v1/schedule/schedules/?project_id=${id}`,\n"
            ");\n",
            encoding="utf-8",
        )
        consumers, unmigrated = scan(fake)
        if len(unmigrated["/v1/schedule/schedules/"]) != 1:
            print("SELF-TEST FAIL: the guard accepted a caller hedging between array and envelope.")
            print("                That caller still throws `total` away.")
            return 1
        (fake / "Hedge.tsx").unlink()

        # A feature that reads through its own wrapper rather than calling
        # apiGet directly. Both callers below have to be visible, and the
        # second one has to be refused.
        #
        # The second fixture is written the way the real one was, with the
        # rows unwrapped on the line after the call, and that detail is the
        # point of it. The envelope hint reads a window, `.items` on the next
        # line lands inside that window, and so a hint set that knows only
        # `apiGet` would count this caller and then acquit it on a `.items`
        # that belongs to the unwrapping rather than to the type argument. It
        # can only be convicted by a bare-array hint that knows the wrapper,
        # which is why BARE_ARRAY_HINT is built from READ_CALLS.
        (fake / "Wrapper.tsx").write_text(
            "const good = useGracefulQuery<Page<ScheduleRow>>(\n"
            "  ['a', id],\n"
            "  `/v1/schedule/schedules/${id}/activities/`,\n"
            ");\n"
            "const bad = useGracefulQuery<ScheduleRow[]>(\n"
            "  ['b', id],\n"
            "  `/v1/schedule/schedules/?project_id=${id}`,\n"
            ");\n"
            "const rows = bad.data?.items ?? [];\n",
            encoding="utf-8",
        )
        consumers, unmigrated = scan(fake)
        if len(consumers["/v1/schedule/schedules/{}/activities/"]) != 1:
            print("SELF-TEST FAIL: a read through a named wrapper was not counted at all.")
            print("                Such callers are invisible rather than green, so the")
            print("                per-endpoint totals understate what was inspected.")
            return 1
        if unmigrated["/v1/schedule/schedules/{}/activities/"]:
            print("SELF-TEST FAIL: a wrapper call naming the envelope type was refused.")
            return 1
        if len(unmigrated["/v1/schedule/schedules/"]) != 1:
            print("SELF-TEST FAIL: a wrapper call reading a bare array was accepted.")
            print("                It unwraps `.items` on the next line, so the envelope")
            print("                hint acquits it and only the bare hint can refuse.")
            return 1
        (fake / "Wrapper.tsx").unlink()

        # The cache-key half has to be proven too, and it cannot be proven from
        # the real tree while SHARED_QUERY_KEYS is empty: an empty dict makes
        # the check vacuously pass, which is the shape this whole script exists
        # to reject. So declare a key just for the fixture.
        global SHARED_QUERY_KEYS
        saved = SHARED_QUERY_KEYS
        try:
            SHARED_QUERY_KEYS = {"widgets": "/v1/widgets/"}
            for f in fake.glob("*.tsx"):
                f.unlink()
            (fake / "Reader.tsx").write_text(
                "useQuery({\n"
                "  queryKey: ['widgets'],\n"
                "  queryFn: () => apiGet<Page<Widget>>('/v1/widgets/').then((p) => p.items),\n"
                "});\n",
                encoding="utf-8",
            )
            (fake / "Stale.tsx").write_text(
                "useQuery({\n  queryKey: ['widgets'],\n  queryFn: () => apiGet<Widget[]>('/v1/widgets/'),\n});\n",
                encoding="utf-8",
            )
            # Naming a key to invalidate it never reads the value, so it can
            # never be handed the wrong shape and must not be counted.
            (fake / "Invalidate.tsx").write_text(
                "qc.invalidateQueries({ queryKey: ['widgets'] });\n",
                encoding="utf-8",
            )
            reads, bad = scan_query_keys(fake)["widgets"]
            if len(reads) != 2:
                print(f"SELF-TEST FAIL: expected 2 reading call sites on the key, saw {len(reads)}.")
                print("                An invalidateQueries call was probably miscounted as a read.")
                return 1
            if [p.name for p in bad] != ["Stale.tsx"]:
                print("SELF-TEST FAIL: the cache-key check did not single out the unmigrated reader.")
                print("                It cannot refuse, so it cannot guard the runtime failure.")
                return 1
        finally:
            SHARED_QUERY_KEYS = saved

    print("SELF-TEST OK: accepts a migrated consumer, refuses an unmigrated one,")
    print("              ignores writers and doc comments on the same route, and")
    print("              refuses a shared cache key whose readers disagree.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true", help="prove the guard can fail, then exit")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    # The self test runs before every real scan, not only on demand. The
    # matching here is narrow enough that a later tightening could stop it
    # seeing anything at all, and a guard that cannot refuse reports the same
    # clean run as a tree with nothing wrong in it. Costs one temp directory.
    if self_test() != 0:
        print("FAIL: the guard could not prove it still refuses, so its verdict means nothing.")
        return 2
    print()
    return report(FRONTEND)


if __name__ == "__main__":
    sys.exit(main())
