# Developing on OpenConstructionERP, with or without an AI assistant

This file exists because the platform is large and its shape is not obvious from the outside.
There are 190 backend modules and around 180 frontend feature directories, and a newcomer who starts
by reading files at random will spend a week learning things that fit on a few pages. What
follows is that few pages. It is written for a competent developer who wants to run the
platform, change it for their own market, and be right about how it works rather than
plausible. It is also written to be handed to an AI coding assistant, because most people
doing this work now use one, and this codebase has several traps that make an assistant
confidently wrong.

Read it in one sitting. Then go and read the code, which is the only thing that is actually
authoritative.

## Which document wins

This file is written for people working from the public repository, and it is the document to
start from. But documents drift and the tree does not, so where this file disagrees with the
tree, the tree wins, and specifically:

Lint and Python version come from `backend/pyproject.toml`. The frontend gate comes from
`frontend/package.json`. Available commands come from the `Makefile`. What runs in continuous
integration comes from `.github/workflows/`.

That is not a formality, and this project supplied its own example of why. `CONTRIBUTING.md`
said for a long time that the Python line length is 100. `backend/pyproject.toml` sets it to 120,
`ruff` reads the latter, and anyone who trusted the prose reformatted code that was already
correct. The prose has since been corrected. The habit it should leave you with has not changed:
where a document and a configuration file disagree, the file is the one that runs.

Some of what follows was measured at version 16.2.0. Counts move. Where a number matters to a
decision you are making, count it yourself, and this file tries to tell you how.

## How contributing actually works here

This project does not accept external pull requests. Not for this module, not for a one-line
typo fix, not from anyone outside the core team. This is a security decision about a supply
chain, not a judgement about your code, and it applies uniformly. Pull requests are not merged,
not checked out, and not copied from. The same goes for patches, forks and dependency changes
proposed from outside.

Saying this early is the point. The alternative is that you write a module, open a pull request,
and find out afterwards.

What is genuinely wanted, and what the team acts on:

Issues, in as much detail as you can give. A specification of behaviour that is wrong or missing
for your market, with the standard or regulation it should follow. A reproduction: what you did,
what happened, what should have happened. A report from adapting the platform to a national
market, saying which of the things below you had to touch and what was not there. If you can
describe the correct behaviour precisely, that is the contribution. The team writes the
implementation from scratch and credits the person who specified it.

If you are running a pilot on a fork for your own use, that is exactly what the AGPL-3.0 licence
is for, and you owe nobody a pull request. Send the findings instead. They travel further.

Questions and reports: info@datadrivenconstruction.io

## Getting it running

`make setup` installs both halves, backend with `pip install -e .[server]` and frontend with
`npm install`. Python 3.12 or newer is required, and this is a hard floor rather than a
preference, because the code uses syntax that older interpreters cannot parse.

For day to day work you need two terminals. `make dev-backend` starts the API on port 8000,
`make dev-frontend` starts the interface on port 5173. `make dev` prints exactly this and
nothing else, which is a deliberate cross-platform choice. There is a `make dev-unix` that
backgrounds the backend into a single terminal, and it works only in POSIX shells.

`make quickstart` brings up PostgreSQL and the application together with no configuration, and
`make infra` starts PostgreSQL, Redis and MinIO on their own. `make seed` loads the cost catalog
and regional indices; demo projects are created automatically on first backend start.

Verification note, and please take it literally. The gates in the section below were run while
writing this file and passed. The setup and run commands above were read from the `Makefile` and
confirmed to exist as targets, but were not executed in this pass, because doing so on the
machine this was written on would have meant starting containers and a database. Treat them as
documented rather than as demonstrated, and tell us if one of them is wrong.

## The backend: modules and the loader

Everything is a module. A module is a Python package under `backend/app/modules/` containing a
`manifest.py`, and the manifest is the whole registration mechanism. `backend/app/core/module_loader.py`
scans for `manifest.py` files, sorts by declared dependencies, imports each package and mounts
its router.

