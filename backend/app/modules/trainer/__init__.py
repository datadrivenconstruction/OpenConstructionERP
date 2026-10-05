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
    course load, so a normal install pays nothing for this module. With it on,
    the ``trainer_spec`` rule set is registered and the courses are loaded;
    neither can raise out of here.
    """
    from app.config import get_settings
    from app.modules.trainer.permissions import register_trainer_permissions

    register_trainer_permissions()

    if not get_settings().academy_mode:
        return

    # Load the courses from ``settings.trainer_courses_dir`` (Wave 1). Nothing
    # here may stop the boot: a bad course is stored as invalid, and any other
    # failure is logged with the stored courses left as they were. Wave 2 adds
    # the recheck handlers below.
    try:
        from app.modules.trainer import loader
        from app.modules.trainer.validators import register_trainer_rules

        register_trainer_rules()
        await loader.load_courses_at_startup()
    except Exception:  # the boot must never crash on the trainer
        logger.exception("Academy mode is on, but the trainer course load failed")
