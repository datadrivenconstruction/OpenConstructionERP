"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the backup restore ownership remap (DB-free).

A backup is one user's own data. On restore into another account (typically on
another machine) every field that held the exporter's user id must be repointed
to the restoring user, and the ``users`` table must be skipped entirely.
"""

from __future__ import annotations

from app.modules.backup.service import (
    RESTORE_SKIP_KEYS,
    _is_sensitive_field,
    remap_owner_refs,
)


def test_remap_repoints_every_matching_field() -> None:
    old, new = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    record = {
        "id": "project-1",
        "owner_id": old,
        "created_by": old,
        "uploaded_by": old,
        "name": "Tower",
        "quantity": 5,
        "parent_id": None,
    }
    out = remap_owner_refs(record, old, new)

    # Every field that held the exporter's id now points at the restorer...
    assert out["owner_id"] == new
    assert out["created_by"] == new
    assert out["uploaded_by"] == new
    # ...and nothing else is touched.
    assert out["id"] == "project-1"
    assert out["name"] == "Tower"
    assert out["quantity"] == 5
    assert out["parent_id"] is None


def test_remap_is_a_noop_when_owner_is_unchanged_or_unknown() -> None:
    record = {"owner_id": "aaaa"}
    # Same owner: nothing to do.
    assert remap_owner_refs(record, "aaaa", "aaaa") == record
    # No exporter id on the manifest: leave the record as-is.
    assert remap_owner_refs(record, "", "bbbb") == record


def test_remap_does_not_mutate_the_input() -> None:
    old, new = "aaaa", "bbbb"
    record = {"owner_id": old}
    remap_owner_refs(record, old, new)
    assert record["owner_id"] == old


def test_account_config_tables_are_never_restored() -> None:
    # Account-level config, not work data: kept as the restoring user's own.
    assert "users" in RESTORE_SKIP_KEYS
    assert "ai_settings" in RESTORE_SKIP_KEYS


def test_secrets_are_stripped_from_exports() -> None:
    # Password hashes and every AI provider key stay out of the archive.
    assert _is_sensitive_field("hashed_password")
    assert _is_sensitive_field("password_hash")
    assert _is_sensitive_field("anthropic_api_key")
    assert _is_sensitive_field("openai_api_key")
    # Ordinary work-data columns are kept.
    assert not _is_sensitive_field("name")
    assert not _is_sensitive_field("owner_id")
    assert not _is_sensitive_field("quantity")


def test_remap_forces_owner_columns_to_the_caller() -> None:
    # A crafted archive can put any user id in an owner column. Forcing the
    # table's ownership columns to the restoring user pins every row to the
    # caller regardless of what the archive claims - the anti-injection boundary.
    victim = "victim-99999999-9999-9999-9999-999999999999"
    caller = "caller-88888888-8888-8888-8888-888888888888"
    record = {"id": "p1", "owner_id": victim, "name": "Injected"}
    # The attacker leaves created_by empty to defeat the value-based remap...
    out = remap_owner_refs(record, "", caller, owner_columns=frozenset({"owner_id"}))
    # ...but the owner column is forced to the caller anyway.
    assert out["owner_id"] == caller
    assert out["name"] == "Injected"


def test_remap_without_owner_columns_keeps_value_only_behaviour() -> None:
    # With no owner_columns a field is repointed only when it equals the exporter
    # id, so a non-matching value is left as-is (the default 3-arg call).
    record = {"owner_id": "someone-else"}
    assert remap_owner_refs(record, "", "caller")["owner_id"] == "someone-else"


def test_secret_detection_is_broad_but_never_strips_storage_keys() -> None:
    # Broadened detection catches more credential-shaped column names...
    assert _is_sensitive_field("webhook_secret")
    assert _is_sensitive_field("access_token")
    assert _is_sensitive_field("api_key")
    assert _is_sensitive_field("smtp_password")
    # ...without ever stripping the storage-key columns a file restore needs.
    assert not _is_sensitive_field("object_key")
    assert not _is_sensitive_field("storage_key")
    assert not _is_sensitive_field("file_path")
    assert not _is_sensitive_field("sort_key")
