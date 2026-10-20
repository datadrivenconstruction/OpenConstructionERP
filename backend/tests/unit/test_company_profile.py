# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Company profile: the letterhead printed on generated documents.

Two tests here guard promises nothing else in the codebase checks.

:func:`test_the_public_branding_endpoint_never_carries_the_profile` - the app
brand is served to anonymous callers because the login page needs it, and the
profile holds a registered address and tax identifiers. The two sit next to
each other in the settings UI and in the PDF layer, so folding one into the
other is an easy tidy-up that would publish the second to the internet.

:func:`test_an_empty_profile_draws_no_letterhead` - the PDF layer draws the
letterhead only when :func:`has_letterhead` says so, and that is what keeps
every existing workspace's documents byte-identical after the upgrade.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.app_branding import MAX_LOGO_DATA_URL_CHARS, branding_path, write_branding
from app.core.company_profile import (
    DEFAULT_COMPANY_PROFILE,
    LOGO_IMAGE_TYPES,
    MAX_ADDRESS_CHARS,
    MAX_ADDRESS_LINES,
    MAX_EMAIL,
    MAX_LEGAL_NAME,
    MAX_PHONE,
    MAX_REGISTRATION_LINE,
    MAX_WEBSITE,
    company_profile_path,
    has_letterhead,
    read_company_profile,
    reset_company_profile,
    sanitise,
    write_company_profile,
)
from app.core.company_profile_router import router as company_profile_router
from app.dependencies import get_current_user_payload

_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

_LINE_CAPS = {
    "legal_name": MAX_LEGAL_NAME,
    "registration_line": MAX_REGISTRATION_LINE,
    "phone": MAX_PHONE,
    "email": MAX_EMAIL,
    "website": MAX_WEBSITE,
}

