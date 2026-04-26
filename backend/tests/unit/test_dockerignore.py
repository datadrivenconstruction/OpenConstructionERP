"""``.dockerignore`` coverage tests (BUG-B06 fix).

Without a ``.dockerignore`` every ``docker build`` ships ~2 GB of
context to the build daemon: the local SQLite DB (1 GB), customer BIM
uploads, the marketing site, every test artefact, and — most
dangerously — every ``.env`` file in the tree. That risks leaking
secrets and customer data into published images.

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

from pathlib import Path

import pathspec
import pytest


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
        ".claude/worktrees/foo/file.py",
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
        # Logs.
        "backend/server.log",
        "logs/app.log",
        # Archives.
        "release.tar.gz",
        "qa_install.zip",
    ],
)
def test_root_context_excludes_dangerous_paths(
    root_spec: pathspec.PathSpec, path: str
) -> None:
    assert root_spec.match_file(path), (
        f"{path} should be excluded by root .dockerignore but is NOT — "
        "this would leak it into the unified Docker image"
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
def test_root_context_keeps_source_files(
    root_spec: pathspec.PathSpec, path: str
) -> None:
    assert not root_spec.match_file(path), (
        f"{path} is required by the Dockerfile.unified build but the "
        ".dockerignore is excluding it"
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
def test_backend_worker_context_excludes_dangerous_paths(
    backend_spec: pathspec.PathSpec, path: str
) -> None:
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
    ],
)
def test_backend_worker_context_keeps_source_files(
    backend_spec: pathspec.PathSpec, path: str
) -> None:
    assert not backend_spec.match_file(path), (
        f"{path} is required by the worker build but backend/.dockerignore "
        "is excluding it"
    )


# ─────────────────────────────────────────────────────────────────────────
# Smoke checks against the real filesystem
# ─────────────────────────────────────────────────────────────────────────


def test_real_local_db_is_excluded(root_spec: pathspec.PathSpec) -> None:
    """If ``backend/openestimate.db`` exists locally, it must be excluded.

    The whole reason BUG-B06 was filed is that the QA tarball found this
    1 GB file in build contexts. The test guards against accidental
    pattern weakening.
    """
    db = BACKEND_ROOT / "openestimate.db"
    if not db.exists():
        pytest.skip("no local DB present — running in clean env")
    rel = db.relative_to(REPO_ROOT).as_posix()
    assert root_spec.match_file(rel), f"{rel} would be sent to docker build"


def test_no_env_file_could_leak_into_image(root_spec: pathspec.PathSpec) -> None:
    """Walk the repo and assert every real ``.env*`` file is ignored.

    Excludes ``.env.example`` (whitelisted) and worktree/cache
    directories which already exist in their own ignore branches —
    the question we're answering is "does the .dockerignore excludes
    every secret-bearing file the build context could see?".
    """
    skipped_dirs = {".git", "node_modules", ".venv", ".claude", ".next"}
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
