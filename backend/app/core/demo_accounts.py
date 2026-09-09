# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The seeded demo identities, named once.

These three addresses are logins, not mailboxes. They live on a domain we
own, and on that domain exactly one mailbox exists, so a message addressed
to any of them is refused by the receiving server and comes back as a hard
bounce against our own sending reputation. In September 2026 that is what
took outbound mail down for the whole account: a background sweeper nudged
the same permanently overdue demo items twice a day, every one of those
nudges bounced, and the host disabled sending.

The list already existed in three places, each with a comment saying the
others had to stay in sync with it. This module is the one they now import,
so "in sync" is a property of the code rather than a request to the reader.

``is_demo_account`` is deliberately the only way to ask the question:
comparing an address by hand skips the case folding and the strip, and an
address that differs from the list only in case is exactly the one that
would slip past a guard and bounce.
"""

from __future__ import annotations

#: Logins seeded for the public walkthrough. Never mailable, see the module
#: docstring. Mirrors the specs in ``app.main._seed_demo_account``.
DEMO_ACCOUNT_EMAILS: frozenset[str] = frozenset(
    {
        "demo@openconstructionerp.com",
        "estimator@openconstructionerp.com",
        "manager@openconstructionerp.com",
    }
)


#: The ``ADMIN_EMAIL`` each seeder script under ``app/scripts`` registers.
#: They log in and, failing that, POST a registration, so any installation
#: that has run one of those scripts holds the account. None of them is a
#: mailbox: they were created as credentials and no inbox was ever made.
#:
#: ``demo@openestimator.io`` is not a typo of the other. It is a different
#: domain, seeded only by ``seed_demo_v2``, and it is the reason this list is
#: kept beside a test that reads the constants back out of the scripts rather
#: than being maintained by hand. A grep written from memory for our three
#: known domains does not match it, which is how it stayed unguarded.
SEEDED_ADMIN_EMAILS: frozenset[str] = frozenset(
    {
        "admin@openestimate.io",
        "demo@openestimator.io",
    }
)

#: Every address the product must refuse to send mail to.
#:
#: Deliberately NOT folded into ``DEMO_ACCOUNT_EMAILS`` above, because that
#: set is not only "these are not mailboxes". It is also the whitelist of the
#: passwordless ``/auth/demo-login`` endpoint and the list the demo reset
#: deletes, so putting an admin address in it would hand out a password-free
#: login to an administrator account. The two questions happen to have had the
#: same answer for three addresses; they are not the same question.
NON_MAILBOX_LOGINS: frozenset[str] = DEMO_ACCOUNT_EMAILS | SEEDED_ADMIN_EMAILS


def is_demo_account(email: str | None) -> bool:
    """True when ``email`` is one of the seeded demo logins.

    This is the authentication question: may this address use the demo
    login, and is it cleared by the demo reset. For "may we send mail to
    it", ask :func:`is_non_mailbox_login` instead - the sets differ.
    """
    if not email:
        return False
    return email.strip().lower() in DEMO_ACCOUNT_EMAILS


def is_non_mailbox_login(email: str | None) -> bool:
    """True when ``email`` is a seeded login rather than a real mailbox.

    Every address this returns True for bounces, because it was created by a
    seeder as a credential and no mailbox was ever made for it. This is the
    question the mail transport has to ask.
    """
    if not email:
        return False
    return email.strip().lower() in NON_MAILBOX_LOGINS