The consequence is worth stating plainly, because it is the single most common way to lose an
afternoon here: a module directory with no `manifest.py` is invisible. It is not an error. The
scan simply does not find it, the module does not load, and nothing anywhere says so. If you
scaffolded a module and its endpoints are not there, check that first.

There are 193 directories under `backend/app/modules/` at the time of writing and 190 of them
carry a manifest. Count them yourself when it matters, with a scan for `manifest.py` one level
down, because the answer moves as modules land, and both of those numbers had already moved by
one between this file being drafted and being reviewed.

A directory without one is not automatically a mistake, though, and it is worth knowing why
before you go fixing them. Two different questions are being asked. Whether a directory has a
`manifest.py` decides whether the loader sees it at all. Whether it has a `router.py` decides
whether it serves URLs. Some directories here are neither, and are simply shared libraries that
other modules import directly, the way `backend/app/modules/boq/router.py` imports from
`measurement` and `price_breakdown`. So when you find a directory the registry does not list,
check whether anything imports it by name before concluding it is broken.
`scripts/check_module_manifests.py` encodes exactly this: it fails when a directory carries no
manifest and is not on a short allowlist of shared libraries, and it rechecks the reason rather
than trusting it, so an allowlisted directory that grows a router or a table fails too. What makes the
mechanism dangerous is not that it has exceptions, it is that it fails without saying anything.

Once a module is found, the loader imports its package and then, in order, `router`, `models`,
`hooks`, `events`, `validators`, `pipeline_nodes`. The last five are optional and their absence
is suppressed, so you write only the files you need. The router branch is more careful than that,
and the distinction matters: if `router.py` does not exist the loader stays quiet, but if
`router.py` exists and one of its transitive imports is missing, the loader logs loudly rather
than letting the router vanish. That was a deliberate fix. Read `module_loader.py` around the
router import if you want the reasoning, which is written out in the code.

URLs are kebab-case. A module directory named `site_inventory` is mounted at
`/api/v1/site-inventory`. The underscore form is also mounted as a legacy mirror, so
`/api/v1/site_inventory` answers too, but it is a compatibility alias and not the canonical form.
Write kebab-case in new code and in anything you publish.

`make module-new NAME=oe_tendering` scaffolds a module. Write it in one pass and in this order:
models, then schemas, then repository, then service, then router, then tests. That order is not
taste. Each layer depends only on the ones before it, so writing them in sequence means you never
have to guess at an interface that does not exist yet, and it is the order that reviewers and
assistants both expect. `backend/app/modules/boq/` is the module to read as a worked example.

## The frontend: two systems, and they are not the same thing

This is where most confusion starts, including in the existing documentation, which sometimes
speaks of them as one thing.

`frontend/src/features/<name>/` holds around 180 directories. These are wired by hand. To add
one you write the component and then add an explicit import and an explicit route to
`frontend/src/app/App.tsx`, one of each, by hand. That file is correspondingly long. There is no
discovery and no registry. If you did not add the line, the page does not exist.

`frontend/src/modules/<name>/` is a different mechanism entirely. It holds 17 opt-in plugin
modules, each with a `manifest.ts` declaring its routes, navigation items and bundled
translations, plus a `_shared` directory that is not a module. Registration is one import line
added to `frontend/src/modules/_registry.ts`. From there everything follows automatically:
`frontend/src/modules/ModuleRoutes.tsx` mounts the routes, `frontend/src/app/layout/Sidebar.tsx`
picks up the navigation items, and `frontend/src/app/i18n.ts` merges the module's own
translations into the language bundles. The components themselves are lazy-loaded from inside
the manifest, so they are code-split without you arranging it.

The second system is documented properly in `frontend/src/modules/MODULE_DEVELOPMENT_GUIDE.md`,
which ships in the repository and which nothing else links to. If you are adding an optional
capability rather than a core screen, read that file before you write anything. On the backend
side, `docs/module-development/quickstart.md` and `docs/module-development/boq-importer-plugin.md`
cover the equivalent ground.

Choosing between them is straightforward in practice. A core screen that everyone gets goes in
`features/`. An optional capability that a user can switch on or off, or that a market needs and
others do not, goes in `modules/`.

