"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``.dockerignore`` coverage tests (BUG-B06 fix).

Without a ``.dockerignore`` every ``docker build`` ships gigabytes of
context to the build daemon: customer BIM uploads, exports, the
marketing site, every test artefact, and, most dangerously, every
``.env`` file in the tree. That risks leaking secrets and customer
data into published images.

The database patterns below are a separate case and are deliberately
kept although the product has no local SQLite database any more.
PostgreSQL became the only supported engine in 6.6.0, but a working
tree older than that can still be carrying a multi-gigabyte
``openestimate.db``, and a pattern excluding a file nobody creates any
more costs nothing, while dropping it would let exactly those trees
bake that file into a published image.

Docker's ignore-file semantics match ``gitignore`` (shipped via the
moby/patternmatcher library); the ``pathspec`` package implements the
same grammar. These tests parse both ``.dockerignore`` files in the
repo, then assert that the *interesting* paths — secrets, large data,
local databases — are excluded, while the paths the Dockerfiles
explicitly need (source code, ``pyproject.toml``, etc.) survive.

If a future contributor weakens these excludes, the test fails —
this is the intent: the cost of an accidentally-published secret is
much higher than a noisy test.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

# Declared in the dev extra, but degrade to a reported skip rather than an
# import error if an environment lacks it. An uncollectable module aborts the
# ENTIRE pytest run, so a single absent test dependency used to make the whole
# suite unrunnable instead of costing us this one file.
pathspec = pytest.importorskip("pathspec", reason="pathspec is required for .dockerignore coverage")

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"


def _load_spec(path: Path) -> pathspec.PathSpec:
    """Compile a .dockerignore file into a gitignore-style PathSpec."""
    assert path.is_file(), f"missing dockerignore: {path}"
    text = path.read_text(encoding="utf-8")
    return pathspec.PathSpec.from_lines("gitwildmatch", text.splitlines())


@pytest.fixture(scope="module")
def root_spec() -> pathspec.PathSpec:
    """Top-level ``.dockerignore`` — used by ``Dockerfile.unified`` build."""
    return _load_spec(REPO_ROOT / ".dockerignore")


@pytest.fixture(scope="module")
def backend_spec() -> pathspec.PathSpec:
    """``backend/.dockerignore`` — used by the compose ``worker`` build."""
    return _load_spec(BACKEND_ROOT / ".dockerignore")


# ─────────────────────────────────────────────────────────────────────────
# Root context — must NOT ship secrets, local DB, customer uploads
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        # Secrets — the most important thing to keep out of images.
        ".env",
        ".env.local",
        ".env.production",
        "backend/.env",
        "backend/.env.test",
        "frontend/.env",
        "deploy/docker/credentials.json",
        "ops/service-account.json",
        "deploy/keys/server.pem",
        "deploy/keys/server.key",
        # Local databases — 1 GB SQLite full of test+demo data.
        "backend/openestimate.db",
        "backend/openestimate.db-journal",
        "backend/openestimate.db-shm",
        "backend/openestimate.db-wal",
        "backend/openestimate.db.cleanup-backup-20260425-220221",
        "backend/some_other.sqlite",
        "data/cache.sqlite3",
        # Customer uploads — never re-ship.
        "data/bim/some-project/file.rvt",
        "data/exports/report.pdf",
        "data/uploads/anything",
        # VCS / scratch / OS.
        ".git/HEAD",
        ".github/workflows/ci.yml",
        ".vscode/settings.json",
        ".DS_Store",
        "frontend/Thumbs.db",
        # Build / cache.
        "frontend/node_modules/react/index.js",
        "backend/.venv/lib/python3.12/site-packages/foo.py",
        "backend/__pycache__/foo.cpython-312.pyc",
        "frontend/.next/server.js",
        "frontend/dist/index.html",
        "frontend/test-results/run/trace.zip",
        "frontend/playwright-report/index.html",
        "backend/.pytest_cache/v/cache/lastfailed",
        # Out-of-image siblings.
        "desktop/main.ts",
        "website-marketing/dist/index.html",
        "i18n-audit/audit.csv",
        # Repo-root licensing prose. The copies under backend/ are the ones the
        # wheel build reads; no Dockerfile COPYs these. Both directions are
        # pinned because the patterns are anchored and negated, and a negation
        # written one line too wide would let the root copies back in without
        # any other test noticing.
        "LICENSE",
        "NOTICE",
        # Logs.
        "backend/server.log",
        "logs/app.log",
        # Archives.
        "release.tar.gz",
        "qa_install.zip",
    ],
)
def test_root_context_excludes_dangerous_paths(root_spec: pathspec.PathSpec, path: str) -> None:
    assert root_spec.match_file(path), (
        f"{path} should be excluded by root .dockerignore but is NOT — this would leak it into the unified Docker image"
    )