_FULL_PROFILE = {
    "document_logo_data_url": _PNG,
    "document_logo_png_data_url": "",
    "legal_name": "Acme Builders GmbH",
    "address": "Musterstrasse 1\n10115 Berlin\nGermany",
    "registration_line": "USt-IdNr. DE123456789 · HRB 12345",
    "phone": "+49 30 1234567",
    "email": "office@acme.example",
    "website": "acme.example",
}


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every no-argument read and write at the test's own directory.

    The router calls the module without a ``data_dir``, so without this a
    router test would write the profile into the real data dir of whoever
    runs the suite.
    """
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    return tmp_path


# -- sanitiser and storage ------------------------------------------------


def test_an_unset_workspace_reads_the_defaults(tmp_path: Path) -> None:
    assert read_company_profile(tmp_path) == DEFAULT_COMPANY_PROFILE


def test_every_default_is_an_empty_string() -> None:
    """Unset is ``""``, never ``None``: the PDF layer codes against one shape."""
    assert all(value == "" for value in DEFAULT_COMPANY_PROFILE.values())


def test_a_saved_profile_survives_a_read(tmp_path: Path) -> None:
    written = write_company_profile(_FULL_PROFILE, tmp_path)
    assert written == _FULL_PROFILE
    assert read_company_profile(tmp_path) == _FULL_PROFILE


def test_the_profile_has_its_own_file(tmp_path: Path) -> None:
    """The branding file is served anonymously; the profile must not live in it."""
    assert company_profile_path(tmp_path) != branding_path(tmp_path)
    write_company_profile(_FULL_PROFILE, tmp_path)
    assert not branding_path(tmp_path).exists()


def test_a_second_save_on_the_same_timestamp_is_still_seen(tmp_path: Path) -> None:
    """Both names are nine characters, so only the writer's cache drop can catch this.

    Windows gives two writes in the same clock tick the same ``st_mtime_ns``;
    the collision is forced with :func:`os.utime` so it reproduces everywhere.
    """
    write_company_profile({"legal_name": "Alpha Ltd"}, tmp_path)
    assert read_company_profile(tmp_path)["legal_name"] == "Alpha Ltd"
    before = company_profile_path(tmp_path).stat()

    write_company_profile({"legal_name": "Omega Ltd"}, tmp_path)
    os.utime(company_profile_path(tmp_path), ns=(before.st_atime_ns, before.st_mtime_ns))

    assert company_profile_path(tmp_path).stat().st_size == before.st_size
    assert read_company_profile(tmp_path)["legal_name"] == "Omega Ltd"


def test_a_file_rewritten_by_another_process_is_still_seen(tmp_path: Path) -> None:
    """A worker rendering the export never sees the API's cache drop; the size has to.

    Exports can run in a Celery worker that holds a cache of its own, so the
    only signal it gets is the file on disk.
    """
    write_company_profile({"legal_name": "Alpha Ltd"}, tmp_path)
    assert read_company_profile(tmp_path)["legal_name"] == "Alpha Ltd"
    path = company_profile_path(tmp_path)
    before = path.stat()

    # Straight to disk, the way a second process would leave it.
    longer = "A considerably longer legal name than the first"
    path.write_text(json.dumps({"legal_name": longer}), encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    now = path.stat()
    assert now.st_mtime_ns == before.st_mtime_ns, "the timestamp collision is what is being tested"
    assert now.st_size != before.st_size, "only the length may give the change away"
    assert read_company_profile(tmp_path)["legal_name"] == longer


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("legal_name", 7),
        ("address", ["Musterstrasse 1"]),
        ("registration_line", {"vat": "DE123"}),
        ("phone", None),
        ("email", True),
        ("website", 3.5),
        ("document_logo_data_url", "https://acme.example/logo.png"),
        ("document_logo_data_url", "data:image/gif;base64,R0lGODlhAQABAAAAACw="),
        ("document_logo_data_url", "data:text/html;base64,PHNjcmlwdD4="),
        ("document_logo_data_url", "data:image/png,rawbytes"),
        ("document_logo_data_url", "data:image/png;base64,"),
        ("document_logo_data_url", 42),
    ],
)
def test_one_bad_value_costs_only_that_value(field: str, value: object) -> None:
    """A rejected field falls back alone; the rest of the letterhead survives.

    Discarding the whole payload would cost a firm its legal name and address
    because it also uploaded a GIF.
    """
    payload = dict(_FULL_PROFILE)
    payload[field] = value

    clean = sanitise(payload)

    assert clean[field] == ""
    for other in DEFAULT_COMPANY_PROFILE:
        if other != field:
            assert clean[other] == _FULL_PROFILE[other]


@pytest.mark.parametrize(("field", "cap"), list(_LINE_CAPS.items()))
def test_a_long_line_is_trimmed_not_refused(field: str, cap: int) -> None:
    assert sanitise({field: "x" * (cap + 25)})[field] == "x" * cap


@pytest.mark.parametrize("field", list(_LINE_CAPS))
def test_a_single_line_field_stays_on_one_line(field: str) -> None:
    """Line breaks become spaces, so a pasted cell reads as words, not one run-on word."""
    clean = sanitise({field: "  Acme\r\nBuilders\x00\tLtd  "})[field]
    assert clean == "Acme Builders Ltd"[: _LINE_CAPS[field]]


def test_the_address_keeps_its_lines_as_written() -> None:
    """A textarea submits CRLF; blank lines and edge whitespace go, the order stays."""
    clean = sanitise({"address": "  Musterstrasse 1 \r\n\r\n  10115 Berlin\r\nGermany  \r\n"})["address"]
    assert clean == "Musterstrasse 1\n10115 Berlin\nGermany"


def test_control_characters_do_not_survive_in_the_address() -> None:
    assert sanitise({"address": "Main St\x00 1\x1b\nSpringfield"})["address"] == "Main St 1\nSpringfield"


def test_the_address_is_capped_in_lines_and_characters() -> None:
    lines = sanitise({"address": "one\ntwo\nthree\nfour\nfive"})["address"].split("\n")
    assert lines == ["one", "two", "three"]

    long_lines = "\n".join(["y" * 200] * MAX_ADDRESS_LINES)
    clean = sanitise({"address": long_lines})["address"]
    assert len(clean) <= MAX_ADDRESS_CHARS
    assert len(clean.split("\n")) <= MAX_ADDRESS_LINES
    assert clean.startswith("y" * 200 + "\n")


@pytest.mark.parametrize("kind", LOGO_IMAGE_TYPES)
def test_every_offered_logo_type_is_accepted(kind: str) -> None:
    """Whatever the options endpoint advertises, the sanitiser must keep."""
    logo = f"data:image/{kind};base64,AAAA"
    assert sanitise({"document_logo_data_url": logo})["document_logo_data_url"] == logo


def test_a_logo_at_the_cap_is_kept_and_one_over_is_dropped() -> None:
    """The cap is app_branding's, so the two logo uploads cannot drift apart."""
    prefix = "data:image/png;base64,"
    at_cap = prefix + "A" * (MAX_LOGO_DATA_URL_CHARS - len(prefix))
    over = at_cap + "A"
    assert sanitise({"document_logo_data_url": at_cap})["document_logo_data_url"] == at_cap
    assert sanitise({"document_logo_data_url": over})["document_logo_data_url"] == ""


