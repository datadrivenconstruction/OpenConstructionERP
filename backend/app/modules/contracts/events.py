# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts module domain events.

Most contract lifecycle events are published inline from the service via
``event_bus.publish_detached`` (signed / amended / claim.submitted / etc.).
This module centralises the event-name constants that the Gap I progress
bridge introduces so subscribers and tests reference one canonical string
instead of a magic literal.

Event reference
───────────────
``contracts.claim.populated``
    Emitted after a draft progress claim has its line breakdown
    rebuilt from the latest progress observations and committed
    (``commit_preview_to_claim``). Payload::

        {
            "claim_id": str,
            "contract_id": str,
            "claim_number": str,
            "line_count": int,        # number of claim lines written
            "gross": str,             # Decimal-as-string, claim currency
            "retention": str,
            "net_due": str,
            "currency": str,
            "actor": str | None,
        }

    Finance / dashboard subscribers use it to refresh a claim's billed-to-date
    once it has been auto-populated from the field, without re-querying the
    whole contract. The event is informational only: it does NOT post to the
    cost spine (the certified-claim → actual posting is owned by Gap B/E and
    fires on ``contracts.claim.certified``).
"""

from __future__ import annotations

#: Emitted when a claim's lines are (re)built from progress observations.
CLAIM_POPULATED = "contracts.claim.populated"

#: Emitted when an extension-of-time claim is submitted for review. Payload::
#:
#:     {
#:         "eot_id": str,
#:         "contract_id": str,
#:         "eot_number": str,
#:         "days_claimed": int,
#:         "actor": str | None,
#:     }
EOT_SUBMITTED = "contracts.eot.submitted"

#: Emitted when an extension-of-time claim is decided (granted /
#: partially_granted / rejected). Payload::
#:
#:     {
#:         "eot_id": str,
#:         "contract_id": str,
#:         "eot_number": str,
#:         "status": str,                  # the decision status
#:         "days_claimed": int,
#:         "days_granted": int,
#:         "revised_completion_date": str | None,
#:         "actor": str | None,
#:     }
#:
#: Scheduling / dashboards subscribe to refresh the contract completion date
#: when time is granted. Informational only; it posts nothing to the ledger.
EOT_DECIDED = "contracts.eot.decided"

__all__ = ["CLAIM_POPULATED", "EOT_DECIDED", "EOT_SUBMITTED"]

# The completed-variation rollup into ``Contract.total_value`` is owned by one
# subscriber, ``_on_variation_completed`` in
# ``app.modules.notifications._wave5_cross_module_subscribers``. It carries the
# redelivery key, the project, currency and closed-contract guards and the
# mirrored change order dedupe. Do not add a second writer for
# ``variations.contract_sum.updated`` here: any second writer that works posts
# the same variation to the contract twice.
