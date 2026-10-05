# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer (Academy) module.

A paid course runs inside a learner's own project: the learner prices a bill,
levels bids, values a claim and a variation, and a deterministic checker reads
the results back out of the ERP. Modules open one at a time as checked tasks
pass. The UI calls it "Academy"; identifiers say ``trainer`` because
``academy`` already names the video catalogue.

The module is always loaded and inert unless ``settings.academy_mode`` is on.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Register permissions; everything else waits for the academy flag.

    Permissions are registered on every install so role matrices and the
    permission listing stay the same whether or not the flag is on. With the
    flag off nothing else happens: no rule set, no event subscription and no
    course load, so a normal install pays nothing for this module.
    """
    from app.config import get_settings
    from app.modules.trainer.permissions import register_trainer_permissions

    register_trainer_permissions()

    if not get_settings().academy_mode:
        return

    # Wave 1 and 2 hook in here: register the ``trainer_spec`` rule set, load
    # the courses from ``settings.trainer_courses_dir`` and subscribe the
    # recheck handlers.
    logger.info("Academy mode is on; the trainer has no startup work yet")
