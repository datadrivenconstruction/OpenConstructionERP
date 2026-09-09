# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Seed-account credentials for the standalone demo seed scripts.

This repository is public, so a literal password in a tracked file is a
published password. Every seed script therefore resolves its credential the
same way ``app.main._resolve_demo_password`` does: an operator-supplied
environment variable is honoured as-is, and with no variable set the script
mints a fresh ``secrets.token_urlsafe(16)`` that lives for this run only.

The seed scripts are standalone HTTP clients pointed at a running backend, so
they share the rule through this module rather than importing ``app.main``,
which would pull the whole FastAPI application in for one function.

Printing rule, mirrored from the same place: a generated password may be
printed once, because a random password nobody can read is useless. A password
that came from the environment is never printed, because the operator already
has it and seed output routinely lands in a log or a terminal recording.
"""

from __future__ import annotations

import os
import secrets

#: Environment variable that pins the seed account password across runs.
SEED_PASSWORD_ENV = "SEED_ADMIN_PASSWORD"


def resolve_seed_password(env_var: str = SEED_PASSWORD_ENV) -> tuple[str, bool]:
    """Resolve the password a seed script authenticates with.

    Args:
        env_var: Name of the environment variable to read.

    Returns:
        ``(password, was_generated)``. ``was_generated`` is ``True`` only when
        the variable was unset or empty and the password was minted for this
        run, which is also the only case in which it may be printed.
    """
    env_value = os.environ.get(env_var)
    if env_value:
        return env_value, False
    return secrets.token_urlsafe(16), True


def describe_seed_login(email: str, password: str, was_generated: bool, env_var: str = SEED_PASSWORD_ENV) -> str:
    """Build the single login line a seed run is allowed to print.

    Args:
        email: The seed account address.
        password: The resolved password.
        was_generated: Whether this run minted the password.
        env_var: Name of the environment variable that pins it.

    Returns:
        A line naming the account, carrying the password itself only when this
        run generated it and it exists nowhere else.
    """
    if was_generated:
        return f"Login: {email} / {password}   (generated for this run, set {env_var} to pin it)"
    return f"Login: {email} / the value of {env_var}"


def login_failed_message(status_code: int, email: str, env_var: str = SEED_PASSWORD_ENV) -> str:
    """Explain a rejected seed login instead of crashing on the missing token.

    A generated password only authenticates against an account this run just
    created. Whenever the account already exists, from an earlier seed run or
    from the platform's own boot seeder, the operator has to supply its
    password through the environment.

    Args:
        status_code: Status the login endpoint returned.
        email: The seed account address.
        env_var: Name of the environment variable that pins the password.

    Returns:
        A message naming the failure and the one way out of it.
    """
    return (
        f"Login failed for {email} (HTTP {status_code}). No default password ships with this "
        f"script any more, so set {env_var} to the password of that account and run again."
    )