@pytest.mark.parametrize("junk", [None, "", 7, [], "not a dict"])
def test_corrupt_input_reads_as_the_default(junk: object) -> None:
    assert sanitise(junk) == DEFAULT_COMPANY_PROFILE


def test_unknown_keys_are_not_stored() -> None:
    assert set(sanitise({**_FULL_PROFILE, "iban": "DE00"})) == set(DEFAULT_COMPANY_PROFILE)


def test_a_corrupt_file_never_raises(tmp_path: Path) -> None:
    """A hand-edited file must cost the letterhead, not the export."""
    company_profile_path(tmp_path).write_text("{ this is not json", encoding="utf-8")
    assert read_company_profile(tmp_path) == DEFAULT_COMPANY_PROFILE


def test_a_hand_edited_file_is_sanitised_on_read(tmp_path: Path) -> None:
    company_profile_path(tmp_path).write_text(
        json.dumps({"legal_name": "Acme\nLtd", "document_logo_data_url": "javascript:alert(1)"}),
        encoding="utf-8",
    )
    profile = read_company_profile(tmp_path)
    assert profile["legal_name"] == "Acme Ltd"
    assert profile["document_logo_data_url"] == ""


def test_saving_an_empty_profile_removes_the_file(tmp_path: Path) -> None:
    write_company_profile({"legal_name": "Acme"}, tmp_path)
    assert company_profile_path(tmp_path).exists()
    write_company_profile(dict(DEFAULT_COMPANY_PROFILE), tmp_path)
    assert not company_profile_path(tmp_path).exists()
    assert read_company_profile(tmp_path) == DEFAULT_COMPANY_PROFILE


def test_reset_is_safe_when_nothing_was_saved(tmp_path: Path) -> None:
    assert reset_company_profile(tmp_path) == DEFAULT_COMPANY_PROFILE


def test_a_reset_is_seen_by_the_next_read(tmp_path: Path) -> None:
    write_company_profile({"legal_name": "Acme"}, tmp_path)
    assert read_company_profile(tmp_path)["legal_name"] == "Acme"
    reset_company_profile(tmp_path)
    assert read_company_profile(tmp_path) == DEFAULT_COMPANY_PROFILE


# -- has_letterhead --------------------------------------------------------


def test_an_empty_profile_draws_no_letterhead() -> None:
    assert has_letterhead(dict(DEFAULT_COMPANY_PROFILE)) is False


@pytest.mark.parametrize("field", ["legal_name", "document_logo_data_url"])
def test_a_name_or_a_logo_alone_draws_the_letterhead(field: str) -> None:
    profile = dict(DEFAULT_COMPANY_PROFILE)
    profile[field] = _FULL_PROFILE[field]
    assert has_letterhead(profile) is True


def test_contact_details_without_a_name_or_logo_draw_no_letterhead() -> None:
    """A block of details with nobody named above it does not say whose they are."""
    profile = dict(_FULL_PROFILE)
    profile["legal_name"] = ""
    profile["document_logo_data_url"] = ""
    assert has_letterhead(profile) is False


@pytest.mark.parametrize("junk", [None, "Acme", [], {"legal_name": "   "}, {"legal_name": 7}])
def test_has_letterhead_never_raises_on_junk(junk: object) -> None:
    assert has_letterhead(junk) is False


# -- router ----------------------------------------------------------------