@pytest.mark.parametrize(
    "path",
    [
        # Source the unified build needs.
        "backend/app/main.py",
        "backend/app/config.py",
        "backend/app/modules/users/service.py",
        "backend/pyproject.toml",
        "backend/alembic.ini",
        "backend/alembic/env.py",
        # The verbatim AGPL-3.0 text. pyproject names it in license-files, so a
        # context that drops it produces a wheel with no licence file and an
        # image that conveys none either. The repo-root ``/LICENSE`` line stays
        # excluded on purpose and is anchored so it cannot reach down here.
        "backend/LICENSE",
        # The same arrangement and the newer half of it. license-files names
        # LICENSE and NOTICE, and it names them as glob patterns, so a context
        # missing this one does not fail Dockerfile.unified's
        # `pip install ./backend`. Measured on hatchling 1.32.0, the build exits
        # 0 and the image ships a wheel carrying one License-File instead of
        # two. Nothing downstream would say a word, which is why the context
        # has to be asserted rather than reasoned about.
        "backend/NOTICE",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/vite.config.ts",
        "frontend/src/main.tsx",
        "frontend/index.html",
        "frontend/tsconfig.json",
        # Small init data the image bakes.
        "data/init.sql",
        # Whitelisted env example.
        ".env.example",
    ],
)
def test_root_context_keeps_source_files(root_spec: pathspec.PathSpec, path: str) -> None:
    assert not root_spec.match_file(path), (
        f"{path} is required by the Dockerfile.unified build but the .dockerignore is excluding it"
    )


def test_root_context_keeps_every_force_included_path(root_spec: pathspec.PathSpec) -> None:
    """No path the wheel force-includes may be excluded from the build context.

    The list above is written by hand, so it only ever covers the paths someone
    thought to add. This one is derived from the force-include map, which is
    the list that actually decides whether the image builds: the wheel is built
    by pip inside the image, and hatchling aborts the whole build on the first
    force-included path it cannot find.

    scripts/check_docker_force_include_context.py holds that map and the
    Dockerfile's COPY lines to each other, but a COPY can only copy what the
    context contains. An entry that is present, copied and .dockerignored
    satisfies that check and still fails the build, which is exactly the
    position ``../frontend/dist`` is in and the reason it is exempt there. This
    closes that gap, and it needs pathspec, which is why it lives here rather
    than in the gate.
    """
    pyproject = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    # Only entries reaching outside backend/; everything else is covered by the
    # stage's own ``COPY backend/ backend/``. frontend/dist is a build artefact
    # that is deliberately ignored and supplied from the frontend-build stage.
    outside = {key[len("../") :] for key in force_include if key.startswith("../")}
    required = sorted(outside - {"frontend/dist"})
    assert required, "no force-include entry points outside backend/, so this test proved nothing"

    for relative in required:
        assert not root_spec.match_file(relative), (
            f"backend/pyproject.toml force-includes {relative}, and the root .dockerignore excludes it. "
            f"The Dockerfile cannot copy what the build context does not carry, so the image will fail "
            f"to build with 'Forced include not found'."
        )
        source = REPO_ROOT / relative
        if not source.is_dir():
            continue
        for child in sorted(source.rglob("*")):
            # Byte caches are ignored on purpose and are not part of what ships.
            if child.is_dir() or "__pycache__" in child.parts or child.suffix in {".pyc", ".pyo"}:
                continue
            as_posix = child.relative_to(REPO_ROOT).as_posix()
            assert not root_spec.match_file(as_posix), (
                f"{as_posix} sits under force-included {relative} but the root .dockerignore excludes it, "
                f"so the image would ship a pack or data directory missing a file it is supposed to carry."
            )


