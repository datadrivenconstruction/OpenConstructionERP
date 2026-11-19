"""A person who installs this product can sign in to the account they just made.

The report this file exists for, in the installer's own sequence: a fresh
Windows install, the CLI started against an empty data directory, the first
account created through the sign-up page, and every sign-in after it answered
"Invalid email or password" - including after the data directory was renamed and
the account created again. Nothing else on the screen disagreed: the sign-up had
succeeded, proven by the second attempt answering "Email already registered".

Two independent defects produced that sentence, and they are indistinguishable
from the sign-in form, which is the third thing this file pins.

1. The two ends of the credential did not agree on what the password is.
   ``LoginRequest``, ``AdminUserCreate`` and ``ResetPasswordRequest`` carry
   ``str_strip_whitespace=True``; ``UserCreate`` - public registration - carried
   no ``model_config`` at all, and neither did ``ChangePasswordRequest`` or
   ``DeleteAccountRequest``. A password registered with a trailing space, a
   newline left by a paste or a leading space from an autofilled form was hashed
   exactly as typed, and every sign-in verified the stripped form against it.
   ``bcrypt.checkpw`` answers False forever, and the screen blames the password.
   Both schemas are read directly by
   ``test_a_password_registered_with_surrounding_whitespace_still_signs_in``,
   so the agreement cannot come apart again without that test naming which side
   moved.

2. A dormant account was reported as a wrong password. ``registration_mode``
   defaults to ``admin-approve``, so every registration after the bootstrap one
   is stored inactive, and ``login`` answered that with the same generic 401 it
   uses for bad credentials. Telling somebody their password is wrong is the one
   claim we can be sure is unfounded, because the password had already been
   checked and was right; the retry loop it sends them into cannot end. That is
   the dead end ``tests/integration/_auth_helpers.py`` had to write
   ``promote_to_admin`` and ``activate_user`` to get the fixtures out of, with no
   equivalent available to a person. ``login`` now answers a dormant account with
   403 and the stable code ``account_pending_activation``, and only after the
   password verified, which is what keeps it from being an enumeration oracle.

The shape of the tests follows the graph the report asks about, end to end over
HTTP: sign-up page payload -> ``POST /api/v1/users/auth/register/`` -> service
(bootstrap, role, ``is_active``) -> password hash -> row; then sign-in form ->
``POST /api/v1/users/auth/login/`` -> lookup -> verify -> active check -> token
mint -> response. Both routes are the real ones, with the real schemas, service,
repository and bcrypt, mounted at the paths the browser uses. What is substituted
is the database: a throwaway PostgreSQL cloned from the session template, which
is the only way "a clean install" means anything inside a suite that shares one
cluster, and the reason the bootstrap question is answerable at all.
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core.tenant_scope import TENANT_CLAIM
from app.dependencies import decode_access_token, get_session
from app.modules.users.models import User
from app.modules.users.router import router as users_router
from tests._pg import isolated_engine

REGISTER = "/api/v1/users/auth/register/"
LOGIN = "/api/v1/users/auth/login/"

#: Documentation-range addresses, one per test, because the throttles are keyed
#: per client address and their buckets are module-level globals that the whole
#: session shares. A test that reused another's address could be answered 429 by
#: a request it never made, and a red run naming a rate limit would name the
#: wrong cause.
_addresses = itertools.count(1)

GENERIC_REFUSAL = "Invalid email or password"

# ``ACCOUNT_PENDING_ACTIVATION`` and ``normalise_password`` are imported inside
# the tests that use them rather than here. Both are symbols this change
# introduces, and a module-level import of either would make every test in the
# file error at the revision the file was written against - an import error,
# which says nothing about the behaviour under test and hides the failures that
# do. Deferred, the refusal tests fail on the answer they were given.


#: The mode an installation ships in, read off the field rather than off the
#: environment: ``backend/tests/conftest.py`` sets ``REGISTRATION_MODE=open`` for
#: the whole suite, so ``get_settings().registration_mode`` is never the default
#: here and a test that assumed it would silently exercise a mode no installer
#: gets. That is why the dormant-account dead end was invisible to twenty green
#: jobs - not one test in the suite ran the shipped default.
SHIPPED_REGISTRATION_MODE = "admin-approve"


def _set_mode(mode: str) -> None:
    """Run the rest of this test in ``mode``, which the fixture below restores."""
    get_settings().registration_mode = mode  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _restore_registration_mode():
    """The settings object is a shared singleton; put the mode back afterwards."""
    settings = get_settings()
    saved = getattr(settings, "registration_mode", SHIPPED_REGISTRATION_MODE)
    yield
    settings.registration_mode = saved  # type: ignore[attr-defined]


@pytest_asyncio.fixture
async def clean_install() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    """A signed-in-nothing install: empty database, real routes, real client.

    Yields the client and a sessionmaker bound to the same throwaway database, so
    a test can read the row the route wrote instead of trusting the response that
    described it.
    """
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def _override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session
                await session.commit()

        app = FastAPI()
        app.include_router(users_router, prefix="/api/v1/users")
        app.dependency_overrides[get_session] = _override_session

        address = f"203.0.113.{next(_addresses) % 250 + 1}"
        transport = ASGITransport(app=app, client=(address, 4242))
        async with AsyncClient(transport=transport, base_url="http://clean-install.test") as client:
            yield client, factory


async def _register(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    """Post the sign-up form's payload and return the response body."""
    payload: dict[str, Any] = {
        "email": "abdoo@example.com",
        "password": "Qm7x!pl2wz",
        "full_name": "Abdoo",
        "company": "Nile Estimating",
        "job_title": "Owner",
    }
    payload.update(overrides)
    response = await client.post(REGISTER, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _login(client: AsyncClient, email: str, password: str):
    return await client.post(LOGIN, json={"email": email, "password": password})


async def _stored_user(factory: async_sessionmaker[AsyncSession], email: str) -> User:
    async with factory() as session:
        user = (await session.execute(select(User).where(User.email == email.lower()))).scalar_one()
        session.expunge(user)
        return user


def _claims(access_token: str) -> dict[str, Any]:
    return decode_access_token(access_token, get_settings())


# ── the first account on a clean install ─────────────────────────────────────


async def test_the_first_account_on_a_clean_install_signs_in(clean_install):
    """The sequence from the report, in the shipped default mode.

    ``registration_mode`` is ``admin-approve``, which stores every registration
    dormant - except the bootstrap one, which is the only account on a fresh
    install and has to be usable or the operator has no way in at all. This is
    the test that says what "a clean install" is for: register, then sign in with
    exactly what was registered, and be let in as an active administrator holding
    a token that names a tenant.
    """
    client, factory = clean_install
    # The shipped default, not the ``open`` the suite runs in: the bootstrap is
    # what makes a fresh install usable in a mode that otherwise waits for an
    # administrator who does not exist yet.
    _set_mode(SHIPPED_REGISTRATION_MODE)
    assert Settings.model_fields["registration_mode"].default == SHIPPED_REGISTRATION_MODE

    body = await _register(client)
    assert body["is_active"] is True, "the first account on a clean install must be usable"
    assert body["role"] == "admin"
    assert body["email"] == "abdoo@example.com"

    response = await _login(client, "abdoo@example.com", "Qm7x!pl2wz")
    assert response.status_code == 200, response.text
    tokens = response.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    claims = _claims(tokens["access_token"])
    assert claims["sub"] == body["id"]
    assert claims[TENANT_CLAIM], "a token minted at sign-in must name the tenant it scopes"

    # The row, not just the response describing it: active, an administrator, and
    # holding a hash of the password that was typed rather than of some
    # normalised form of it that no later request will reproduce.
    user = await _stored_user(factory, "abdoo@example.com")
    assert user.is_active is True
    assert user.role == "admin"
    assert user.hashed_password.startswith("$2b$")


async def test_the_sign_up_form_s_free_text_fields_do_not_change_the_outcome(clean_install):
    """A job title and a company are not credentials, and a referral answer is nothing.

    The report named two of them as suspects: the role field, which the sign-up
    page only accepts as a word, and the question "How did you find us?". Neither
    is sent as ``role`` - the form's field is ``job_title``, free text stored in
    the registration metadata - and ``UserCreate.role`` is constrained to the four
    real roles and defaults, so a word in that box cannot decide the account's
    privileges.

    The referral question is gone: the form stopped asking it and ``UserCreate``
    stopped accepting it, because nothing in the product ever read the answer back.
    What this case now asserts about it is the part an operator can be caught by -
    a browser still holding yesterday's bundle posts the field, and that request
    has to create the first administrator rather than be refused for a property the
    schema no longer declares. The answer is ignored and is not stored beside the
    account.
    """
    client, factory = clean_install

    body = await _register(
        client,
        email="owner@example.com",
        job_title="Owner",
        company="Asher Ramadan Contracting",
        how_found_us="a colleague recommended it",
    )
    assert body["is_active"] is True
    assert body["role"] == "admin", "the form's role box must not set the account's role"

    response = await _login(client, "owner@example.com", "Qm7x!pl2wz")
    assert response.status_code == 200, response.text
    assert _claims(response.json()["access_token"])[TENANT_CLAIM]

    user = await _stored_user(factory, "owner@example.com")
    registration = (user.metadata_ or {}).get("registration") or {}
    assert registration["company"] == "Asher Ramadan Contracting"
    assert registration["job_title"] == "Owner"
    assert "how_found_us" not in registration, "a field the form no longer asks must not be stored"


async def test_an_address_typed_in_mixed_case_with_spaces_signs_in(clean_install):
    """The address is normalised the same way at both ends.

    ``EmailStr`` strips and lowercases the domain for both schemas, and the
    repository lowercases before it looks anything up, so a person who types
    their address differently on the two screens is not locked out by it. This
    was one of the report's hypotheses; it is covered because the answer has to
    stay no.
    """
    client, _factory = clean_install

    body = await _register(client, email="  Abdoo@Example.COM  ")
    # ``EmailStr`` strips the spaces and lowercases the domain; ``register``
    # lowercases the local part too before it stores the row, so what comes back
    # is the address in the form every later lookup will use.
    assert body["email"] == "abdoo@example.com"

    for typed in ("Abdoo@Example.COM", "abdoo@example.com", "  abdoo@example.com "):
        response = await _login(client, typed, "Qm7x!pl2wz")
        assert response.status_code == 200, f"{typed!r}: {response.text}"


# ── the password the two ends disagree about ─────────────────────────────────


async def test_a_password_registered_with_surrounding_whitespace_still_signs_in(clean_install):
    """The defect behind the report: register stores it raw, sign-in strips it.

    At the revision this file was written against, ``UserCreate`` carried no
    ``model_config`` while ``LoginRequest`` carried ``str_strip_whitespace=True``.
    A password typed or pasted with a space at either end was hashed as typed and
    could never be verified again, on any install, in any registration mode, for
    as long as the row lived - and renaming the data directory and registering
    again reproduced it exactly, which is what the report describes.

    Both the padded and the stripped form have to sign in, because a person
    retyping their password will not reproduce a space they cannot see, and the
    one they can see is the one they will type.
    """
    client, _factory = clean_install

    body = await _register(client, email="padded@example.com", password="Qm7x!pl2wz ")
    assert body["is_active"] is True

    for typed in ("Qm7x!pl2wz ", "Qm7x!pl2wz", " Qm7x!pl2wz", "Qm7x!pl2wz\n"):
        response = await _login(client, "padded@example.com", typed)
        assert response.status_code == 200, f"{typed!r}: {response.text}"


def test_both_ends_of_a_credential_normalise_it_the_same_way():
    """The invariant, read off the two schemas rather than off one flow.

    The HTTP test above can only fail loudly for the padding it happens to try.
    This one asks the schemas directly, so a ``model_config`` added to one side
    and not the other - the drift that caused this - is named as such, with the
    two values that disagree printed, instead of surfacing as somebody's sign-in
    not working.
    """
    from app.modules.users.schemas import (
        AdminUserCreate,
        ChangePasswordRequest,
        DeleteAccountRequest,
        LoginRequest,
        ResetPasswordRequest,
        UserCreate,
        normalise_password,
    )

    # Fourteen characters stripped to thirteen, because ``AdminUserCreate``
    # demands twelve of a password it has already stripped - one schema's limit
    # is another's rejection, and the value has to satisfy all four at once.
    typed = "  Qm7x!pl2wz-99 \n"

    # Stored side: what the policy validator returns is what gets hashed.
    for schema, field in (
        (UserCreate, "password"),
        (AdminUserCreate, "password"),
        (ChangePasswordRequest, "new_password"),
        (ResetPasswordRequest, "new_password"),
    ):
        kwargs: dict[str, Any] = {
            "email": "someone@example.com",
            "full_name": "Some One",
            "current_password": typed,
            "token": "a-token",
            field: typed,
        }
        instance = schema(**{k: v for k, v in kwargs.items() if k in schema.model_fields})
        assert getattr(instance, field) == normalise_password(typed), f"{schema.__name__}.{field} stores it raw"

    # Compared side: sign-in strips, so what it verifies is the normalised form.
    assert LoginRequest(email="someone@example.com", password=typed).password == normalise_password(typed)
    # These two carry the *existing* password, which no policy validator sees, so
    # they are normalised by ``service.verify_password`` instead. Pinning the raw
    # value here is what says that is deliberate rather than overlooked.
    assert DeleteAccountRequest(current_password=typed).current_password == typed
    assert ChangePasswordRequest(current_password=typed, new_password=typed).current_password == typed

    from app.modules.users.service import hash_password, verify_password

    hashed = hash_password(typed)
    assert verify_password(typed, hashed)
    assert verify_password(normalise_password(typed), hashed), "the stripped form is what sign-in sends"
    assert not verify_password("Qm7x!pl2wzX", hashed)


async def test_a_long_password_with_symbols_and_a_non_ascii_character_signs_in(clean_install):
    """The other shape the report asked about: a real passphrase, not ``12345678``.

    Twelve characters with a symbol and a character outside ASCII. It is 15 bytes
    encoded, well inside the 72 bcrypt accepts, and it has to survive the trip
    through a JSON body, a Pydantic field, ``encode("utf-8")`` and back.
    """
    client, _factory = clean_install
    passphrase = "Nile–Cost!2026x"

    body = await _register(client, email="passphrase@example.com", password=passphrase)
    assert body["is_active"] is True

    response = await _login(client, "passphrase@example.com", passphrase)
    assert response.status_code == 200, response.text
    assert _claims(response.json()["access_token"])[TENANT_CLAIM]


async def test_a_password_bcrypt_cannot_hash_is_refused_at_the_door(clean_install):
    """Over 72 encoded bytes: refused at registration, not raised inside it.

    ``Field(max_length=128)`` allowed a password bcrypt refuses, and bcrypt
    raises rather than truncating - the behaviour
    ``test_hash_rejects_password_over_72_bytes`` pins. The two limits met inside
    the request, so ``hash_password`` raised and the sign-up answered 500. A
    person is told the limit instead, in the same 422 that tells them every other
    way a password was refused.
    """
    client, _factory = clean_install
    too_long = "Nîle–Cöst!2026" + "x" * 60

    response = await client.post(REGISTER, json={"email": "long@example.com", "password": too_long, "full_name": "L"})

    assert response.status_code == 422, response.text
    assert "72 bytes" in response.text


async def test_signing_in_with_an_over_long_password_is_refused_not_a_server_error(clean_install):
    """The same 72 bytes, arriving from the sign-in side.

    ``LoginRequest`` deliberately validates nothing about a password's shape:
    refusing one there for being too long would publish the policy to anybody who
    can reach the form. So the limit is met inside ``verify_password``, where it
    used to escape as a ``ValueError`` and reach the browser as a 500 - which the
    sign-in screen reads as "the server did not answer", about a server that had
    answered. A password bcrypt cannot hash cannot be the password on file, so it
    is a wrong password, and it is answered as one.
    """
    client, _factory = clean_install

    await _register(client, email="overlong@example.com")

    response = await _login(client, "overlong@example.com", "x" * 100)

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == GENERIC_REFUSAL


async def test_an_over_long_password_answers_the_same_whether_the_account_exists(clean_install):
    """The refusal above must not become a way to find out who has an account.

    ``login`` burns a bcrypt round against a dummy hash when the address is
    unknown, so that the two branches take alike long. Routed straight through
    ``verify_password``, that dummy check raised on a password bcrypt refuses
    while the branch for a known account caught the same error and answered 401 -
    so one over-long password told a stranger which addresses exist, in the
    status code rather than in the timing. Both branches answer 401 with the same
    generic detail, which is the only thing that keeps the pair indistinguishable.
    """
    client, _factory = clean_install

    await _register(client, email="known@example.com")

    over_long = "x" * 100
    known = await _login(client, "known@example.com", over_long)
    unknown = await _login(client, "nobody@example.com", over_long)

    assert (known.status_code, unknown.status_code) == (401, 401), (known.text, unknown.text)
    assert known.json()["detail"] == unknown.json()["detail"] == GENERIC_REFUSAL


# ── a dormant account says so ────────────────────────────────────────────────


async def test_a_dormant_account_is_told_it_is_dormant(clean_install):
    """The second registrant, in the mode this install ships in.

    The bootstrap is spent by the first account, so this one is stored inactive
    with the default role, and its password is correct. What it must not be told
    is that the password is wrong: that sends it into a retry loop with no exit,
    which is the dead end the report describes and the one the integration
    fixtures needed ``activate_user`` to get around.
    """
    from app.modules.users.service import ACCOUNT_PENDING_ACTIVATION

    client, factory = clean_install
    _set_mode(SHIPPED_REGISTRATION_MODE)

    await _register(client, email="first@example.com")
    body = await _register(client, email="second@example.com")
    assert body["is_active"] is False, "in admin-approve the second account waits for an administrator"
    assert body["role"] != "admin"

    response = await _login(client, "second@example.com", "Qm7x!pl2wz")

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == ACCOUNT_PENDING_ACTIVATION
    assert GENERIC_REFUSAL not in response.text

    user = await _stored_user(factory, "second@example.com")
    assert user.is_active is False


async def test_the_dormant_account_answer_does_not_reveal_anything_to_a_stranger(clean_install):
    """What makes the message above safe to send.

    The code is only ever returned once the password has verified, so the caller
    has already proved they hold the account's credential. Everybody else - a
    wrong password on a dormant account, a wrong password on an active one, an
    address nobody registered - still gets one indistinguishable answer, so
    nobody can walk the form to find out which addresses have accounts or which
    of them are waiting.
    """
    from app.modules.users.service import ACCOUNT_PENDING_ACTIVATION

    client, _factory = clean_install
    _set_mode(SHIPPED_REGISTRATION_MODE)

    await _register(client, email="first@example.com")
    await _register(client, email="second@example.com")

    refusals = [
        await _login(client, "second@example.com", "wrong-password-1"),  # dormant, wrong password
        await _login(client, "first@example.com", "wrong-password-1"),  # active, wrong password
        await _login(client, "nobody@example.com", "Qm7x!pl2wz"),  # no such account
    ]

    for response in refusals:
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == GENERIC_REFUSAL

    # The control that stops the three above passing on a server that refuses
    # everybody: the same two accounts still sign in with their own password.
    assert (await _login(client, "first@example.com", "Qm7x!pl2wz")).status_code == 200
    pending = await _login(client, "second@example.com", "Qm7x!pl2wz")
    assert pending.status_code == 403
    assert pending.json()["detail"] == ACCOUNT_PENDING_ACTIVATION


async def test_an_open_install_signs_every_registrant_straight_in(clean_install):
    """``OE_REGISTRATION_MODE=open`` is the way out, and it has to work.

    The pending-activation copy points a local installer at exactly this setting,
    so the claim is worth a test of its own: in ``open`` mode the second
    registrant is active too and signs in immediately, with a viewer's token.
    """
    client, _factory = clean_install
    _set_mode("open")

    await _register(client, email="first@example.com")
    body = await _register(client, email="second@example.com")
    assert body["is_active"] is True

    response = await _login(client, "second@example.com", "Qm7x!pl2wz")
    assert response.status_code == 200, response.text
    assert _claims(response.json()["access_token"])[TENANT_CLAIM]


# ── the recovery path from the command line ──────────────────────────────────


async def test_reset_password_gives_a_locked_out_account_its_way_back(clean_install):
    """``openconstructionerp reset-password`` against the data directory.

    The report's own recovery: an account nobody can sign in to, with no server
    able to mail a reset link because no mail is configured on a local install.
    The command works offline for the same reason ``promote-admin`` does, and it
    activates a dormant account, because handing back a password that is now
    correct and a sign-in that still refuses would be a second dead end.
    """
    from app.cli import _reset_user_password

    _client, factory = clean_install
    async with factory() as session:
        session.add(
            User(
                email="locked@example.com",
                hashed_password="not-a-bcrypt-hash",
                full_name="Locked Out",
                role="viewer",
                is_active=False,
            )
        )
        await session.commit()

    async with factory() as session:
        message = await _reset_user_password(session, "LOCKED@example.com ", "  Qm7x!pl2wz  ")
        await session.commit()
    assert "now active" in message

    user = await _stored_user(factory, "locked@example.com")
    assert user.is_active is True
    # The stored hash is of the normalised password, which is what sign-in sends.
    from app.modules.users.service import verify_password

    assert verify_password("Qm7x!pl2wz", user.hashed_password)
    assert not verify_password("Qm7x!pl2wzX", user.hashed_password)


async def test_reset_password_refuses_to_weaken_an_account_or_invent_one(clean_install):
    """The command cannot write a hash the sign-up form would have refused."""
    from app.cli import _reset_user_password

    _client, factory = clean_install
    async with factory() as session:
        session.add(
            User(
                email="keeper@example.com",
                hashed_password="not-a-bcrypt-hash",
                full_name="Keeper",
                role="admin",
                is_active=True,
            )
        )
        await session.commit()

    async with factory() as session:
        for refused in ("12345678", "short1", "a" * 73, "Abcd1234"):
            with pytest.raises(ValueError):
                await _reset_user_password(session, "keeper@example.com", refused)
        with pytest.raises(LookupError):
            await _reset_user_password(session, "nobody@example.com", "Qm7x!pl2wz")


def test_reset_password_is_a_cli_command_with_a_data_dir():
    """The command exists, is spelled as documented, and takes ``--data-dir``."""
    from app import cli

    args = cli._build_parser().parse_args(["reset-password", "ops@example.com", "--data-dir", "/tmp/oe"])

    assert args.command == "reset-password"
    assert args.email == "ops@example.com"
    assert args.data_dir is not None
    assert args.password is None, "the password is prompted for unless a script supplies it"

    with_prompt = cli._build_parser().parse_args(["reset-password", "ops@example.com", "--password", "Qm7x!pl2wz"])
    assert with_prompt.password == "Qm7x!pl2wz"


def test_reset_password_without_an_email_exits_before_touching_the_database():
    """No address means nothing to reset, and exit 2 says so before any connect."""
    from app import cli

    args = cli._build_parser().parse_args(["reset-password"])

    with pytest.raises(SystemExit) as exc:
        cli.cmd_reset_password(args)
    assert exc.value.code == 2