## The frontend gate is the build, not the type check

`npm run build` is `tsc -b` followed by `vite build`. `npm run typecheck` is `tsc --noEmit` and
stops there. These are not interchangeable and the difference is not academic. The build resolves
the module graph the way the bundle does, and `tsc -b` answers from `.tsbuildinfo` where a cold
`--noEmit` does not. A green `tsc --noEmit` read as a green build is how broken frontend commits
have shipped, more than once, recently enough that the `Makefile` carries a comment about it
above the `typecheck` target.

`make typecheck` runs `mypy` on the backend and `npm run build` on the frontend for exactly this
reason. Use it. A frontend change is not finished until a build has seen it.

That build was not run while writing this file, and the claim above comes from reading
`frontend/package.json` and the `Makefile`, both of which state it outright.

## Validation is part of the workflow, not an add-on

Validation is a first-class concern here and every module is expected to carry rules. There is no
central list of rules to edit, which surprises people who go looking for one.

A module declares its rules in its own `validators.py`. That file constructs `ValidationRule`
objects and calls `rule_registry.register(...)` at import time. The loader imports `validators.py`
automatically as part of loading the module, so registration happens by the file existing.
`backend/app/modules/boq/validators.py` is the example to copy, and `backend/app/core/validation/`
holds the engine.

The corollary is that rules registered at import time appear or disappear with their module. If a
module fails to load, its rules are silently absent from the registry too.

## Internationalisation, and the failure mode nobody catches

Every user-visible string goes through the translation layer. There are no hardcoded strings.
That is a hard rule and it is enforced by several gates.

The failure that gates do not catch is this. If you add a new key to
`frontend/src/app/locales/en.ts` and stop there, the application does not crash. It falls back to
English in every other language, silently, on screen, for every user who is not reading in
English. Lint passes. The type check passes. The build passes. The tests pass. This has shipped.
When you add a string, add it to every locale, or use the translation tooling to do so, and
verify by switching language rather than by watching a gate go green.

Counting the languages is worth doing carefully, because the two obvious numbers disagree and
both are correct. There are 43 locale files in `frontend/src/app/locales/`, and 41 languages
offered in the picker. The gap is two files that exist and are deliberately not offered:
`uz` is commented out in the `SUPPORTED_LANGUAGES` list in `frontend/src/app/i18n.ts`, and `mn`
is held back pending a native-speaker pass. Both carry their reason in a comment next to them. So
count files when you are asking about coverage, and count `SUPPORTED_LANGUAGES` when you are
asking what a user can select. If you inherit a single number for this, it is wrong for one of
the two questions.

Backend validation messages are a separate bundle with a separate and much smaller reach.
`backend/app/core/validation/messages/` ships `en.json`, `de.json`, `es.json` and `ru.json`, and
that is all of them. Four languages on the backend against 41 offered on the frontend. Nothing in
the interface tells a user this, and a validation report in, say, Polish will come back with
English message text. The resolution order is the requested locale, then English, then a
humanised form of the key, so it degrades quietly rather than breaking.

The good news for anyone adapting the platform is that this bundle is loaded by globbing
`*.json` in that directory. Adding `pl.json` there is the entire registration step and there is
no list to update. The catch is that it must be complete. Several tests iterate every loaded
locale and assert that every key resolves in it without falling back, so a partial new file does
not degrade quietly the way a partial frontend locale does. It turns the backend suite red
instead, which is the better failure but not the one you will be expecting.

## The gates you can run yourself

Continuous integration will run on what you push, but a green remote run is not evidence about
the tree in front of you, and the only gate that reliably catches your mistake is the one you ran
before you pushed. Run them locally.

`python scripts/check_repo_hygiene.py` refuses internal-only files that must never be published.
`python scripts/check_version_sync.py` checks that every version literal across the nine files
that carry one agrees. Both of these were run while writing this file, against version 16.2.0,
and both passed.

