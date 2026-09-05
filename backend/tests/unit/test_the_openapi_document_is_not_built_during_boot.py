"""Booting must not build the OpenAPI document unless somebody asked for it.

The document takes 73.0s to assemble on this stand, for 2923 paths and 3601
component schemas, and it is CPU-bound Python. Running it on a worker thread is
not the same as running it out of the way: measured on a boot with the prime
opted back in and nothing else competing, the first request to arrive after the
port opened took 64.6s, and the two after it 2.3s and 2.2s, before latency
settled at 0.15s. The boot started that build on every non-production start and
every desktop launch paid it.

Nothing reads it there. It has exactly three consumers, ``/api/docs``,
``/api/redoc`` and ``/api/openapi.json``, and a desktop user opens none of them
on the way in. So the default is off, whoever does open those pages pays the
build on that request - cached and locked by ``_custom_openapi`` exactly as
before, which is what this deployment did until the prime was added - and an
operator serving the reference pages to other people opts back in with
``OE_PRIME_OPENAPI_SCHEMA=1``.

This pins the default and both halves of the gate. A default is the easiest
thing in a codebase to flip back by accident, and the cost of flipping this one
is two minutes of a core on every launch of every install.
"""

from __future__ import annotations

from app.main import PRIME_OPENAPI_SCHEMA_ENV, should_prime_openapi_schema


def test_a_boot_that_was_not_asked_does_not_build_the_document() -> None:
    """The default, stated as a test because it used to be the other way."""
    assert should_prime_openapi_schema(fast_startup=False, openapi_url="/api/openapi.json", env={}) is False


def test_an_operator_can_ask_for_it() -> None:
    """The lever exists, so serving the reference pages is still a supported choice."""
    for spelling in ("1", "true", "TRUE", "yes", " 1 "):
        assert (
            should_prime_openapi_schema(
                fast_startup=False,
                openapi_url="/api/openapi.json",
                env={PRIME_OPENAPI_SCHEMA_ENV: spelling},
            )
            is True
        ), f"{spelling!r} should read as an opt-in"


def test_a_value_that_is_not_an_opt_in_is_not_treated_as_one() -> None:
    """``0`` and ``off`` must not turn on the most expensive thing a boot can do."""
    for spelling in ("0", "false", "no", "off", ""):
        assert (
            should_prime_openapi_schema(
                fast_startup=False,
                openapi_url="/api/openapi.json",
                env={PRIME_OPENAPI_SCHEMA_ENV: spelling},
            )
            is False
        ), f"{spelling!r} should not read as an opt-in"


def test_production_does_not_build_a_document_it_will_not_serve() -> None:
    """``openapi_url`` is ``None`` in production and takes /api/docs with it.

    Asking for the prime there would spend the whole build on a 2 GB VPS to fill
    a cache with no reader, in the window where a healthcheck timeout turns into
    a restart loop. The opt-in does not override that.
    """
    assert (
        should_prime_openapi_schema(
            fast_startup=False,
            openapi_url=None,
            env={PRIME_OPENAPI_SCHEMA_ENV: "1"},
        )
        is False
    )


def test_the_test_suite_never_pays_for_it() -> None:
    """``OE_TEST_FAST_STARTUP`` wins over the opt-in, as it does for every warm-up."""
    assert (
        should_prime_openapi_schema(
            fast_startup=True,
            openapi_url="/api/openapi.json",
            env={PRIME_OPENAPI_SCHEMA_ENV: "1"},
        )
        is False
    )
