"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The embedder status card is told which case it is in, not asked to guess.

``/embedder/status/`` has always returned English prose telling the reader how
to install the optional semantic extra, and the frontend rendered that prose
verbatim. That is why the sentence was the one untranslated thing on an
otherwise fully translated panel: prose cannot be translated by the client, and
parsing it to recover the case would break on the first reword.

So the payload now names the case. The value exists to be looked up in a
translation table, which makes the relationship between it and the other two
fields load-bearing in a way a comment cannot enforce: a client that reads
``"pip"`` renders a copy box, and if ``pip_command`` were empty there it would
render an empty one. All three come off a single ``repair_hint`` call, so the
disagreement is structurally impossible today. This pins that, because the
obvious future edit is to compute the code from ``desktop_mode`` or from an
environment variable, either of which would answer a different question than
the one the command answers.

Both polarities are driven by setting ``sys.frozen``, which is the real switch
``is_frozen_build`` reads, rather than by stubbing our own function. A test that
replaces the branch it is checking proves only that the stub works.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

#: Every code this endpoint is allowed to emit. The frontend treats the field as
#: an open set and falls back to the prose on anything it does not know, so a new
#: value is a compatible change there. It is not a free one here: a value added
#: without a locale key behind it silently downgrades every language to English,
#: which is the exact defect this field was added to remove. Adding to this set
#: is the moment to notice that.
KNOWN_CODES = frozenset({"pip", "frozen_no_extra"})


def _status(monkeypatch: pytest.MonkeyPatch, *, frozen: bool) -> dict[str, Any]:
    """Read the endpoint once, with the interpreter claiming to be frozen or not."""
    from app.modules.costs.router import embedder_status

    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    return asyncio.run(embedder_status())


@pytest.mark.parametrize("frozen", [False, True])
def test_the_code_is_one_the_frontend_has_a_sentence_for(monkeypatch: pytest.MonkeyPatch, frozen: bool) -> None:
    payload = _status(monkeypatch, frozen=frozen)
    assert payload["install_hint_code"] in KNOWN_CODES, payload["install_hint_code"]


def test_a_pip_code_never_arrives_without_a_command_to_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one combination that would render an empty copy box."""
    for frozen in (False, True):
        payload = _status(monkeypatch, frozen=frozen)
        if payload["install_hint_code"] == "pip":
            assert payload["pip_command"].strip(), "code says pip and there is nothing to run"
        else:
            assert not payload["pip_command"], "there is no pip here, so nothing should be offered"


def test_the_prose_is_still_sent_for_clients_that_predate_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dropping ``install_hint`` would blank the panel on every older frontend.

    An older build reads the prose and knows nothing about the code. It is the
    fallback rung for a newer build too, on any code it does not recognise, so
    this field cannot become optional once the code exists.
    """
    for frozen in (False, True):
        payload = _status(monkeypatch, frozen=frozen)
        assert payload["install_hint"].strip(), "the fallback sentence is empty"


def test_the_two_installs_do_not_read_the_same(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control that catches a branch which stopped branching.

    Every assertion above passes if the endpoint returns one constant answer in
    both polarities, which is exactly what a broken ``is_frozen_build`` would
    produce, and it is the failure this field is most likely to acquire: the
    three checks above each hold within a single polarity. Two answers that come
    back equal are the finding, not a coincidence, so the difference is asserted
    rather than assumed.
    """
    loose = _status(monkeypatch, frozen=False)
    frozen = _status(monkeypatch, frozen=True)

    assert loose["install_hint_code"] != frozen["install_hint_code"]
    assert loose["install_hint"] != frozen["install_hint"]
    assert loose["pip_command"] != frozen["pip_command"]
    assert loose["install_hint_code"] == "pip"
    assert frozen["install_hint_code"] == "frozen_no_extra"