The ones a contributor trips over most often, beyond those two:
`check_i18n_placeholder_parity.py` catches a translation that asks for a variable the calling
code does not pass, which is the way a mechanical rename of a placeholder gets past every other
check. `check_i18n_orphan_keys.py` finds keys the code asks for that no locale file can answer.
`check_migration_heads.py` insists the migration graph has a single head. `check_head_imports.py`
checks that the committed tree can import itself, which is not automatic and has failed.
`check_zero_width.py` catches invisible characters. `check_no_brand_tokens.py` catches competitor
and vendor brand names, which are not allowed anywhere in the tree.

There are about forty of these in `scripts/`, each named for what it checks, and reading the
filenames is faster than reading this list. The workflows that call them are
`.github/workflows/repo-hygiene.yml` and `.github/workflows/ci.yml`.

One practical trap if you ever write a condition against these. The workflow in
`repo-hygiene.yml` is named "Repo hygiene", but its jobs are named "Whole-tree structural guards"
and "Locale and i18n guards". A status check carries the job name, not the workflow name, so a
condition written against "Repo hygiene" matches nothing and fails silently rather than
erroring. This has misled people repeatedly.

Backend style is `ruff format` and `ruff check`, and the version is pinned deliberately.
`backend/pyproject.toml` requires `ruff==0.16.6` in its dev extra and `.pre-commit-config.yaml`
holds the matching hook at `v0.16.6`. Both files carry a comment explaining why: the
`ruff format --check` gate compares against one formatter's exact output, so a different ruff
reformats differently and fails on code that passed locally. If you bump one, bump both. Run
`ruff format --check` before `ruff check`. The frontend has no automatic formatter, by decision,
so match the style of the file you are editing. Code, comments, docstrings, log messages, test names and commit
messages are all in English regardless of where you are. Non-Latin text is fine as data: locale
values, test fixtures, standard names, units, parsed spreadsheet headers.

## Briefing an AI coding assistant

If you are going to have an assistant work on this codebase, the difference between a useful
session and a frustrating one is almost entirely what you put in front of it first. Assistants
fail here in a specific way: the codebase looks conventional, so the assistant generalises from
other projects, and the places where this one differs are exactly the places where nothing
complains.

Point it at these, in this order. This file, first and whole. Then `backend/app/core/module_loader.py`,
which is the backend's entire extension model and is heavily commented with the reasoning behind
its awkward parts. Then `frontend/src/modules/_registry.ts` and
`frontend/src/modules/MODULE_DEVELOPMENT_GUIDE.md` for the frontend plugin model. Then one worked
module end to end, `backend/app/modules/boq/`, so it has a concrete example of the layer order
rather than a description of it. Then `docs/` for whatever domain the task touches, and
`docs/adr/` for decisions that look arbitrary until you read why.

The canonical format is the source of truth for project data. Everything imported, from any CAD
or exchange format, is converted into it, and every module reads and writes it rather than
reading a vendor format directly. An assistant that starts parsing a source format inside a
module has taken a wrong turn.

The principles the platform is built on, in short: stay lightweight, few dependencies, the core
runs on a small server. Internationalise everything, no hardcoded strings. Handle CAD by
conversion, never by embedding a CAD library. Treat validation as core workflow, never optional.
Make every capability a module with a manifest. Support open data standards natively, GAEB XML
3.3, DIN 276, NRM and MasterFormat among them. Let AI propose and require a human to confirm,
with confidence scores shown. Keep PostgreSQL as the only mandatory dependency.

The hard constraints, which are refusals rather than preferences: do not add an IFC or CAD
geometry library, and route all BIM and CAD work through conversion. BCF is allowed as an
input and output format for issues, viewpoints and validation reports, without pulling in a
geometry library. Do not treat IFC as native, it is one more format to convert. Do not write
monolithic code, every capability is a module with a manifest. Do not make validation optional.
Do not auto-apply AI output without human confirmation. Do not introduce vendor lock-in, all
data stays exportable and all formats open. Do not take code from external pull requests, forks
or patches. Do not publish internal working documents. Do not write developer-facing text in any
language but English. Do not name competitor brands anywhere in the code, commits, builds or
interface, and describe capabilities by category or function instead. Contact address is
info@datadrivenconstruction.io and no other.

