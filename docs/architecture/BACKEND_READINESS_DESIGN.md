# Backend readiness state — design note

**Status: design only. Nothing described here is implemented, and nothing here
should be implemented from this note alone.** It exists because the first-boot
work measured the problem, fixed everything that could be fixed without changing
when the process starts listening, and stopped at the one part that cannot be
fixed without changing exactly that. The preconditions below are audits of other
people's configuration, and two of them — the desktop launcher and a container
healthcheck — cannot be performed from a sandbox with no browser, no PostgreSQL
and no Rust toolchain. Guessing at them is how a boot that is merely slow becomes
a boot that restart-loops.

## The problem, in numbers

A fresh install takes 90–120 seconds to answer anything on Windows, measured by
the owner. The CI lanes measure the same shape on their runners at the commit this
note was written against: 40.1 s to the first healthy `/api/health` answer on
ubuntu and 77.7 s on windows in the browser lane, and 42 s / 60 s / 103 s for the
CLI lane's boot step across ubuntu / macOS / windows.

| Component | Measured | Source |
| --- | --- | --- |
| Embedded PostgreSQL recovery after a killed run | ~60 s | owner's Windows first-boot measurement |
| Route-table build | 32.1 s quiet, 58.6 s under load, ~37 s on the owner's machine | `warm_route_table` docstring, `backend/app/main.py`; owner's log |
| Inline OpenAPI build, when it is switched on | 52 s to 140 s, quoted as ~141 s | `backend/app/main.py`, cited in `frontend/src/features/auth/LoginPage.tsx` |
| A request served while that build runs **in a thread** | 64.6 s of a 73.0 s build | `backend/app/main.py`, re-measurement quoted below |
| A health check issued alongside the route-table build | answered 33.9 s later | `_heartbeat_through_startup` docstring |

During all of it the port is closed. Not slow — closed: a client cannot connect,
so there is nothing to answer `{"status": "starting"}`, nothing to return a `503`
with a `Retry-After`, and nothing to serve a starting page from.

## Why nothing can answer today

Two independent reasons, and the second one is the one that shapes the design.

**The socket does not exist yet.** uvicorn's `Server.startup()` awaits
`self.lifespan.startup()` and only then creates its listeners — read in uvicorn
0.54.0, inside this project's `uvicorn[standard]>=0.32.0,<1` pin. `main.py`
already relies on this twice and says so both times: `_heartbeat_through_startup`
exists because "uvicorn binds only after this lifespan returns, so for the whole
of startup the only evidence that anything is happening is what this process
writes"; and the inline OpenAPI prime is deliberately not awaited because
"Starlette accepts no requests until this handler returns".

**Even with the port open, a compute-bound phase starves it.** This is not a
prediction, it is a measurement already recorded in `main.py`, and it corrected an
earlier claim that a thread fixes it:

> What the thread does NOT buy is a responsive process, and the line that used to
> stand here said it did: "requests are served throughout, just slower while it
> runs - health answered in 17.1s, 0.7s and 2.2s". Re-measured against a boot
> whose route table was already warm, so the build is the only thing running: the
> first request after the port opened took 64.6s of a 73.0s build, and the two
> after it 2.3s and 2.2s before latency came back to 0.15s.

So a readiness gate served from this process answers during the phases that
*wait* — the embedded cluster booting, migrations, seeding, a vector store
connecting — and is starved during the phases that *compute*: importing ~190
modules and building the route table. That single fact decides what is worth
building, and any design that promises a live health endpoint through the
route-table build is promising something the GIL will not deliver from inside one
process.

The startup handler runs in sections, in this order: `i18n`, `Database`,
`Modules`, `Validation`, `Demo data`, `Vector DB`, `Ready`, `Routing`. Module
routers are mounted inside it, so the route table does not exist until partway
through. And the section named `Ready` is a banner printed *before* the
route-table warm-up in `Routing` — a word this design has to take over, so that
log marker should be renamed in the same change rather than leave two meanings of
"ready" in one boot.

## What "ready" has to mean

Two questions are conflated today, and separating them is most of the design:

- **Liveness** — is this process alive and working towards an answer?
- **Readiness** — may a request be served? Not until the database is up, the
  routers are mounted, the migrations and repairs have run, and the route table is
  warm.

The readiness state is the second. The failure it prevents is not a slow boot; it
is that a slow boot is *indistinguishable from a dead one*, which is what a
watchdog kills and what a user reloads.

## The recommended approach

One process, one port, a gate that answers before routing exists — and an honest
statement of the window in which the gate itself cannot answer.

**1. An outermost pure-ASGI readiness middleware, added in `create_app()` before
any router is mounted.** It consults `app.state` and never the router, so it needs
no route table:

- `/api/health` → `503`, `Retry-After`, and `{"status": "starting"}` plus the
  phase name the boot log is already narrating (`_boot_phase`), and nothing else.
  This endpoint is unauthenticated on purpose and its own docstring forbids text
  describing the deployment's internals — which is why the schema-heal signal it
  carries today is a boolean and not a message.
- `/`, and only `/` → a static starting page: inline, no assets, and no JavaScript
  that polls. A `<meta http-equiv="refresh">` of about 30 s instead.
- `/legal`, `/api/source` and the bundled licence assets → passed through. They
  need no database and no module router, and the AGPL-3.0 section 13 source offer
  should not sit behind a gate that is closed for two minutes.
- everything else → `503` with the same `Retry-After`, no routing attempted. A
  route that is not mounted yet must be refused, not `404`: a `404` during startup
  is a lie about the API, and it is the assertion that proves the gate runs first.

**2. The waiting work moves out of the startup handler into a background worker;
the handler returns almost immediately.** The worker keeps the existing order —
PostgreSQL, modules, migrations and repairs, seeding, vector store, route-table
warm-up — and opens the gate at the end. It runs in a thread, which is enough for
every phase that waits (a thread blocked on a subprocess or a socket releases the
GIL, so the loop keeps serving the gate) and is *not* enough for the compute
phases, per the measurement above. The gate therefore opens in two senses and the
design has to say which is which: `app.state` flips to ready at the end of the
worker, while the process's ability to answer anything at all dips during module
import and the route-table build.

**3. The compute window is shortened or served from outside, not papered over.**
Three honest options, in the order they should be tried:

- *Measure the compute phases before optimising anything.* The route-table build
  is instrumented; the module import is not, beyond a section header. Nobody knows
  today how the 32–58 s splits between importing ~190 modules and warming the
  table, and the answer decides which of the next two is worth doing.
- *Attack the cost.* Lazy module import, a persisted import cache, or a warm-up
  that can be issued in slices with a yield between them would each shrink the
  silent window from inside the process. None of these is verified here; all three
  are real work with their own risk, and none should be assumed to land.
- *Serve the gate from a second process.* The supervisor design rejected below is
  the only thing that keeps health alive through a compute-bound phase, and this
  measurement is what would justify revisiting it. If it is revisited, it is
  revisited for that reason alone.

**4. `Retry-After` is a floor for clients, never a new polling rate.** 5 s during
the waits, 15 s during the compute phases (the existing heartbeat interval,
`_BOOT_HEARTBEAT_SECONDS`). The frontend already has a schedule —
`HEALTH_PROBE_DELAYS_MS`, nine attempts over 165 s, exported from `LoginPage.tsx`
— and it must take the *longer* of the two. A client that obeys a 5 s
`Retry-After` through a 100 s boot asks twenty times, and the browser lane fails a
run that repeats any one URL more than five times.

**5. Staging.** The change is only worth making if the port opens earlier, so it
cannot land as an inert middleware and be finished later.

- *Stage A* — the gate, the `starting` state, and the embedded PostgreSQL boot
  moved into the worker. That is the longest single wait (~60 s of a 90–120 s
  boot), it is a wait rather than a router mutation, and it is the part that can
  move with the least to go wrong. After this the port opens in seconds and the
  gate answers for most of the boot.
- *Stage B* — the remaining sections move into the worker in the existing order,
  and the gate opens after the route-table warm-up. The warm-up stays: it is what
  makes the first *real* request fast, and the gate does not replace it, it only
  stops that request from arriving before it has run.
