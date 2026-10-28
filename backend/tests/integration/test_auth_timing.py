"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Login-endpoint timing-parity test (BUG-JWT01 / Wave 3-A).

Verifies that ``UserService.login`` already pays the dummy-bcrypt cost on
the missing-user branch (line ~329 of users/service.py), so that the wall
time of "unknown email" vs "real email + wrong password" stays within the
same order of magnitude.

If this test fails after a refactor, the most likely cause is that
someone removed the ``verify_password(...dummy hash...)`` call from the
``user is None`` branch — that's the construct that makes user
enumeration via timing infeasible.

This test follows the shared PostgreSQL isolation helpers in ``tests._pg``:
it runs the service layer directly on a transaction-isolated session (no
HTTP roundtrip, that adds far too much network noise to a timing test).

Run: pytest backend/tests/integration/test_auth_timing.py -v
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import suppress

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session

# ── Transaction-isolated PostgreSQL session (see tests/_pg.py) ────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:  # type: ignore[misc]
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


# ── Helpers ───────────────────────────────────────────────────────────────


async def _seed_user(session: AsyncSession, email: str, password: str) -> None:
    """Register a real user we'll later try to log in as."""
    from app.config import get_settings
    from app.modules.users.schemas import UserCreate
    from app.modules.users.service import UserService

    svc = UserService(session, get_settings())
    await svc.register(UserCreate(email=email, password=password, full_name="Timing Tester"))
    await session.commit()


def _bench_async(coro_factory, *, iterations: int) -> float:
    """Run ``coro_factory()`` ``iterations`` times, return trimmed-mean wall-time (sec).

    Discards slowest 10% to absorb GC / event-loop noise.
    """
    import asyncio

    samples: list[float] = []
    for _ in range(iterations):
        coro = coro_factory()
        t0 = time.perf_counter()
        try:
            asyncio.get_event_loop().run_until_complete(coro)
        except HTTPException:
            pass
        except Exception:  # noqa: BLE001
            pass
        samples.append(time.perf_counter() - t0)
    samples.sort()
    keep = samples[: max(1, int(len(samples) * 0.9))]
    return sum(keep) / len(keep)


# ── The actual timing-parity test ─────────────────────────────────────────


@pytest.mark.skipif(
    "COVERAGE_RUN" in os.environ or "COV_CORE_SOURCE" in os.environ,
    reason="Coverage tracing distorts microbenchmarks beyond usefulness",
)
@pytest.mark.asyncio
async def test_login_timing_parity_unknown_user_vs_bad_password(session: AsyncSession) -> None:
    """Wall time of bad-username vs bad-password must stay within the same order.

    Threshold is generous (3x) because bcrypt cost dominates both paths:
    a real user does ONE bcrypt verify against the stored hash, an unknown
    user does ONE bcrypt verify against a fixed dummy hash. The two should
    be near-equal in cost. If this ratio blows out, the dummy-bcrypt
    safeguard has been removed.
    """
    from app.config import get_settings
    from app.modules.users.schemas import LoginRequest
    from app.modules.users.service import UserService

    real_email = f"real-{uuid.uuid4().hex[:6]}@timing.io"
    real_password = "TimingTest123!"  # noqa: S105
    await _seed_user(session, real_email, real_password)

    svc = UserService(session, get_settings())

    async def _bad_username() -> None:
        # Definitely-not-registered email — exercises the ``user is None`` branch.
        with suppress(HTTPException):
            await svc.login(LoginRequest(email=f"ghost-{uuid.uuid4().hex[:6]}@timing.io", password="WrongPass123!"))

    async def _bad_password() -> None:
        # Real user, wrong password — exercises the ``verify_password`` branch.
        with suppress(HTTPException):
            await svc.login(LoginRequest(email=real_email, password="WrongPass456!"))

    # Warm-up: bcrypt's first call after import is markedly slower (lazy native init).
    for _ in range(3):
        await _bad_username()
        await _bad_password()

    # We can't easily run the asyncio.run-based _bench_async helper from
    # inside a pytest-asyncio event loop, so instead we time inline awaits.
    iterations = 12  # bcrypt cost=12 → ~250ms each → keep iterations modest
    samples_unknown: list[float] = []
    samples_badpw: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        await _bad_username()
        samples_unknown.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        await _bad_password()
        samples_badpw.append(time.perf_counter() - t0)

    samples_unknown.sort()
    samples_badpw.sort()
    keep = max(1, int(iterations * 0.75))
    mean_unknown = sum(samples_unknown[:keep]) / keep
    mean_badpw = sum(samples_badpw[:keep]) / keep

    a = max(mean_unknown, 1e-6)
    b = max(mean_badpw, 1e-6)
    ratio = max(a, b) / min(a, b)

    assert ratio < 3.0, (
        f"Login timing leak detected: unknown-user={mean_unknown * 1000:.0f}ms  "
        f"bad-password={mean_badpw * 1000:.0f}ms  ratio={ratio:.2f}x (should be <3x). "
        f"Likely cause: the dummy-bcrypt call in UserService.login was removed."
    )
