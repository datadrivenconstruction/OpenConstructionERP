# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Field-worker Daily Diary MVP (task #113, Epic F).

A field-first diary distinct from the legacy ``daily_diary`` module:

* Auth is **PIN-gated magic-link** (Epic F decision): worker submits a
  phone number, receives an SMS containing a one-time link plus a
  six-digit PIN. Opening the link consumes the token and starts a
  long-lived session scoped to a single project + the granted module(s).
* Permissions live in a **dedicated** ``oe_field_module_grant`` table -
  the standard RBAC stack is bypassed entirely so a field worker with no
  internal role can still access a granted module.
* MVP surface: draft → submit → approve diary entries, with append-only
  activities + S3-style attachments (200 MB cap, magic-byte gated).

Other field modules (timesheet, photos, deliveries) will reuse the same
grant + auth dependencies that live here.
"""


async def on_startup() -> None:
    """Module startup hook - register the diary validation rules."""
    from app.modules.field_diary.validators import register_field_diary_validation_rules

    register_field_diary_validation_rules()
