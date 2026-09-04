# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The startup banner must not tell the user the server is up before it is.

``print_startup_banner`` has exactly one caller and it runs BEFORE uvicorn
starts, so everything the banner asserts about the server is asserted about a
process that has not bound its socket yet. On a first run that gap is not
notional: the boot this was measured on answered ``GET /`` after 50.55s and
``/api/health`` after about 490s, most of the latter being the demo seed.

The banner used to head that with a green tick over "OpenConstructionERP is
running", directly above the address to open. Beside an address, a tick is an
instruction, and a stranger who followed it got a browser error from an install
that was working perfectly.

So what is checked here is the claim rather than the wording: the banner may say
it is starting, and may not say it is running. The last two assertions are what
stop that being satisfied by deleting things - the address and the credentials
are the reason the banner is printed early at all, and a banner that dropped
them to avoid promising readiness would be a worse banner, not a fixed one.
"""

from __future__ import annotations

from pathlib import Path

from app.cli import print_startup_banner


def _banner(capsys) -> str:
    print_startup_banner(
        version="16.7.0",
        host="127.0.0.1",
        port=8080,
        data_dir=Path("/tmp/oe-data"),
        serve_frontend=True,
    )
    return capsys.readouterr().out


def test_the_banner_does_not_say_the_application_is_running(capsys) -> None:
    """It is printed before uvicorn starts, so it cannot know that, and it is not true."""
    assert "is running" not in _banner(capsys), (
        "the startup banner claims the application is running, but it is printed before uvicorn "
        "starts and the address it shows does not answer for a long time on a first boot"
    )


def test_the_banner_says_it_is_starting(capsys) -> None:
    """Saying nothing at all would leave the reader with an address and no expectation."""
    assert "is starting" in _banner(capsys)


def test_the_banner_still_hands_over_the_address_and_the_credentials(capsys) -> None:
    """The reason it is printed early, and so the half that must survive any rewording."""
    output = _banner(capsys)
    assert "http://127.0.0.1:8080" in output
    assert "demo@openconstructionerp.com" in output