def _client(role: str | None) -> TestClient:
    """A client signed in with ``role``, or anonymous when ``None``."""
    app = FastAPI()
    app.include_router(company_profile_router, prefix="/api/v1")
    if role is not None:

        async def _payload() -> dict[str, str]:
            return {"sub": "user-under-test", "role": role}

        app.dependency_overrides[get_current_user_payload] = _payload
    return TestClient(app)


@pytest.fixture
def admin() -> Iterator[TestClient]:
    with _client("admin") as client:
        yield client


@pytest.mark.parametrize("path", ["/api/v1/company-profile/", "/api/v1/company-profile/options/"])
def test_anonymous_callers_are_refused(path: str) -> None:
    with _client(None) as client:
        assert client.get(path).status_code == 401


def test_any_signed_in_user_can_read_the_profile(_data_dir: Path) -> None:
    """A viewer exporting an RFI needs the letterhead as much as an admin does."""
    write_company_profile(_FULL_PROFILE, _data_dir)
    with _client("viewer") as client:
        for path in ("/api/v1/company-profile/", "/api/v1/company-profile"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.json() == _FULL_PROFILE


@pytest.mark.parametrize("role", ["viewer", "editor", "manager"])
def test_only_an_admin_can_change_the_profile(role: str, _data_dir: Path) -> None:
    write_company_profile({"legal_name": "Acme"}, _data_dir)
    with _client(role) as client:
        assert client.put("/api/v1/company-profile/", json={"legal_name": "Mallory"}).status_code == 403
        assert client.delete("/api/v1/company-profile/").status_code == 403
    assert read_company_profile(_data_dir)["legal_name"] == "Acme"


def test_put_merges_over_the_stored_profile(admin: TestClient, _data_dir: Path) -> None:
    """Null leaves a field alone, an empty string clears it, and nothing else moves."""
    first = admin.put(
        "/api/v1/company-profile/",
        json={"legal_name": "Acme Builders GmbH", "address": "Musterstrasse 1\r\n10115 Berlin"},
    )
    assert first.status_code == 200
    assert first.json()["address"] == "Musterstrasse 1\n10115 Berlin"

    second = admin.put("/api/v1/company-profile/", json={"legal_name": None, "phone": "+49 30 1234567"})
    assert second.json()["legal_name"] == "Acme Builders GmbH"
    assert second.json()["address"] == "Musterstrasse 1\n10115 Berlin"
    assert second.json()["phone"] == "+49 30 1234567"

    third = admin.put("/api/v1/company-profile", json={"address": ""})
    assert third.status_code == 200
    assert third.json()["address"] == ""
    assert third.json()["legal_name"] == "Acme Builders GmbH"
    assert third.json()["phone"] == "+49 30 1234567"

    assert read_company_profile(_data_dir) == third.json()


def test_put_sanitises_what_it_stores(admin: TestClient, _data_dir: Path) -> None:
    response = admin.put("/api/v1/company-profile/", json={"legal_name": "x" * (MAX_LEGAL_NAME + 10)})
    assert response.json()["legal_name"] == "x" * MAX_LEGAL_NAME
    assert read_company_profile(_data_dir)["legal_name"] == "x" * MAX_LEGAL_NAME


@pytest.mark.parametrize(
    ("logo", "reason"),
    [
        pytest.param("data:image/gif;base64,R0lGODlhAQABAAAAACw=", "unsupported_format", id="gif"),
        pytest.param("https://acme.example/logo.png", "unsupported_format", id="remote-url"),
        pytest.param("data:image/png;base64,", "unsupported_format", id="empty-payload"),
        pytest.param("data:image/png,rawbytes", "unsupported_format", id="not-base64"),
        # An explicit id: the value is 4 MiB, and pytest builds the tmp dir name from the id.
        pytest.param("data:image/png;base64," + "A" * MAX_LOGO_DATA_URL_CHARS, "too_large", id="over-the-cap"),
    ],
)
def test_an_unusable_logo_is_refused_and_the_stored_one_kept(
    logo: str, reason: str, admin: TestClient, _data_dir: Path
) -> None:
    """Sanitised to ``""`` and merged, a bad upload would delete the good logo behind a 200.

    The whole request is refused, so the name sent alongside it is not
    applied either: a half-applied save is harder to reason about than none.
    """
    write_company_profile(_FULL_PROFILE, _data_dir)

    response = admin.put(
        "/api/v1/company-profile/",
        json={"document_logo_data_url": logo, "legal_name": "Renamed Ltd"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["field"] == "document_logo_data_url"
    assert detail["reason"] == reason
    assert detail["accepted_types"] == [f"image/{kind}" for kind in LOGO_IMAGE_TYPES]
    assert detail["max_chars"] == MAX_LOGO_DATA_URL_CHARS
    assert detail["message"]
    assert read_company_profile(_data_dir) == _FULL_PROFILE


@pytest.mark.parametrize("cleared", ["", "   "])
def test_an_empty_logo_clears_it_on_purpose(cleared: str, admin: TestClient, _data_dir: Path) -> None:
    write_company_profile(_FULL_PROFILE, _data_dir)

    response = admin.put("/api/v1/company-profile/", json={"document_logo_data_url": cleared})

    assert response.status_code == 200
    assert response.json()["document_logo_data_url"] == ""
    assert response.json()["legal_name"] == _FULL_PROFILE["legal_name"]
    assert read_company_profile(_data_dir)["document_logo_data_url"] == ""


def test_a_usable_logo_replaces_the_stored_one(admin: TestClient, _data_dir: Path) -> None:
    write_company_profile(_FULL_PROFILE, _data_dir)
    replacement = "data:image/svg+xml;base64,PHN2Zy8+"

    response = admin.put("/api/v1/company-profile/", json={"document_logo_data_url": replacement})

    assert response.status_code == 200
    assert read_company_profile(_data_dir)["document_logo_data_url"] == replacement


def test_delete_clears_the_profile(admin: TestClient, _data_dir: Path) -> None:
    write_company_profile(_FULL_PROFILE, _data_dir)
    response = admin.delete("/api/v1/company-profile/")
    assert response.status_code == 200
    assert response.json() == DEFAULT_COMPANY_PROFILE
    assert not company_profile_path(_data_dir).exists()


def test_the_options_are_the_numbers_the_sanitiser_enforces(admin: TestClient) -> None:
    """The form is built from this response; a number it disagrees on is a control that lies."""
    options = admin.get("/api/v1/company-profile/options/").json()

    assert options["max_address_lines"] == MAX_ADDRESS_LINES
    assert options["max_logo_data_url_chars"] == MAX_LOGO_DATA_URL_CHARS
    assert options["max_lengths"] == {**_LINE_CAPS, "address": MAX_ADDRESS_CHARS}
    for field, cap in options["max_lengths"].items():
        assert len(sanitise({field: "z" * (cap + 1)})[field]) == cap
    for mime in options["logo_mime_types"]:
        logo = f"data:{mime};base64,AAAA"
        assert sanitise({"document_logo_data_url": logo})["document_logo_data_url"] == logo


def test_the_public_branding_endpoint_never_carries_the_profile(_data_dir: Path) -> None:
    """The branding GET answers anonymous callers; the letterhead must stay out of it."""
    from app.core.branding_router import BrandingResponse
    from app.core.branding_router import router as branding_router

    sentinels = {
        "document_logo_data_url": "data:image/png;base64,U0VOVElORUxMT0dP",
        "legal_name": "Sentinel Legal Name GmbH",
        "address": "Sentinel Street 9\nSentinel City",
        "registration_line": "USt-IdNr. DE999999999",
        "phone": "+00 000 SENTINEL",
        "email": "sentinel@private.example",
        "website": "sentinel-private.example",
    }
    write_company_profile(sentinels, _data_dir)
    write_branding({"mode": "text", "company_name": "Public Brand"}, _data_dir)

    app = FastAPI()
    app.include_router(branding_router, prefix="/api/v1")
    app.include_router(company_profile_router, prefix="/api/v1")
    with TestClient(app) as client:
        response = client.get("/api/v1/branding/")

    assert response.status_code == 200
    assert response.json()["company_name"] == "Public Brand"
    assert set(response.json()) == set(BrandingResponse.model_fields)
    for value in sentinels.values():
        for line in value.split("\n"):
            assert line not in response.text
