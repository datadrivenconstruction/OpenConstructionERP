# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Proof that the spec being installed is the spec a person actually reviewed.

Installing a module writes Python to disk and loads it into the running server.
The platform's answer to that is a human review step: the wizard renders every
file through ``/preview`` and a person reads them before pressing install. That
step is only worth anything if the server can tell a reviewed spec from an
unreviewed one, and it could not: ``/preview`` and the install endpoint took the
same request body, so an install carried no evidence that a preview had ever
happened. The review was enforced by the screen, not by the API.

A digest computed over the spec by the caller would not fix that, because any
caller can compute one without ever asking for a preview. Only something the
server issued proves the server was asked. So ``/preview`` returns a short-lived
token, and install refuses a spec that does not arrive with a matching one.

The token binds three things, and each one closes a different hole:

* the spec digest, so the files that were rendered for review are the files that
  get written, and not a spec edited after the reading;
* the user, so one person's preview cannot authorise another person's install;
* the issue time, so a token cannot be kept and replayed indefinitely.

An upgrade of an installed module is reviewed the same way, and its token also
names what it is for: a token issued for an upgrade does not install, and one
issued for an install does not upgrade. The key needs no claim of its own,
since it is part of the spec the digest covers.

Within that window a token is not spent by using it, and saying so is part of
the claim: spending one would need a record of the tokens already seen, which is
exactly the state this refuses to keep. Reuse buys very little, because a spec
that is already installed is refused as a conflict, so what it leaves open is a
reinstall of the same reviewed files after an uninstall, inside the hour, by the
person who read them.

It is a signed statement, not a secret, and it deliberately stores no state: a
review token needs no table, no migration and no cleanup job, which keeps the
single-database promise intact. The signature uses the deployment's JWT secret,
which is already refused at startup in staging and production when left at its
development default.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

from app.config import get_settings
from app.modules.module_builder.spec import ModuleSpec

#: How long a preview stays installable. Long enough to read every generated
#: file without hurrying, short enough that a token found later is worthless.
REVIEW_TOKEN_TTL_SECONDS = 3600

#: Version prefix, so a future change to the payload shape can be rejected
#: cleanly rather than mis-parsed.
_VERSION = "v1"

#: What a token authorises. An install token carries no purpose claim, so the
#: tokens issued before upgrades existed still read as install tokens.
INSTALL = "install"
UPGRADE = "upgrade"


class ReviewTokenInvalid(Exception):
    """The token does not prove that this exact spec was previewed by this user."""


def spec_digest(spec: ModuleSpec) -> str:
    """A stable digest of *spec*, independent of field order in the request.

    The spec is dumped in JSON mode so every value is a primitive, then encoded
    with sorted keys and no incidental whitespace, so two requests that mean the
    same module always digest the same and any change of substance digests
    differently.
    """
    canonical = json.dumps(
        spec.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sign(body: str) -> str:
    secret = get_settings().jwt_secret.encode("utf-8")
    return _b64(hmac.new(secret, body.encode("utf-8"), hashlib.sha256).digest())


def issue(spec: ModuleSpec, user_id: uuid.UUID | str, *, now: float | None = None, purpose: str = INSTALL) -> str:
    """Issue a review token for *spec* previewed by *user_id*, for *purpose*."""
    claims = {
        "v": _VERSION,
        "d": spec_digest(spec),
        "u": str(user_id),
        "t": int(now if now is not None else time.time()),
    }
    if purpose != INSTALL:
        claims["p"] = purpose
    body = _b64(
        json.dumps(
            claims,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return f"{body}.{_sign(body)}"


def verify(
    token: str, spec: ModuleSpec, user_id: uuid.UUID | str, *, now: float | None = None, purpose: str = INSTALL
) -> None:
    """Raise :class:`ReviewTokenInvalid` unless *token* proves the review.

    Signature first, then contents: a forged token is rejected before anything
    inside it is believed, and the comparison is constant-time so the signature
    cannot be discovered one byte at a time.
    """
    body, _, signature = token.partition(".")
    if not body or not signature or not hmac.compare_digest(signature, _sign(body)):
        raise ReviewTokenInvalid("review token signature does not verify")

    try:
        padding = "=" * (-len(body) % 4)
        claims = json.loads(base64.urlsafe_b64decode(body + padding))
    except Exception as exc:  # noqa: BLE001 - any malformed body is one failure
        raise ReviewTokenInvalid("review token is malformed") from exc

    if claims.get("v") != _VERSION:
        raise ReviewTokenInvalid("review token version is not supported")
    if claims.get("d") != spec_digest(spec):
        raise ReviewTokenInvalid("the spec being installed is not the spec that was previewed")
    if claims.get("u") != str(user_id):
        raise ReviewTokenInvalid("the review token was issued to a different user")
    if claims.get("p", INSTALL) != purpose:
        raise ReviewTokenInvalid(f"the review token was issued for another action than this {purpose}")

    age = (now if now is not None else time.time()) - float(claims.get("t", 0))
    if age > REVIEW_TOKEN_TTL_SECONDS:
        raise ReviewTokenInvalid("the review token has expired; preview the module again")
    if age < -60:
        raise ReviewTokenInvalid("the review token is not yet valid")