For backend work, hold the assistant to one module at a time, complete, in the order models,
schemas, repository, service, router, tests. Core infrastructure gets tests first.

Finally, tell it about the traps, because it will not infer them and each one produces code that
looks right:

A module directory without `manifest.py` is invisible to the loader, with no error. A string
added only to `en.ts` falls back silently in 40 other languages with every gate green.
`frontend/src/features/` and `frontend/src/modules/` are two different systems with different
registration, and advice about one is wrong about the other. `tsc --noEmit` is not the gate,
`npm run build` is, and they disagree. And an assistant will tend to treat a remote pipeline as
the safety net, which it is not here: a run that went green somewhere else says nothing about
the tree in front of you, so the check you run before pushing is the one that counts.

## Adapting the platform to a national market

This is the most common reason to fork, so here is where regional behaviour actually lives.

Regional packs are the main mechanism. There are 13 of them, directories matching
`backend/app/modules/*_pack/`: `asia_pac_pack`, `china_pack`, `dach_pack`, `india_pack`,
`latam_pack`, `mexico_pack`, `middle_east_pack`, `russia_pack`, `sa_pack`, `uk_pack`,
`us_ca_pack`, `us_pack` and `us_tx_pack`. A pack declares what a market expects: its currency,
its date and number formats, the standards it uses, its measurement system, and the ISO 3166-1
alpha-2 country codes it claims.

`backend/app/core/regional_packs.py` resolves a project to its pack at runtime. Read its
docstring before adding a pack, because the resolution rules are deliberately conservative and
will surprise you otherwise. A country is matched first on the explicit ISO-2 code and only then,
as an exact fallback, on the free-text region field. A country claimed by several packs resolves
only if those packs agree, and returns nothing if they disagree. Anything unrecognised returns
nothing, which callers must treat as unconfigured rather than as a default.

One thing to note: that file holds an explicit tuple, `PACK_CONFIG_MODULES`, listing the pack
config modules it consults. It is a hand-maintained list, not filesystem discovery, chosen so the
import set stays explicit. A new pack must be added to it. There is an integration test that
fails when the tuple drifts from the packs on disk, so this is caught, but it is caught by a
test and not by the loader.

Beyond the pack, a market adaptation typically touches:

The interface language, in `frontend/src/app/locales/`. Adding a file is not enough, the language
must also be added to `SUPPORTED_LANGUAGES` in `frontend/src/app/i18n.ts` or it will not appear
in the picker, which is precisely what `mn` demonstrates today.

Backend validation messages, in `backend/app/core/validation/messages/`. Drop in a `<locale>.json`
and it is picked up by the directory glob. If you skip this, users of that language get English
validation text with no warning.

Validation rules themselves, since national standards differ. New rules go in a module's
`validators.py`, most naturally in the regional pack for that market.

Tax handling, in `backend/app/core/tax.py`, and currency formatting. Currency is a place to be
careful: formatting defaults derive from the currency itself, and the platform has already been
bitten by currencies whose conventional decimal places differ from what a generic formatter
assumes.

Cost data and classification standards. `MODULES.md` and `docs/` cover the import path for
national cost databases, and `docs/cost-database-import.md` is the specific document.

If you do this work, the report on what you had to touch is the single most useful thing you can
send back, especially the parts where this section turned out to be incomplete.

## Where to go next

`README.md` for what the platform does. `MODULES.md` for the module inventory. `docs/README.md`
as the entry point to the documentation, with `docs/adr/` for architecture decisions and their
reasoning, `docs/module-development/` for extending the backend, `docs/architecture/` and
`docs/platform/` for structure, and `docs/user-guide/` for how the product is meant to be used.
`CHANGELOG.md` for what has been changing, which is a good proxy for where the project's
attention currently is.

`SECURITY.md` for reporting a vulnerability, which should not go through a public issue.

Everything else: info@datadrivenconstruction.io
