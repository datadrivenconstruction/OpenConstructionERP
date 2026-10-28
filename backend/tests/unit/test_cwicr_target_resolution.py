"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The CWICR v3 store resolves to one place, and writes never outrun reads.

Four call sites used to answer "where is the CWICR store" and no two were
written from the same rule. ``qdrant_adapter._get_client`` consulted
``cwicr_qdrant_url`` alone and otherwise opened an embedded store;
``qdrant_snapshot_loader`` consulted it strictly in one function and
leniently in another; the router helper added ``or qdrant_url``. Because
``qdrant_url`` carries a non-None default and ``cwicr_qdrant_url`` carries
none, the lenient resolutions could never fall through and the strict one
always did. On a default install the snapshot therefore restored to
``http://localhost:6333`` while the ranker opened
``~/.openestimator/qdrant_cwicr``, and every surface reported success.

The invariant these tests hold is not "the four agree today". It is that a
write target is never a server the reader does not open: either the two
resolve to the same place, or the write is refused with a message an
operator can act on.

Every case builds ``Settings(_env_file=None, ...)``. Without that, pydantic
loads ``backend/.env``, and on a developer machine that file sets
``CWICR_QDRANT_URL`` - which silently supplies the missing value to every
case and makes the whole file pass by describing the machine rather than
the product.

Two assertions here were never proved red, and the next reader should not
assume otherwise just because the rest of the file was. Both are in the
``is_server`` branch of the cross-module invariant below: ``mismatch is
None`` and ``write_target == read_target.location``. Both injections
restored the old lenient resolution, which is a failure of the embedded
branch, so the configured-server cases stayed green throughout. They pin the
positive path - that a correctly configured server is NOT refused - and a
regression that breaks them would be a refusal storm rather than a silent
divergence, which is loud enough to find without a red run behind it.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.modules.costs.qdrant_adapter import (
    describe_server_write_mismatch,
    resolve_cwicr_target,
)

EMBEDDED_SUFFIX = "qdrant_cwicr"


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_shipped_defaults_resolve_to_the_embedded_store() -> None:
    """A fresh install reads its own disk, not localhost:6333.

    This is the assertion that documents the trap. ``qdrant_url`` defaults
    to a URL, so anything lenient resolves to a server here; the store the
    ranker actually opens is embedded.
    """
    target = resolve_cwicr_target(_settings())

    assert target.kind == "embedded"
    assert target.is_server is False
    assert EMBEDDED_SUFFIX in target.location


def test_the_general_qdrant_url_does_not_move_the_cwicr_store() -> None:
    """Setting QDRANT_URL alone must not repoint the CWICR ranker.

    It is the general cross-module vector store's setting. Honouring it
    here is the one-line "consistency fix" that would swing every
    unconfigured install onto a port that is usually nothing.
    """
    target = resolve_cwicr_target(_settings(qdrant_url="http://someone-elses-qdrant:6333"))

    assert target.kind == "embedded"
    assert "someone-elses-qdrant" not in target.location


def test_the_dedicated_setting_moves_the_store() -> None:
    target = resolve_cwicr_target(_settings(cwicr_qdrant_url="http://cwicr:6333"))

    assert target.kind == "url"
    assert target.location == "http://cwicr:6333"


def test_the_dedicated_setting_wins_over_the_general_one() -> None:
    """Both set and disagreeing: the CWICR setting decides, unambiguously."""
    target = resolve_cwicr_target(_settings(qdrant_url="http://general:6333", cwicr_qdrant_url="http://cwicr:6333"))

    assert target.location == "http://cwicr:6333"


# ── The wiring invariant ────────────────────────────────────────────────
#
# Each case is (label, settings kwargs). The adversarial ones are the point:
# a settings object where the two names disagree is exactly where a
# re-introduced fallback would separate the write from the read again.
_CASES = [
    ("shipped defaults", {}),
    ("general URL only", {"qdrant_url": "http://general:6333"}),
    ("general URL explicitly cleared", {"qdrant_url": None}),
    ("dedicated URL only", {"cwicr_qdrant_url": "http://cwicr:6333"}),
    ("both, same host", {"qdrant_url": "http://same:6333", "cwicr_qdrant_url": "http://same:6333"}),
    ("both, different hosts", {"qdrant_url": "http://general:6333", "cwicr_qdrant_url": "http://cwicr:6333"}),
    ("embedded path pinned", {"cwicr_qdrant_path": "/var/lib/oce/cwicr"}),
]


@pytest.mark.parametrize(("label", "kw"), _CASES, ids=[c[0] for c in _CASES])
def test_a_write_never_targets_a_server_the_reader_does_not_open(
    label: str, kw: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The invariant, stated once and checked over every configuration.

    The write target is read from the ROUTER's own helper rather than
    recomputed here. Asserting that two calls to one function agree would
    be a tautology; the defect was that two MODULES disagreed, so the test
    has to cross the same boundary the bug did.

    For any settings object there are then exactly two honest outcomes:
    the write goes where the read goes, or there is no server-mode write
    to make and the caller is told why.
    """
    from app.modules.costs import qdrant_adapter
    from app.modules.costs.router import _v3_qdrant_url

    settings = _settings(**kw)
    monkeypatch.setattr(qdrant_adapter, "get_settings", lambda: settings)

    read_target = resolve_cwicr_target(settings)
    write_target = _v3_qdrant_url()
    mismatch = describe_server_write_mismatch(settings)

    if read_target.is_server:
        # A write is allowed, and it lands on precisely the read target.
        assert mismatch is None
        assert write_target == read_target.location
    else:
        # No server write is offered at all, and the refusal has to be usable.
        assert write_target is None
        assert mismatch is not None
        assert "CWICR_QDRANT_URL" in mismatch
        assert read_target.location in mismatch


def test_the_refusal_names_the_general_setting_without_recommending_it() -> None:
    """The message has to explain the near-miss, not invite it.

    An operator who set QDRANT_URL and got nothing needs to be told that
    the value was seen and deliberately not used. Telling them to "set
    QDRANT_URL or CWICR_QDRANT_URL", as two of these messages used to,
    sends them back to the setting that cannot work.
    """
    message = describe_server_write_mismatch(_settings(qdrant_url="http://general:6333"))

    assert message is not None
    assert "http://general:6333" in message
    assert "CWICR_QDRANT_URL" in message
    # No wording that presents the general setting as a fix.
    assert "or QDRANT_URL" not in message
    assert "set QDRANT_URL" not in message.lower()
