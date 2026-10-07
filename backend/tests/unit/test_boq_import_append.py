from copy import deepcopy

from app.modules.boq.import_append import append_import_ordinals


def test_repeated_tree_reserves_existing_roots_and_preserves_section_references():
    rows = [
        {"ordinal": "1", "is_section": True},
        {"ordinal": "1.2", "is_section": True},
        {"ordinal": "1.2.1", "metadata": {"import_section": "1.2", "xpwe_vc_id": "7"}},
        {"ordinal": "2", "is_section": True},
        {"ordinal": "2.1", "classification": {"gaeb_section": "2", "national_code": "2.1"}},
        {"ordinal": "3", "metadata": {"import_section": ""}},
    ]
    append_import_ordinals(rows, ["1", "1.2", "4.8", "6"])
    assert [r["ordinal"] for r in rows] == ["7", "7.2", "7.2.1", "8", "8.1", "9"]
    assert rows[2]["metadata"] == {"import_section": "7.2", "xpwe_vc_id": "7", "import_original_ordinal": "1.2.1"}
    assert rows[4]["classification"] == {"gaeb_section": "8", "national_code": "2.1"}
    assert rows[5]["metadata"]["import_section"] == ""


def test_noncolliding_and_id_roundtrip_rows_remain_unchanged():
    for rows, existing in [
        ([{"ordinal": "2", "metadata": {"import_section": ""}}], ["1"]),
        ([{"ordinal": "1", "position_id": "existing-id"}, {"ordinal": "2"}], ["1", "2"]),
    ]:
        before = deepcopy(rows)
        append_import_ordinals(rows, existing)
        assert rows == before