- *Stage C*, orthogonal and the best value in this note — stop creating the 60 s.
  That component is crash recovery, and it appears when the previous run was
  killed rather than stopped. A clean shutdown of the embedded cluster (checkpoint
  on exit, and a launcher and CLI that stop it rather than orphan it) removes a
  minute from the second and every later boot instead of hiding a minute behind a
  starting page. It can be measured, landed and verified before, after or without
  Stages A and B, and it is the only stage that makes the product faster rather
  than more honest about being slow.

## Rejected alternatives

- **Pre-bind the socket and hand it to uvicorn** (`Server.startup(sockets=[...])`,
  the Gunicorn path). The kernel completes handshakes into the backlog during
  boot, so the port looks open, but nothing reads it: a client connects and gets
  no response, which is a spinner rather than a starting page. Worse, every
  watchdog that uses "can I connect?" as "is it up?" starts answering yes for a
  process that cannot serve — including the desktop shell's decision to attach to
  a running backend rather than start a second one against the same data dir.
- **A second readiness listener on another port.** The frontend, the launcher, the
  container healthchecks and both CI lanes all speak to one port; a second one has
  to be taught to all of them, and in the desktop build the launcher would have to
  proxy it. Two listeners on one data directory also invites the double-backend
  confusion the attach logic exists to prevent.
- **A supervisor process that binds, serves the starting page and proxies to the
  child.** Rejected on cost: a proxy in the request path of every deployment
  including the desktop build, plus socket inheritance on Windows. Section 3 above
  is the one finding that would justify reopening it, and only for the compute
  window.
- **`200` with `{"status": "starting"}` instead of `503`.** Attractive — no
  console errors, no healthcheck restarts — and rejected because every existing
  client reads the status code, not the body: the login page's probe treats
  `!res.ok` as "still booting", both CI lanes wait for a `200`, and the launcher
  polls health to decide whether to attach. A `200` tells all of them the server
  is ready while every real route refuses. And it cannot ship backend-first: the
  service worker serves cached assets, so an old frontend in a browser meets a new
  backend in the wild. `503` keeps every client that exists today truthful, which
  is why the audit below is about start periods rather than about clients.

## Risks and preconditions

Each of these has to be *checked*, in the artefacts and on a machine that can run
them, before Stage A is written. They are listed with the place to look, not with
an assumption about what is there.

