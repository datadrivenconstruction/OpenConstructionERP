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


def is_demo_account(email: str | None) -> bool:
    """True when ``email`` is one of the seeded demo logins."""
    if not email:
        return False
    return email.strip().lower() in DEMO_ACCOUNT_EMAILS
