# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow - the tier-one workflow spine for every register.

A flat tick-list is not how a real project runs: work passes GATES (a
hold point somebody owns and signs) and hits ROUTES (a decision that
sends the item down a different path). Ported from the source workflow app
Portfolio, where the shape was proven over 19 live jobs.

Three step shapes, one ordered list per item:
    step   - a plain action
    gate   - ⛔ somebody signs; cannot be skipped or marked not-required
    route  - 🔀 a decision; picking a branch APPENDS that branch's steps

Rails enforced SERVER-SIDE (a rail enforced in one code path is not a
rail): steps complete in order, completed steps are immutable history,
gates refuse to pass while their subject-specific check fails, and every
completion writes an audit event.
"""
