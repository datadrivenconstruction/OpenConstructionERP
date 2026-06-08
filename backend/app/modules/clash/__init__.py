# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Clash / interference detection module.

Geometric AABB (axis-aligned bounding box) coordination over the
**canonical** BIM element store (``oe_bim_element.bounding_box``). It is
fully CAD-agnostic - there is NO IfcOpenShell / OCC / native-IFC runtime
dependency (the architecture guide §3). Bounding boxes are produced upstream by the
DDC cad2data pipeline and persisted on every imported element, so clash
detection just reads what is already there.

Surfaces a discipline×discipline clash **matrix** plus a per-pair result
list with a review workflow, and can push selected clashes out as native
BCF topics (via the ``oe_bcf`` module) so they round-trip into common
BIM coordination viewers without vendor lock-in.
"""


async def on_startup() -> None:
    """‌⁠‍Module startup hook - register RBAC permissions."""
    from app.modules.clash.permissions import register_clash_permissions

    register_clash_permissions()
