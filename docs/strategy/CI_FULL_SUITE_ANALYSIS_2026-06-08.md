# Full test suite analysis - 2026-06-08

Context: the backend test suite was split so pushes gate on the unit tree
only (ci.yml, 120 minutes) and the whole tree runs nightly (ci-full.yml,
360 minutes). This note records what the nightly run actually does today
and what to change next.

## Headline

The one nightly run on record (workflow_dispatch, run 27091496927) ran for
6h0m15s and was cancelled when it hit the 360 minute job cap. pytest was
still going when the runner tore the job down (it shows up as a terminated
orphan process in the teardown log). So the full suite does not finish in
six hours, and there is no clean pass or fail to read. Every "result" from
it so far is a partial run.

## Why it runs so long

The suite runs serially. pytest-xdist is installed but disabled on purpose
(`addopts = []`), because the whole tree shares one PostgreSQL database that
conftest sets up at import time and bootstraps the first registered user as
the admin every later test relies on. Under xdist each worker inherits the
same DATABASE_URL, so parallel workers race on create_all DDL and the
admin-bootstrap ordering stops being deterministic. Serial is correct until
each worker gets its own database.

Serial plus a real Postgres plus the full integration tree is inherently
slow, and two things make it worse:

- Negative tests deliberately trip constraints (foreign key violations on
  `oe_match_elements_search_log`, duplicate `idempotency_key` on
  `oe_job_run`, and so on). Postgres logs every one of those at ERROR, so
  six hours of expected failures flood the job log and bury any real
  signal. One checkpoint in the captured tail took 269 seconds, which
  points at heavy I/O on the shared database late in the run.
- The live-infra tests run too. Recall and rerank tests need a live Qdrant
  plus the BGE-M3 encoder, and the dashboard tests need the pandas/analytics
  extras. When the infra or extras are absent these either error out or sit
  waiting, neither of which the plain `pytest -q` invocation could time-box.

## The failing-tests artifact is stale

`artifact_failed_tests.txt` (captured 2026-06-07 10:29, about 60 tests) is a
snapshot from before the most recent fix wave, not a current failure list.
Spot checks against the current tree:

- Already green after `c38dd3e72` (align tests with shipped behavior) and
  `97c6f7a34` (serialize money fields as decimal strings):
  `test_i18n::test_21_locales_defined`, `test_cost_schemas::test_rate_is_decimal`,
  `test_formatters_units::test_skips_when_no_unit_system_supplied`,
  `test_translation::TestCascade::test_cache_hit_on_second_call`. All pass now.
- Red by environment, not by bug: the live-Qdrant recall set
  (`test_intake_recall::*[live_qdrant]`), the BGE rerank set
  (`test_reranker_bge::*`), `test_ranker_qdrant_payload_fallback`,
  `test_qdrant_snapshot_loader`, `test_costs_vector_adapter`,
  `test_cwicr_v3_catalogue`. These need the vector stack to be present.
- Red by missing extra: the pandas-backed dashboards
  (`test_dashboards_scaffolding`, `test_bi_dashboards`, `test_risk_service`)
  raise ModuleNotFoundError without the analytics extras installed.

So the artifact mixes already-fixed assertions with infra-dependent tests.
It is not a list of live regressions.

## Local reproduction caveat

The project requires Python 3.12 or newer (`requires-python = ">=3.12"`, and
`app/core/job_runner.py` uses the 3.12 `type X = ...` alias statement). A
runner on 3.11 hits a SyntaxError importing anything that pulls in
`job_runner`, and is also missing optional extras like pandas. So the suite
cannot be faithfully reproduced on 3.11, and this analysis was done against
the 3.12 CI run, not a local one. Use Python 3.12 with `pip install -e
".[dev]"` to reproduce.

## What shipped here

ci-full.yml now runs:

    pytest -q -ra --durations=50 --timeout=900 --timeout-method=thread

with `pytest-timeout` added to the dev extra. A single hung test now becomes
a reported failure at 15 minutes instead of consuming the whole budget, so
the run can finish, and `--durations=50` plus `-ra` make the slow spots and
the real failures readable without scrolling six hours of Postgres logs. The
15 minute ceiling is deliberately generous: no real unit or integration test
should come close.

This is the diagnostic step. It does not by itself make the suite fast; it
makes the next nightly terminate and tell us where the time and the failures
actually are.

## Recommended follow-ups (need a call)

1. Mark the live-infra tests (live Qdrant, BGE rerank, embeddings) with a
   marker and either stand up that infra in a dedicated job or exclude them
   from the plain nightly with `-m "not <marker>"`. They are real tests but
   they belong on a runner that has the stack.
2. Quiet Postgres in the test container (`log_min_messages=fatal` or similar)
   so the expected constraint violations from negative tests stop flooding
   the log.
3. Give each xdist worker its own database so the suite can finally run in
   parallel. That is the real fix for the wall-clock, not the timeout.
4. Consider adding the same `--timeout` to the unit gate in ci.yml so a hung
   unit test cannot quietly burn the 120 minute budget there either.
