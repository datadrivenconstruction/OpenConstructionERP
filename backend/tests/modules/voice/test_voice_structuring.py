# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-logic tests for the voice-to-structured-entry engine (voice.structuring).

These cover the parts that must be right without a provider or a database: the
target registry, field cleaners (enum clamping, date normalization, length
caps), the no-LLM heuristic, LLM-result cleaning, the confidence rule, draft
assembly (both the LLM path and the degrade path), language mapping, and prompt
building. No network, no DB, no app config is touched, so this runs on the local
py3.11 interpreter too.
"""

from __future__ import annotations

from app.modules.voice import structuring

# --------------------------------------------------------------------------------------
# target registry
# --------------------------------------------------------------------------------------


def test_target_types_are_the_three_supported():
    assert set(structuring.target_types()) == {"diary_note", "defect", "task"}


def test_target_spec_known_and_unknown():
    assert structuring.target_spec("defect") is not None
    assert structuring.target_spec("  task  ") is not None  # trimmed
    assert structuring.target_spec("unknown") is None
    assert structuring.target_spec("") is None


def test_every_target_has_a_title_and_description_field():
    for target in structuring.target_types():
        spec = structuring.target_spec(target)
        assert spec is not None
        names = spec.field_names()
        assert "title" in names
        assert "description" in names


# --------------------------------------------------------------------------------------
# clip_text / clip_longtext
# --------------------------------------------------------------------------------------


def test_clip_text_collapses_whitespace_and_caps():
    assert structuring.clip_text("  a   b\n c  ", 100) == "a b c"
    assert structuring.clip_text("x" * 500, 10) == "x" * 10
    assert structuring.clip_text(42, 10) == ""


def test_clip_longtext_preserves_newlines_but_trims():
    out = structuring.clip_longtext("  line one  \n\n  line   two \n")
    assert out == "line one\n\nline two"
    assert structuring.clip_longtext(None) == ""


# --------------------------------------------------------------------------------------
# clamp_enum
# --------------------------------------------------------------------------------------


def test_clamp_enum_exact_and_case_insensitive():
    choices = ("low", "medium", "high", "critical")
    assert structuring.clamp_enum("HIGH", choices, "medium") == "high"
    assert structuring.clamp_enum("critical", choices, "medium") == "critical"


def test_clamp_enum_normalizes_spaces_and_hyphens():
    choices = ("general", "fire_safety", "hvac")
    assert structuring.clamp_enum("fire safety", choices, "general") == "fire_safety"
    assert structuring.clamp_enum("fire-safety", choices, "general") == "fire_safety"


def test_clamp_enum_falls_back_to_default_for_unknown():
    choices = ("low", "medium", "high")
    assert structuring.clamp_enum("banana", choices, "medium") == "medium"
    assert structuring.clamp_enum("", choices, "medium") == "medium"
    assert structuring.clamp_enum(None, choices, "medium") == "medium"
    assert structuring.clamp_enum(3, choices, "medium") == "medium"


# --------------------------------------------------------------------------------------
# normalize_date
# --------------------------------------------------------------------------------------


def test_normalize_date_accepts_iso_only():
    assert structuring.normalize_date("2026-07-09") == "2026-07-09"
    assert structuring.normalize_date("due by 2026-12-01 please") == "2026-12-01"


def test_normalize_date_rejects_vague_or_invalid():
    assert structuring.normalize_date("next week") == ""
    assert structuring.normalize_date("Friday") == ""
    assert structuring.normalize_date("2026-13-40") == ""  # out of range month/day
    assert structuring.normalize_date(None) == ""


# --------------------------------------------------------------------------------------
# clean_field (kind dispatch)
# --------------------------------------------------------------------------------------


def test_clean_field_dispatches_on_kind():
    title_f = structuring.FieldSpec(name="title", kind="title", prompt="")
    date_f = structuring.FieldSpec(name="due_date", kind="date", prompt="")
    enum_f = structuring.FieldSpec(
        name="priority", kind="enum", prompt="", choices=("low", "normal", "high", "urgent"), default="normal"
    )
    assert structuring.clean_field(title_f, "  Fix the door  ") == "Fix the door"
    assert structuring.clean_field(date_f, "2026-07-09") == "2026-07-09"
    assert structuring.clean_field(enum_f, "URGENT") == "urgent"
    assert structuring.clean_field(enum_f, "whatever") == "normal"


# --------------------------------------------------------------------------------------
# heuristic_fields (no-LLM fallback)
# --------------------------------------------------------------------------------------


def test_heuristic_defect_detects_category_and_priority():
    spec = structuring.target_spec("defect")
    assert spec is not None
    text = "There is a crack in the concrete column on level 3, this is urgent and unsafe."
    fields = structuring.heuristic_fields(spec, text)
    assert fields["category"] == "structural"  # "crack"/"column"/"concrete"
    assert fields["priority"] == "critical"  # "unsafe" beats "urgent"
    # Title is the first sentence; description is the whole note; free text empty.
    assert fields["title"].startswith("There is a crack")
    assert "crack" in fields["description"]
    assert fields["location"] == ""
    assert fields["trade"] == ""


def test_heuristic_task_priority_and_empty_date():
    spec = structuring.target_spec("task")
    assert spec is not None
    fields = structuring.heuristic_fields(spec, "Order more rebar asap for the pour.")
    assert fields["priority"] == "urgent"
    assert fields["due_date"] == ""  # never guessed without a model
    assert fields["title"].startswith("Order more rebar")


def test_heuristic_diary_entry_type_default_and_delivery():
    spec = structuring.target_spec("diary_note")
    assert spec is not None
    assert structuring.heuristic_fields(spec, "Nothing special today.")["entry_type"] == "general"
    delivery = structuring.heuristic_fields(spec, "A truck delivered 20 tonnes of sand this morning.")
    assert delivery["entry_type"] == "delivery"


# --------------------------------------------------------------------------------------
# clean_llm_fields
# --------------------------------------------------------------------------------------


def test_clean_llm_fields_reads_nested_fields_object():
    spec = structuring.target_spec("task")
    assert spec is not None
    llm = {
        "fields": {
            "title": "  Install the handrail  ",
            "description": "Handrail missing on the east stair.",
            "priority": "HIGH",
            "due_date": "by 2026-08-01",
            "ignored_extra": "x",
        }
    }
    fields = structuring.clean_llm_fields(spec, llm)
    assert fields["title"] == "Install the handrail"
    assert fields["priority"] == "high"
    assert fields["due_date"] == "2026-08-01"
    assert "ignored_extra" not in fields


def test_clean_llm_fields_reads_flat_object_and_defaults_missing():
    spec = structuring.target_spec("defect")
    assert spec is not None
    # Flat shape (no "fields" wrapper) + a missing enum -> its default.
    fields = structuring.clean_llm_fields(spec, {"title": "Loose socket"})
    assert fields["title"] == "Loose socket"
    assert fields["category"] == "general"
    assert fields["priority"] == "medium"
    assert fields["trade"] == ""


# --------------------------------------------------------------------------------------
# draft_confidence
# --------------------------------------------------------------------------------------


def test_confidence_is_none_without_llm():
    spec = structuring.target_spec("task")
    assert spec is not None
    assert structuring.draft_confidence(spec, None, {"title": "x"}) is None


def test_confidence_uses_model_value_clamped():
    spec = structuring.target_spec("task")
    assert spec is not None
    assert structuring.draft_confidence(spec, {"confidence": 0.77}, {}) == 0.77
    assert structuring.draft_confidence(spec, {"confidence": 5}, {}) == 1.0
    assert structuring.draft_confidence(spec, {"confidence": -1}, {}) == 0.0


def test_confidence_heuristic_rewards_populated_non_default_fields():
    spec = structuring.target_spec("task")
    assert spec is not None
    # Bare extraction, all defaults/empty -> base 0.5.
    thin = {"title": "", "description": "", "priority": "normal", "due_date": ""}
    assert structuring.draft_confidence(spec, {}, thin) == 0.5
    rich = {"title": "Do X", "description": "Detail", "priority": "high", "due_date": "2026-08-01"}
    assert structuring.draft_confidence(spec, {}, rich) == 0.9  # 0.5 + 4*0.1 capped at 0.4


# --------------------------------------------------------------------------------------
# assemble_draft (LLM path + degrade path)
# --------------------------------------------------------------------------------------


def test_assemble_draft_with_llm_result():
    spec = structuring.target_spec("defect")
    assert spec is not None
    llm = {
        "fields": {
            "title": "Cracked column",
            "description": "Vertical crack in column C3.",
            "location": "Level 3, gridline C",
            "trade": "structural",
            "category": "structural",
            "priority": "critical",
        },
        "refined_text": "There is a vertical crack in column C3 on level 3.",
        "detected_language": "English",
        "confidence": 0.88,
    }
    draft = structuring.assemble_draft(spec=spec, llm_result=llm, text="raw note")
    assert draft["ai_generated"] is True
    assert draft["target_type"] == "defect"
    assert draft["fields"]["category"] == "structural"
    assert draft["fields"]["priority"] == "critical"
    assert draft["fields"]["location"] == "Level 3, gridline C"
    assert draft["refined_text"].startswith("There is a vertical crack")
    assert draft["detected_language"] == "English"
    assert draft["confidence"] == 0.88


def test_assemble_draft_degrades_without_llm():
    spec = structuring.target_spec("task")
    assert spec is not None
    draft = structuring.assemble_draft(
        spec=spec,
        llm_result=None,
        text="Fix the leaking tap in unit 4 urgently.",
        detected_language_hint="en",
    )
    assert draft["ai_generated"] is False
    assert draft["confidence"] is None
    assert draft["fields"]["priority"] == "urgent"
    assert draft["fields"]["title"].startswith("Fix the leaking tap")
    # refined_text falls back to the raw note; detected language uses the hint.
    assert "leaking tap" in draft["refined_text"]
    assert draft["detected_language"] == "en"


def test_assemble_draft_backfills_empty_title_from_note():
    spec = structuring.target_spec("diary_note")
    assert spec is not None
    # LLM ran but gave no title -> assembly backfills from the note's first line.
    draft = structuring.assemble_draft(
        spec=spec,
        llm_result={"fields": {"title": "", "description": "Poured slab."}},
        text="Poured the ground-floor slab today. All good.",
    )
    assert draft["ai_generated"] is True
    assert draft["fields"]["title"].startswith("Poured the ground-floor slab")


# --------------------------------------------------------------------------------------
# language handling
# --------------------------------------------------------------------------------------


def test_language_name_maps_primary_subtag():
    assert structuring.language_name("de") == "German"
    assert structuring.language_name("pt-BR") == "Portuguese"
    assert structuring.language_name("zh_Hans") == "Chinese"
    assert structuring.language_name("") is None
    assert structuring.language_name(None) is None
    assert structuring.language_name("xx") is None


# --------------------------------------------------------------------------------------
# prompt building
# --------------------------------------------------------------------------------------


def test_build_prompt_lists_each_field_and_embeds_note():
    spec = structuring.target_spec("defect")
    assert spec is not None
    prompt = structuring.build_structuring_prompt(spec, "Cracked wall in room 4.", None)
    for name in ("title", "description", "location", "trade", "category", "priority"):
        assert f'"{name}"' in prompt
    assert "Cracked wall in room 4." in prompt
    # Enum options are spelled out so the model returns a valid value.
    assert "structural" in prompt and "fire_safety" in prompt


def test_build_prompt_truncates_long_note():
    spec = structuring.target_spec("task")
    assert spec is not None
    long_text = "x" * (structuring.MAX_TEXT_CHARS + 2000)
    prompt = structuring.build_structuring_prompt(spec, long_text, None)
    assert "[note truncated]" in prompt


def test_system_prompt_adds_translation_clause_for_known_language():
    spec = structuring.target_spec("task")
    assert spec is not None
    system_de = structuring.structuring_system_prompt(spec, "de")
    assert "German" in system_de
    system_none = structuring.structuring_system_prompt(spec, None)
    assert "German" not in system_none