1. **Every healthcheck's start period must exceed the worst measured boot.**
   Docker, Railway, Render and the Terraform/STACKIT configs under `deploy/`, plus
   whatever an operator brings. A `503` during boot is correct readiness semantics
   and is exactly what a `start_period` exists to absorb — but a 30 s grace period
   against a 120 s boot is a restart loop, and the loop is worse than the silence
   it replaced. `main.py` already names this failure in passing ("which is how a
   healthcheck timeout turns into a restart loop"). This is the most dangerous
   interaction in the design.
2. **The desktop launcher must not read `503` as "dead".** It polls `/api/health`
   to decide whether a backend is already running against the data directory, with
   a 12 s probe deadline and a four-minute silence limit. `backend/app/cli.py` and
   the launcher's attach path have to be read for what they do with a non-2xx, and
   the launcher cannot be compiled in a sandbox — so this is a change made blind
   or not made.
3. **Whether the heartbeat still ticks during a compute phase.** It is a thread
   writing one log line every 15 s, and it is the launcher's only evidence of life
   while the port is closed. If the GIL starves a request for 64 s it may also
   delay this, and after Stage A the port is open, so a launcher that used to wait
   for log lines may start waiting for HTTP answers that are themselves starved.
   Measure it; do not assume it.
4. **The browser lane's ceilings.** `frontend/e2e/cold-start-first-boot.spec.ts`
   asserts at most 60 requests, at most five repeats of any one URL, and zero
   console errors, page errors and 5xx responses — and a `503` is a 5xx. Today the
   lane sees none, because it waits for the first healthy `200` before navigating
   anywhere (`scripts/ci/browser_cold_start_lane.py`), so no page is loaded while
   the port is closed. That must stay true: the lane must not navigate to the
   starting page, and the starting page must not poll with `fetch` when a human
   reaches it, because Chromium logs a `503` to the console whether or not the
   caller catches it. If the lane is extended to load the starting page — the
   honest way to test it — the 5xx rule needs a named exception for `/api/health`
   before the first ready answer, written as a reason, not as a filter that
   swallows real ones.
5. **Both CI lanes measure time to the first `200`.**
   `scripts/ci/cli_cold_start_probe.py` and `browser_cold_start_lane.py` wait for
   `/api/health` to answer `200`, so after this change they still measure the same
   thing — when the product becomes usable, not when the port opens — and their
   numbers should not move. If they do, something other than the gate changed.
   Their timeouts must still exceed the worst boot.
6. **`_boot_phase` is a module global written from the startup path.** Once that
   path is a thread, the gate reads it from the loop. A string assignment is
   atomic enough for a status line, but the phase and its start timestamp are
   written as two statements and the heartbeat already reads both; they should
   become one immutable value rather than two fields a reader can catch between.
7. **The gate must not become a place where authorization is decided.** It answers
   before authentication exists, so it may serve only the four things named above.
   Everything else stays behind the gate rather than being let through as
   "probably harmless", and the legal floor's pass-through is a named list of
   paths, not a rule about prefixes.
8. **A failed startup stops being a closed port.** Today a fatal startup error
   exits with uvicorn's `STARTUP_FAILURE`, and "the port is open" implies "the
   boot succeeded". After Stage A the process is listening while it boots, so a
   worker that raises has to leave the gate answering `503` with a body that says
   startup failed — forever — rather than opening onto an app with no database
   behind it. This is the case most likely to be forgotten, and the one whose
   absence turns a crash into a hang.

## Test plan

Written before the code, in the lanes that actually run.

**Unit (`backend/tests/unit`; no database, no web framework).** A bare app holding
only the gate, in the shape of
`backend/tests/unit/test_the_branding_settings_reach_the_http_surface.py`: the
smallest setup that still asserts the gate, the shape and the refusal.

- starting → `/api/health` is `503`, carries a plausible integer `Retry-After`
  (never below 1) for every phase, and its body says `starting` and the phase and
  no internal name; `/` is the starting page and its only refresh mechanism is the
  meta tag; `/legal` and `/api/source` pass through; an invented route is `503`
  and not `404`.
- ready → every route behaves exactly as it does today, and the gate adds nothing
  to a normal request's latency or headers. Assert that with a measurement, not a
  comment: the gate is in the path of every request the product will ever serve.
- failed → risk 8, as a test.

**PG lane (`backend/tests/pg`).** The worker's real sequence against a real
embedded cluster: the gate opens only after migrations and repairs have run, and a
request that arrives while they are running is refused rather than served from a
half-migrated schema.

**Frontend (`frontend/src`).** The probe reads the body's `status` as well as the
code, so `503 {"status": "starting"}` and a refused connection both land on
`login-still-starting`, and neither lands on "unable to connect to server" — the
misreading the current wording exists to stop. `Retry-After` is honoured as a
floor and never shortens `HEALTH_PROBE_DELAYS_MS`; a test asserts the attempt
count for a 100 s boot stays inside the ceiling the browser lane enforces.

**Browser lane.** Unchanged and green first: it is the regression test for the
whole change, because it is the only place a real browser meets a real cold boot.
Only then, and as its own commit, one new case — load `/` while starting, assert
the starting page, assert no console error and no page error, assert the page ends
at the sign-in screen once the gate opens.

**Manual, and recorded as manual rather than as a pass.** The launcher's failure
screen and its attach decision against a backend that is starting; a container
healthcheck with a start period shorter than the boot, to watch the restart loop
the audit exists to prevent; a killed run followed by a restart, to measure Stage C
against the ~60 s it is meant to remove; and a request issued *during* the
route-table build after Stage A, to record how long the gate actually takes to
answer when the process is computing — the number this note predicts will be bad
and cannot produce from a sandbox.
