# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The demo logins carry invented role names per demo language, never the old placeholders."""

from __future__ import annotations

from pathlib import Path

from app.core import demo_account_names as names

ROOT = Path(__file__).resolve().parents[3]


def test_every_language_names_every_login_with_its_part() -> None:
    for language, table in names.DEMO_ACCOUNT_NAMES.items():
        assert set(table) == set(names.RETIRED_PLACEHOLDERS), language
        for name in table.values():
            person, _, part = name.partition(", ")
            assert len(person.split()) == 2 and part, (language, name)
    all_names = [n for table in names.DEMO_ACCOUNT_NAMES.values() for n in table.values()]
    assert len(set(all_names)) == len(all_names)
    assert not set(all_names) & set(names.RETIRED_PLACEHOLDERS.values())


def test_a_language_without_a_set_falls_back_to_english() -> None:
    assert names.demo_account_name(names.MANAGER_EMAIL, "de-DE") == "Katrin Seidl, Bauherrenvertretung"
    assert names.demo_account_name(names.MANAGER_EMAIL, "fr") == names.DEMO_ACCOUNT_NAMES["en"][names.MANAGER_EMAIL]


def test_no_retired_placeholder_is_left_in_the_code_that_seeds_or_shows_a_login() -> None:
    files = [
        "backend/app/main.py",
        "backend/app/core/demo_projects.py",
        "backend/app/scripts/seed_demo_estimates.py",
        "backend/app/scripts/seed_demo_showcase.py",
        "frontend/src/features/auth/LoginPage.tsx",
        "frontend/src/features/auth/LoginPageNext.tsx",
    ]
    for rel in files:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for placeholder in names.RETIRED_PLACEHOLDERS.values():
            assert placeholder not in text, (rel, placeholder)
