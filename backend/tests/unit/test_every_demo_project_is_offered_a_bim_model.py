# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every demo project is offered a BIM model.

``install_demo_project`` only attaches CAD/BIM assets when
``bundle_key_for(demo_id)`` returns a bundle. A demo template that is missing
from ``BUNDLE_MAP`` is never even offered to ``attach_demo_assets``, so it ends
up with no ``BIMModel`` row at all.

Nothing complains when that happens. A missing model is not an error anywhere;
it is an absence that other seeders read as "nothing to do":

    * ``app.modules.bcf.seed`` returns early on a project with no model and
      logs the skip at debug level, so the BCF issue register stays empty and
      the log says nothing at INFO.
    * ``app.modules.bim_hub.seed`` federates existing models only, so a project
      with none gets no federation either.

The result is a project that opens on an empty coordination surface with
nothing on screen to say the data is missing rather than the feature broken.

Seven templates had drifted out of the map this way - each pack landed after
``seed_demo_assets`` was written and nobody added the row. The count is not
what this test guards. It asserts the invariant instead: every template that
resolves is offered a bundle, so the next pack that lands unmapped goes red
here rather than shipping an empty register.

These assertions read module-level registries only and need no database.
"""

from __future__ import annotations

from app.core.demo_projects import DEMO_TEMPLATES
from app.scripts.seed_demo_assets import _SKIP_DEMOS, BUNDLES, bundle_key_for

#: Floor on the registry size. ``DEMO_TEMPLATES`` is filled by an import
#: side-effect at the foot of ``demo_projects`` (``import app.core.demo_packs``)
#: that is wrapped in a bare ``except``. If pack registration ever breaks, the
#: registry falls back to the five built-ins and every assertion below would
#: pass over almost nothing. The floor turns that silent collapse into a
#: failure. It sits under the shipped count so adding a pack never trips it.
MINIMUM_TEMPLATES = 30


def test_the_template_registry_actually_loaded() -> None:
    """A collapsed registry must fail rather than make the rest vacuous."""
    assert len(DEMO_TEMPLATES) >= MINIMUM_TEMPLATES, (
        f"only {len(DEMO_TEMPLATES)} demo templates registered - partner-pack "
        "registration probably failed, which would make the coverage assertion "
        "below pass over an almost empty registry"
    )


def test_every_demo_template_is_offered_a_bim_model() -> None:
    """No template may fall through ``bundle_key_for`` and lose its model."""
    unmapped = sorted(
        demo_id for demo_id in DEMO_TEMPLATES if demo_id not in _SKIP_DEMOS and bundle_key_for(demo_id) is None
    )
    assert not unmapped, (
        "these demo projects are seeded with no BIM model, so their BCF issue "
        f"register and coordination federation come up empty: {unmapped}. Add "
        "each one to BUNDLE_MAP in app/scripts/seed_demo_assets.py."
    )


def test_every_bundle_key_resolves_to_a_bundle() -> None:
    """A typo'd bundle key is the same empty screen by another route."""
    broken = sorted(
        demo_id for demo_id in DEMO_TEMPLATES if (key := bundle_key_for(demo_id)) is not None and key not in BUNDLES
    )
    assert not broken, f"demo projects mapped to a bundle that does not exist: {broken}"


def test_the_heilbronn_procedural_bundle_stays_with_heilbronn() -> None:
    """Only Heilbronn may claim the model built from Heilbronn's geometry.

    ``_attach_demo_assets_inner`` dispatches to the procedural path on the
    bundle key alone, and that path attaches a model generated from one
    specific building. A sibling retail demo pointed at this bundle would be
    handed a model of the wrong building and present it as its own, which is a
    worse defect than the empty screen the map exists to prevent.
    """
    claimants = sorted(demo_id for demo_id in DEMO_TEMPLATES if bundle_key_for(demo_id) == "retail_heilbronn")
    assert claimants == ["retail-market-heilbronn"], (
        f"the Heilbronn procedural model is claimed by {claimants}; every other "
        "project must take a generic bundle until it has assets of its own"
    )