# ─────────────────────────────────────────────────────────────────────────
# Backend context (compose `worker`) — leaner sibling check
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        # Note: paths here are RELATIVE to backend/ (the build context)
        ".env",
        ".env.local",
        "openestimate.db",
        "openestimate.db-journal",
        "openestimate.db.cleanup-backup-20260425-220221",
        "storage/uploaded.bin",
        "tests/unit/test_demo_credentials.py",
        ".pytest_cache/v/cache/lastfailed",
        ".ruff_cache/CACHEDIR.TAG",
        "__pycache__/foo.cpython-312.pyc",
        "app/__pycache__/main.cpython-312.pyc",
        ".venv/lib/foo.py",
        "server.log",
        ".git/HEAD",
    ],
)
def test_backend_worker_context_excludes_dangerous_paths(backend_spec: pathspec.PathSpec, path: str) -> None:
    assert backend_spec.match_file(path), (
        f"{path} should be excluded by backend/.dockerignore but is NOT — "
        "this would leak it into the Celery worker image"
    )


@pytest.mark.parametrize(
    "path",
    [
        "app/main.py",
        "app/config.py",
        "app/modules/users/service.py",
        "app/core/jobs.py",
        "pyproject.toml",
        "alembic.ini",
        "alembic/env.py",
        # Both named by license-files in pyproject; the worker image installs
        # the same package and must be able to convey the licence it declares
        # and the notice that says what it bundles. Nothing in this file
        # excludes either, and that is worth an assertion rather than a
        # reading, since the `*.md` line two groups up catches neither only
        # because they carry no extension.
        "LICENSE",
        "NOTICE",
    ],
)
def test_backend_worker_context_keeps_source_files(backend_spec: pathspec.PathSpec, path: str) -> None:
    assert not backend_spec.match_file(path), (
        f"{path} is required by the worker build but backend/.dockerignore is excluding it"
    )


# ─────────────────────────────────────────────────────────────────────────
# Smoke checks against the real filesystem
# ─────────────────────────────────────────────────────────────────────────


def test_real_local_db_is_excluded(root_spec: pathspec.PathSpec) -> None:
    """``backend/openestimate.db`` must be excluded from the build context.

    The whole reason BUG-B06 was filed is that the QA tarball found this
    1 GB file in build contexts. The test guards against accidental
    pattern weakening.

    It used to skip itself when that file was not on disk, which turned it
    off in every environment it was written for. The file is gitignored, so
    a clean checkout never carries one and CI is nothing but clean
    checkouts: the guard ran only on a developer machine that happened to
    have a local database, and reported a green skip everywhere else. What
    is being asked here is whether ``.dockerignore`` excludes that PATH,
    and the pattern answers that whether or not the path is populated, so
    consulting the filesystem first could only ever silence the check.
    """
    rel = (BACKEND_ROOT / "openestimate.db").relative_to(REPO_ROOT).as_posix()
    assert root_spec.match_file(rel), f"{rel} would be sent to docker build"


def test_no_env_file_could_leak_into_image(root_spec: pathspec.PathSpec) -> None:
    """Walk the repo and assert every real ``.env*`` file is ignored.

    Excludes ``.env.example`` (whitelisted) and worktree/cache
    directories which already exist in their own ignore branches —
    the question we're answering is "does the .dockerignore excludes
    every secret-bearing file the build context could see?".
    """
    skipped_dirs = {".git", "node_modules", ".venv", ".next"}
    leaks: list[str] = []
    for env_file in REPO_ROOT.rglob(".env*"):
        if not env_file.is_file():
            continue
        if env_file.name == ".env.example":
            continue
        if any(part in skipped_dirs for part in env_file.parts):
            continue
        rel = env_file.relative_to(REPO_ROOT).as_posix()
        if not root_spec.match_file(rel):
            leaks.append(rel)
    assert not leaks, f"these .env files would be sent to docker build: {leaks}"
