"""Tests for BOQ templates data integrity.

Verifies that all 8 built-in templates are present, structurally valid,
and contain sensible data (positive rates, no duplicate ordinals, etc.).
"""

import pytest

from app.modules.boq.templates import TEMPLATES

EXPECTED_TEMPLATE_IDS = [
    "residential",
    "office",
    "warehouse",
    "school",
    "hospital",
    "hotel",
    "retail",
    "infrastructure",
]


class TestTemplatesExistence:
    def test_all_eight_templates_exist(self):
        assert len(TEMPLATES) == 8

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_template_present(self, template_id: str):
        assert template_id in TEMPLATES, f"Template '{template_id}' is missing"


class TestTemplateStructure:
    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_template_has_name(self, template_id: str):
        tmpl = TEMPLATES[template_id]
        assert "name" in tmpl
        assert isinstance(tmpl["name"], str)
        assert len(tmpl["name"]) > 0

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_template_has_description(self, template_id: str):
        tmpl = TEMPLATES[template_id]
        assert "description" in tmpl
        assert isinstance(tmpl["description"], str)
        assert len(tmpl["description"]) > 0

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_template_has_sections(self, template_id: str):
        tmpl = TEMPLATES[template_id]
        assert "sections" in tmpl
        assert isinstance(tmpl["sections"], list)
        assert len(tmpl["sections"]) > 0


class TestSectionStructure:
    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_each_section_has_ordinal_and_description(self, template_id: str):
        for section in TEMPLATES[template_id]["sections"]:
            assert "ordinal" in section, f"Section missing ordinal in {template_id}"
            assert "description" in section, f"Section missing description in {template_id}"

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_each_section_has_positions(self, template_id: str):
        for section in TEMPLATES[template_id]["sections"]:
            assert "positions" in section
            assert isinstance(section["positions"], list)
            assert len(section["positions"]) > 0, (
                f"Section '{section.get('ordinal')}' in '{template_id}' has no positions"
            )


class TestPositionData:
    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_positions_have_required_fields(self, template_id: str):
        required = {"ordinal", "description", "unit", "qty_factor", "rate"}
        for section in TEMPLATES[template_id]["sections"]:
            for pos in section["positions"]:
                missing = required - set(pos.keys())
                assert not missing, (
                    f"Position '{pos.get('ordinal', '?')}' in '{template_id}' "
                    f"missing fields: {missing}"
                )

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_qty_factor_is_positive(self, template_id: str):
        for section in TEMPLATES[template_id]["sections"]:
            for pos in section["positions"]:
                assert pos["qty_factor"] > 0, (
                    f"qty_factor <= 0 for '{pos['ordinal']}' in '{template_id}'"
                )

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_rate_is_positive(self, template_id: str):
        for section in TEMPLATES[template_id]["sections"]:
            for pos in section["positions"]:
                assert pos["rate"] > 0, (
                    f"rate <= 0 for '{pos['ordinal']}' in '{template_id}'"
                )

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_no_duplicate_ordinals(self, template_id: str):
        ordinals: list[str] = []
        for section in TEMPLATES[template_id]["sections"]:
            for pos in section["positions"]:
                ordinals.append(pos["ordinal"])
        assert len(ordinals) == len(set(ordinals)), (
            f"Duplicate ordinals found in '{template_id}': "
            f"{[o for o in ordinals if ordinals.count(o) > 1]}"
        )

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_ordinal_is_non_empty_string(self, template_id: str):
        for section in TEMPLATES[template_id]["sections"]:
            for pos in section["positions"]:
                assert isinstance(pos["ordinal"], str)
                assert len(pos["ordinal"]) > 0

    @pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
    def test_unit_is_non_empty_string(self, template_id: str):
        for section in TEMPLATES[template_id]["sections"]:
            for pos in section["positions"]:
                assert isinstance(pos["unit"], str)
                assert len(pos["unit"]) > 0
