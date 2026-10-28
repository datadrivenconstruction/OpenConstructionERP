"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The HTTP surface over the bundled licence texts.

Mounted on a bare FastAPI app rather than through ``create_app``, so these run
without a database and without importing 190 modules. That the real app mounts
it is a separate question and is checked in
``tests/integration/test_license_texts_api.py``.

The traversal test matters more than it looks. The handler cannot traverse by
construction, because it matches the requested name against a listing of the
directory instead of joining it onto one, so this test can only ever pass. It
is here so that a later rewrite which does join a path has something that goes
red. It asserts on the refusal message as well as the status, because a 404
from Starlette's router and a 404 from our own listing look identical from the
outside, and only one of them is evidence about this handler.
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import license_router as license_router_module
from app.core.license_texts import LicenseTextsUnavailable, license_dir


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(license_router_module.router, prefix="/api/v1")
    return TestClient(app)


def _files_on_disk() -> set[str]:
    return {p.name for p in license_dir().iterdir() if p.is_file() and not p.name.startswith(".")}


def test_listing_answers_an_envelope_not_a_bare_array(client: TestClient) -> None:
    resp = client.get("/api/v1/licenses/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, dict), "a bare array breaks every caller the day paging arrives"
    assert set(body) >= {"items", "total"}
    assert body["total"] == len(body["items"])


def test_listing_names_every_file_actually_present(client: TestClient) -> None:
    """Enumerated from the directory, so a text added later needs no frontend edit."""
    body = client.get("/api/v1/licenses/").json()
    assert {item["name"] for item in body["items"]} == _files_on_disk()


def test_listing_is_public(client: TestClient) -> None:
    """No Authorization header anywhere in this file, and 200 throughout.

    A licence you have to sign in to read is barely better than a licence
    behind a link that does not resolve on a machine with no network.
    """
    assert client.get("/api/v1/licenses/").status_code == 200


def test_a_text_is_served_byte_for_byte(client: TestClient) -> None:
    directory = license_dir()
    for name in sorted(_files_on_disk()):
        resp = client.get(f"/api/v1/licenses/{name}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == name
        assert body["text"] == (directory / name).read_text(encoding="utf-8", errors="replace")
        assert body["size_bytes"] == (directory / name).stat().st_size


def test_a_name_not_in_the_listing_is_refused(client: TestClient) -> None:
    resp = client.get("/api/v1/licenses/LICENSE_NOT_A_THING")
    assert resp.status_code == 404
    assert "LICENSE_NOT_A_THING" in resp.json()["detail"]


@pytest.mark.parametrize(
    "attempt",
    [
        "..%5CNOTICE",
        "..%5C..%5C..%5CNOTICE",
        "%2e%2e",
        "%2e%2e%5cNOTICE",
        "..%5C..%5C..%5Capp%5Cconfig.py",
        "LICENSE_LGPL_3_0%5C..%5C..%5C..%5CNOTICE",
    ],
)
def test_a_traversal_that_reaches_the_handler_is_refused_by_the_listing(
    client: TestClient,
    attempt: str,
) -> None:
    """Backslashes, because those are the separators that get through to us.

    An encoded forward slash is decoded into a path separator before routing,
    so ``..%2FNOTICE`` never reaches this handler at all (covered below). A
    backslash is not a separator to Starlette and is one to Windows, so these
    arrive intact as ``name`` and are refused by the only thing refusing them:
    the lookup against the listing. The message is asserted, not just the
    status, because a 404 from the router and a 404 from us are identical from
    outside and only one of them is evidence about this code.
    """
    resp = client.get(f"/api/v1/licenses/{attempt}")
    assert resp.status_code == 404, resp.text
    assert "No bundled licence text named" in resp.json()["detail"], (
        "a 404 from the router is not evidence about this handler; the refusal has to be the listing lookup's"
    )


def test_the_traversal_above_would_have_worked_against_a_path_join() -> None:
    """Negative control: the attack is real, the listing is what stops it.

    Without this, the test above passes just as happily against a name that
    could never have escaped anywhere, and would go on passing after someone
    replaces the listing lookup with ``directory / name``. Here the naive join
    is performed and shown to land on a real file outside the directory.

    Which separator escapes is the platform's business, and the backslash form
    used above is a live attack only on Windows. On POSIX the same handler is
    still reachable with a traversing name by a direct call, which is what
    ``test_license_texts.py`` covers, so the join is worth showing either way.
    """
    escaping_name = "..\\..\\..\\NOTICE" if os.name == "nt" else "../../../NOTICE"
    escaped = (license_dir() / escaping_name).resolve()
    assert escaped.is_file(), (
        "fixture is stale: this join no longer reaches a file, so it no longer "
        "demonstrates that the handler had something to refuse"
    )
    assert "licenses" not in escaped.parts


@pytest.mark.parametrize(
    "attempt",
    ["..%2FNOTICE", "..%2F..%2F..%2FNOTICE", "%2Fetc%2Fpasswd"],
)
def test_a_slash_traversal_is_refused_before_it_reaches_the_handler(
    client: TestClient,
    attempt: str,
) -> None:
    """The second barrier, and it is not ours: ASGI decodes %2F into a separator.

    The path then has more segments than ``/{name}`` has, so the router
    declines to match and answers its own 404. Recorded rather than merged
    with the test above, because a reader who sees one traversal test pass
    should not have to guess which of the two things refused it.
    """
    resp = client.get(f"/api/v1/licenses/{attempt}")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Not Found"
    assert "GNU" not in resp.text


def test_no_file_outside_the_directory_can_be_reached(client: TestClient) -> None:
    """The general form of the test above: only names in the listing answer 200."""
    listed = _files_on_disk()
    outside = [
        "NOTICE",
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "config.py",
        "__init__.py",
    ]
    for name in outside:
        assert name not in listed, f"fixture is stale: {name} is now a licence text"
        assert client.get(f"/api/v1/licenses/{name}").status_code == 404


def test_an_unlocatable_directory_is_a_fault_not_an_absence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """503, not 404 and not an empty list.

    404 tells a reader there is no such licence. An empty listing tells them
    this build carries none. Both are false statements about our compliance
    made by a broken install, and the reader most likely to be asking is the
    one who cares most about the answer.
    """

    def _unavailable() -> None:
        raise LicenseTextsUnavailable("looked in: /nowhere")

    monkeypatch.setattr(license_router_module, "list_license_texts", _unavailable)

    listing = client.get("/api/v1/licenses/")
    assert listing.status_code == 503, listing.text
    assert "packaging fault" in listing.json()["detail"]

    one = client.get("/api/v1/licenses/LICENSE_LGPL_3_0")
    assert one.status_code == 503, one.text


def test_the_longest_text_arrives_whole_and_unescaped(client: TestClient) -> None:
    """The GPL is 35 kB, and a panel that shows 8 kB of it is worse than useless.

    Whole is the point: byte equality against the file is already asserted
    above for every text, so what this adds is the size, and that the angle
    brackets in the address block survive rather than arriving HTML-escaped.
    """
    on_disk = (license_dir() / "LICENSE_GPL_3_0").read_text(encoding="utf-8")
    text = client.get("/api/v1/licenses/LICENSE_GPL_3_0").json()["text"]
    assert len(text) > 30_000
    assert text == on_disk
    assert "&lt;" not in text
    assert "<https://www.gnu.org/licenses/>" in text
